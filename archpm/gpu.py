"""GPU telemetry.

Per process, the first source is DRM fdinfo (fdinfo.py): every driver that
exports it, amdgpu, i915 and xe among them, without root or an extra package.
NVIDIA's proprietary driver exports nothing there, so `nvidia-smi pmon` fills
in what fdinfo cannot see.

For the card as a whole: NVIDIA via two long-running `nvidia-smi` processes
that we read from, instead of spawning a new process every tick. AMD (and
anything else exposing `gpu_busy_percent`): sysfs.
"""
from __future__ import annotations

import shutil
import subprocess
import threading
import time
from pathlib import Path

from .fdinfo import DrmFdinfo
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
        self.fdinfo = DrmFdinfo()

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
        """pid -> (busy%, device memory MB). Empty if no source can provide it.

        fdinfo comes first. nvidia-smi only adds what fdinfo does not cover:
        a process on an NVIDIA card next to an AMD one keeps both, the busy
        share being the larger and the memory the sum, one card each. Should
        a driver named nvidia ever export fdinfo, that entry wins outright so
        the same card is never counted twice.
        """
        out = self._nvidia_processes()
        for pid, (busy, mb, drivers) in self.fdinfo.processes().items():
            nv = out.get(pid)
            if nv is None or "nvidia" in drivers:
                out[pid] = (busy, mb)
            else:
                out[pid] = (max(busy, nv[0]), mb + nv[1])
        return out

    def _nvidia_processes(self) -> dict[int, tuple[float, float]]:
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
        return self._procs_supported or self.fdinfo.seen_any

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
        label = sysfs_name(dev)
        while not self._stop.is_set():
            s = sysfs_sample(dev, label)
            with self._lock:
                self._sample = s
            self._stop.wait(1.0)


# -- sysfs helpers (module-level so they can be tested against a fixture tree) --
_PCI_IDS = ("/usr/share/hwdata/pci.ids", "/usr/share/misc/pci.ids")
_VENDOR_SHORT = {"1002": "AMD", "8086": "Intel", "10de": "NVIDIA"}


def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def _hex_id(text: str) -> str:
    return text.strip().lower().removeprefix("0x")


def _scan_pci_ids(fh, vendor: str, device: str) -> str:
    in_vendor = False
    vendor_name = ""
    for line in fh:
        if not line.strip() or line.startswith("#"):
            continue
        if not line.startswith("\t"):
            in_vendor = line[:4].lower() == vendor
            if in_vendor:
                vendor_name = line[4:].strip()
            elif vendor_name:
                break  # past our vendor block
            continue
        if in_vendor and not line.startswith("\t\t") and line[1:5].lower() == device:
            short = _VENDOR_SHORT.get(vendor, vendor_name.split(" ")[0])
            return f"{short} {line[5:].strip()}"
    return ""


def pci_ids_lookup(vendor: str, device: str, paths: tuple[str, ...] | None = None) -> str:
    """Device name from pci.ids, e.g. ("1002", "164e") -> "AMD Raphael". Empty if unknown.

    The file is a vendor line ("1002  Advanced Micro Devices...") followed by
    tab-indented device lines ("\t164e  Raphael"); deeper indents are subsystems.
    """
    vendor, device = _hex_id(vendor), _hex_id(device)
    for path in paths if paths is not None else _PCI_IDS:
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                found = _scan_pci_ids(fh, vendor, device)
        except OSError:
            continue
        if found:
            return found
    return ""


def sysfs_name(dev: Path, pci_ids: tuple[str, ...] | None = None) -> str:
    """Human-readable card name. amdgpu rarely provides product_name, so fall
    back to the PCI id and the system's pci.ids database."""
    name = _read(dev / "product_name")
    if name:
        return name
    vendor, device = _hex_id(_read(dev / "vendor")), _hex_id(_read(dev / "device"))
    if not vendor:
        return "GPU"
    return pci_ids_lookup(vendor, device, pci_ids) or f"GPU {vendor}:{device}"


def sysfs_sample(dev: Path, label: str = "GPU") -> GpuSample:
    """One reading from a /sys/class/drm/cardN/device tree."""
    s = GpuSample(name=label)
    s.util = _f(_read(dev / "gpu_busy_percent"))
    used = _f(_read(dev / "mem_info_vram_used"))
    total = _f(_read(dev / "mem_info_vram_total"))
    s.mem_used_mb, s.mem_total_mb = used / 1048576.0, total / 1048576.0
    hwmon = next(iter((dev / "hwmon").glob("hwmon*")), None)
    if hwmon:
        s.temp_c = _f(_read(hwmon / "temp1_input")) / 1000.0
        # Discrete cards report power1_average; APUs (and some others) only
        # power1_input. Both are microwatts.
        power = _read(hwmon / "power1_average") or _read(hwmon / "power1_input")
        s.power_w = _f(power) / 1e6
        s.clock_mhz = _f(_read(hwmon / "freq1_input")) / 1e6
    return s
