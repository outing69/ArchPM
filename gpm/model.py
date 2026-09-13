"""Data types for a single sample of the system."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class GpuSample:
    name: str = ""
    util: float = 0.0            # SM utilisation in %
    mem_util: float = 0.0        # memory bus utilisation in %
    mem_used_mb: float = 0.0
    mem_total_mb: float = 0.0
    temp_c: float = 0.0
    power_w: float = 0.0
    clock_mhz: float = 0.0
    fan_pct: float = 0.0

    @property
    def mem_pct(self) -> float:
        return 100.0 * self.mem_used_mb / self.mem_total_mb if self.mem_total_mb else 0.0


@dataclass(slots=True)
class ProcSample:
    pid: int
    ppid: int = 0
    name: str = ""
    username: str = ""
    cmdline: str = ""
    cpu_percent: float = 0.0     # 0..100*ncpu, like top
    mem_rss: int = 0             # bytes
    mem_percent: float = 0.0
    num_threads: int = 0
    nice: int = 0
    status: str = ""
    io_read_bps: float = 0.0
    io_write_bps: float = 0.0
    gpu_sm: float = 0.0          # % of the GPU, -1 = unknown
    gpu_mem_mb: float = 0.0
    create_time: float = 0.0
    affinity: int = 0            # number of cores this process may run on
    owned: bool = False          # runs under our own uid

    @property
    def mem_mb(self) -> float:
        return self.mem_rss / 1048576.0


@dataclass(slots=True)
class SystemSample:
    ts: float = 0.0
    cpu_percent: float = 0.0
    per_core: list[float] = field(default_factory=list)
    freq_mhz: float = 0.0
    load: tuple[float, float, float] = (0.0, 0.0, 0.0)
    mem_used: int = 0
    mem_total: int = 0
    mem_available: int = 0
    swap_used: int = 0
    swap_total: int = 0
    cpu_temp_c: float = 0.0
    temps: dict[str, float] = field(default_factory=dict)
    net_rx_bps: float = 0.0
    net_tx_bps: float = 0.0
    disk_r_bps: float = 0.0
    disk_w_bps: float = 0.0
    proc_count: int = 0
    thread_count: int = 0
    gpu: GpuSample | None = None

    @property
    def mem_pct(self) -> float:
        return 100.0 * self.mem_used / self.mem_total if self.mem_total else 0.0


@dataclass(slots=True)
class Snapshot:
    system: SystemSample
    procs: list[ProcSample] = field(default_factory=list)
