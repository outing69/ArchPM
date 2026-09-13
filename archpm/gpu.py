"""GPU telemetry.

NVIDIA: two long-running `nvidia-smi` processes that we read from, instead of
spawning a new process every tick. That saves ~30ms CPU per sample and, via
`pmon`, also gives per-process SM%/VRAM -- something the one-off queries don't
offer.

AMD/Intel: fall back to sysfs (`gpu_busy_percent`), without per-process data.
"""
from __future__ import annotations

import shutil
import subprocess
import threading
import time
from pathlib import Path

from .model import GpuSample

_PROC_TTL = 6.0  # a pid that hasn't shown up in pmon for 6s no longer uses the GPU


def _line_buffered(cmd: list[str]) -> list[str]:
    """nvidia-smi block-buffers when stdout is a pipe; stdbuf forces line buffering."""
    if shutil.which("stdbuf"):
        return ["stdbuf", "-oL", *cmd]
    return cmd


def _f(text: str) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


class GpuMonitor:
    """Background monitor. `sample()` and `processes()` are thread-safe and fast."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sample = GpuSample()
        self._procs: dict[int, tuple[float, float, float]] = {}  # pid -> (sm, mb, ts)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._procs_supported = False
        self.backend = "none"

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if shutil.which("nvidia-smi"):
            self.backend = "nvidia"
            self._spawn(self._nvidia_stats_loop)
            self._spawn(self._nvidia_pmon_loop)
        elif self._sysfs_card():
            self.backend = "sysfs"
            self._spawn(self._sysfs_loop)

    def _spawn(self, target) -> None:
        t = threading.Thread(target=target, daemon=True, name=target.__name__)
        t.start()
        self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()

    # -- readers -----------------------------------------------------------
    def sample(self) -> GpuSample | None:
        if self.backend == "none":
            return None
        with self._lock:
            return GpuSample(**{f: getattr(self._sample, f) for f in GpuSample.__slots__})

    def processes(self) -> dict[int, tuple[float, float]]:
        """pid -> (sm%, vram_mb). Empty if the backend can't provide it."""
        if not self._procs_supported:
            return {}
        cutoff = time.monotonic() - _PROC_TTL
        with self._lock:
            stale = [p for p, (_, _, ts) in self._procs.items() if ts < cutoff]
            for p in stale:
                del self._procs[p]
            return {p: (sm, mb) for p, (sm, mb, _) in self._procs.items()}

    @property
    def per_process_available(self) -> bool:
        return self._procs_supported

    # -- NVIDIA ------------------------------------------------------------
    _FIELDS = (
        "name,utilization.gpu,utilization.memory,memory.used,memory.total,"
        "temperature.gpu,power.draw,clocks.sm,fan.speed"
    )

    def _nvidia_stats_loop(self) -> None:
        cmd = _line_buffered([
            "nvidia-smi", f"--query-gpu={self._FIELDS}",
            "--format=csv,noheader,nounits", "-l", "1",
        ])
        for line in self._stream(cmd):
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 9:
                continue
            s = GpuSample(
                name=parts[0], util=_f(parts[1]), mem_util=_f(parts[2]),
                mem_used_mb=_f(parts[3]), mem_total_mb=_f(parts[4]),
                temp_c=_f(parts[5]), power_w=_f(parts[6]),
                clock_mhz=_f(parts[7]), fan_pct=_f(parts[8]),
            )
            with self._lock:
                self._sample = s

    def _nvidia_pmon_loop(self) -> None:
        cmd = _line_buffered(["nvidia-smi", "pmon", "-d", "1", "-s", "um"])
        for line in self._stream(cmd):
            if line.startswith("#"):
                continue
            f = line.split()
            # gpu pid type sm mem enc dec jpg ofa fb ccpm command
            if len(f) < 11 or not f[1].isdigit():
                continue
            self._procs_supported = True
            sm = _f(f[3].replace("-", "0"))
            fb = _f(f[9].replace("-", "0")) if len(f) > 9 else 0.0
            with self._lock:
                self._procs[int(f[1])] = (sm, fb, time.monotonic())

    def _stream(self, cmd: list[str]):
        """Keeps the subprocess running and yields lines; restarts on crash."""
        backoff = 2.0
        while not self._stop.is_set():
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, bufsize=1,
                )
            except OSError:
                return
            try:
                assert proc.stdout is not None
                for raw in proc.stdout:
                    if self._stop.is_set():
                        break
                    line = raw.strip()
                    if line:
                        yield line
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
            if self._stop.wait(backoff):
                return
            backoff = min(backoff * 2, 30.0)

    # -- sysfs (AMD/Intel) -------------------------------------------------
    @staticmethod
    def _sysfs_card() -> Path | None:
        for busy in sorted(Path("/sys/class/drm").glob("card*/device/gpu_busy_percent")):
            return busy.parent
        return None

    def _sysfs_loop(self) -> None:
        dev = self._sysfs_card()
        if dev is None:
            return
        name = (dev / "product_name")
        label = name.read_text().strip() if name.exists() else "GPU"
        hwmon = next(iter((dev / "hwmon").glob("hwmon*")), None)
        while not self._stop.is_set():
            s = GpuSample(name=label)
            s.util = _f(self._read(dev / "gpu_busy_percent"))
            used = _f(self._read(dev / "mem_info_vram_used"))
            total = _f(self._read(dev / "mem_info_vram_total"))
            s.mem_used_mb, s.mem_total_mb = used / 1048576.0, total / 1048576.0
            if hwmon:
                s.temp_c = _f(self._read(hwmon / "temp1_input")) / 1000.0
                s.power_w = _f(self._read(hwmon / "power1_average")) / 1e6
                s.clock_mhz = _f(self._read(hwmon / "freq1_input")) / 1e6
            with self._lock:
                self._sample = s
            self._stop.wait(1.0)

    @staticmethod
    def _read(path: Path) -> str:
        try:
            return path.read_text().strip()
        except OSError:
            return ""
