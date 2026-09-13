"""The measuring work: psutil processes, cores, memory, IO and sensors.

The sampler keeps its psutil.Process objects between ticks. That is not a
micro-optimisation but a requirement: cpu_percent() is a delta relative to the
previous call on the *same* object.
"""
from __future__ import annotations

import os
import time

import psutil

from .gpu import GpuMonitor
from .model import ProcSample, Snapshot, SystemSample

# cpu_affinity() deliberately not per tick: that is one syscall per process
# (~430 of them) for a value only the affinity dialog needs, and it asks for it
# itself when opened.

_DEAD = (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess)

_PROC_ATTRS = [
    "pid", "ppid", "name", "username", "cmdline", "memory_info", "memory_percent",
    "num_threads", "nice", "status", "create_time", "uids",
]


class Sampler:
    def __init__(self, gpu: GpuMonitor | None = None) -> None:
        self.ncpu = psutil.cpu_count(logical=True) or 1
        self.uid = os.getuid()
        self.gpu = gpu
        self._procs: dict[int, psutil.Process] = {}
        self._starts: dict[int, float] = {}
        self._io: dict[int, tuple[float, float, float]] = {}  # pid -> (read, write, ts)
        self._net: tuple[float, float, float] | None = None
        self._disk: tuple[float, float, float] | None = None
        self._boot = psutil.boot_time()
        psutil.cpu_percent(percpu=True)  # baseline for the first tick

    # ------------------------------------------------------------------
    def prime(self) -> None:
        """First pass so the very next sample already has real CPU%."""
        self._refresh_cache()
        for p in self._procs.values():
            try:
                p.cpu_percent()
            except _DEAD:
                pass

    def _refresh_cache(self) -> None:
        alive = set()
        for pid in psutil.pids():
            alive.add(pid)
            known = self._procs.get(pid)
            if known is not None:
                continue
            try:
                p = psutil.Process(pid)
                self._procs[pid] = p
                self._starts[pid] = p.create_time()
                p.cpu_percent()
            except _DEAD:
                continue
        for pid in self._procs.keys() - alive:
            del self._procs[pid]
            self._starts.pop(pid, None)
            self._io.pop(pid, None)

    # ------------------------------------------------------------------
    def sample(self) -> Snapshot:
        now = time.time()
        self._refresh_cache()
        gpu_procs = self.gpu.processes() if self.gpu else {}

        procs: list[ProcSample] = []
        threads = 0
        for pid, p in list(self._procs.items()):
            try:
                with p.oneshot():
                    info = p.as_dict(_PROC_ATTRS)
                    cpu = p.cpu_percent()
                    io = self._io_rates(pid, p, now)
            except _DEAD:
                self._procs.pop(pid, None)
                continue

            mem = info.get("memory_info")
            uids = info.get("uids")
            cmd = info.get("cmdline") or []
            gsm, gmb = gpu_procs.get(pid, (0.0, 0.0))
            n_thr = info.get("num_threads") or 0
            threads += n_thr
            procs.append(ProcSample(
                pid=pid,
                ppid=info.get("ppid") or 0,
                name=info.get("name") or "",
                username=info.get("username") or "",
                cmdline=" ".join(cmd),
                cpu_percent=cpu,
                mem_rss=getattr(mem, "rss", 0),
                mem_percent=info.get("memory_percent") or 0.0,
                num_threads=n_thr,
                nice=info.get("nice") or 0,
                status=info.get("status") or "",
                io_read_bps=io[0],
                io_write_bps=io[1],
                gpu_sm=gsm,
                gpu_mem_mb=gmb,
                create_time=info.get("create_time") or 0.0,
                owned=bool(uids and uids.real == self.uid),
            ))

        sys_sample = self._system(now, len(procs), threads)
        return Snapshot(system=sys_sample, procs=procs)

    # ------------------------------------------------------------------
    def _io_rates(self, pid: int, p: psutil.Process, now: float) -> tuple[float, float]:
        try:
            c = p.io_counters()
        except (psutil.AccessDenied, NotImplementedError, AttributeError):
            return 0.0, 0.0
        prev = self._io.get(pid)
        self._io[pid] = (c.read_bytes, c.write_bytes, now)
        if prev is None:
            return 0.0, 0.0
        dt = now - prev[2]
        if dt <= 0:
            return 0.0, 0.0
        return max(0.0, (c.read_bytes - prev[0]) / dt), max(0.0, (c.write_bytes - prev[1]) / dt)

    def _system(self, now: float, nproc: int, nthread: int) -> SystemSample:
        per_core = psutil.cpu_percent(percpu=True)
        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()
        s = SystemSample(
            ts=now,
            cpu_percent=sum(per_core) / len(per_core) if per_core else 0.0,
            per_core=per_core,
            load=os.getloadavg(),
            mem_used=vm.total - vm.available,
            mem_total=vm.total,
            mem_available=vm.available,
            swap_used=sw.used,
            swap_total=sw.total,
            proc_count=nproc,
            thread_count=nthread,
            gpu=self.gpu.sample() if self.gpu else None,
        )
        try:
            f = psutil.cpu_freq()
            s.freq_mhz = f.current if f else 0.0
        except (OSError, AttributeError):
            pass
        s.temps, s.cpu_temp_c = self._temps()
        s.net_rx_bps, s.net_tx_bps = self._net_rates(now)
        s.disk_r_bps, s.disk_w_bps = self._disk_rates(now)
        return s

    @staticmethod
    def _temps() -> tuple[dict[str, float], float]:
        out: dict[str, float] = {}
        cpu = 0.0
        try:
            raw = psutil.sensors_temperatures()
        except (AttributeError, OSError):
            return out, cpu
        for chip, entries in raw.items():
            for e in entries:
                label = f"{chip}/{e.label}" if e.label else chip
                out[label] = e.current
                # Ryzen: k10temp Tctl is the sensor the boost logic steers on
                if not cpu and (e.label in ("Tctl", "Tdie", "Package id 0") or chip == "k10temp"):
                    cpu = e.current
        if not cpu and out:
            cpu = next(iter(out.values()))
        return out, cpu

    def _net_rates(self, now: float) -> tuple[float, float]:
        c = psutil.net_io_counters()
        prev, self._net = self._net, (c.bytes_recv, c.bytes_sent, now)
        return _rate(prev, c.bytes_recv, c.bytes_sent, now)

    def _disk_rates(self, now: float) -> tuple[float, float]:
        c = psutil.disk_io_counters()
        if c is None:
            return 0.0, 0.0
        prev, self._disk = self._disk, (c.read_bytes, c.write_bytes, now)
        return _rate(prev, c.read_bytes, c.write_bytes, now)


def _rate(prev: tuple[float, float, float] | None, a: float, b: float,
          now: float) -> tuple[float, float]:
    if prev is None:
        return 0.0, 0.0
    dt = now - prev[2]
    if dt <= 0:
        return 0.0, 0.0
    return max(0.0, (a - prev[0]) / dt), max(0.0, (b - prev[1]) / dt)
