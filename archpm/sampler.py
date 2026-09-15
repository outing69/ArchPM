"""The measuring work: psutil processes, cores, memory, IO and sensors.

The sampler keeps its psutil.Process objects between ticks. That is not a
micro-optimisation but a requirement: cpu_percent() is a delta relative to the
previous call on the *same* object.
"""
from __future__ import annotations

import os
import time

import psutil

from .appinfo import AppResolver
from .gpu import GpuMonitor
from .grouping import build_groups, read_pss
from .model import ProcSample, Snapshot, SystemSample
from .net import NetSampler

# cpu_affinity() deliberately not per tick: that is one syscall per process
# (~430 of them) for a value only the affinity dialog needs, and it asks for it
# itself when opened.

_DEAD = (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess)

# Per tick. cmdline and username are fetched separately and cached: the
# command line only changes on exec (which also changes the name), and a uid's
# name never does. Together that was a quarter of every tick.
_PROC_ATTRS = [
    "pid", "ppid", "name", "memory_info", "memory_percent",
    "num_threads", "nice", "status", "create_time", "uids",
]
PSS_EVERY = 5     # ticks between two PSS reads of the same process
PSS_SLOTS = 4     # the reads are spread by pid over the first four of those ticks ...
TEMPS_EVERY = 5   # ... and the fifth reads the sensors, slow to read and slow to change
NET_EVERY_S = 5.0  # seconds between socket scans (one ss call, ~50 ms)


class Sampler:
    def __init__(self, gpu: GpuMonitor | None = None, group_memory: bool = True) -> None:
        self.ncpu = psutil.cpu_count(logical=True) or 1
        self.uid = os.getuid()
        self.gpu = gpu
        self.group_memory = group_memory     # PSS for the Grouped view; the agent has no use for it
        self._pss: dict[int, int] = {}       # pid -> bytes, refreshed every PSS_EVERY ticks
        self._procs: dict[int, psutil.Process] = {}
        self._starts: dict[int, float] = {}
        self._io: dict[int, tuple[float, float, float]] = {}  # pid -> (read, write, ts)
        self._net: tuple[float, float, float] | None = None
        self._disk: tuple[float, float, float] | None = None
        self._boot = psutil.boot_time()
        self.apps = AppResolver()
        self._tick = 0
        self._temps_cache: tuple[dict[str, float], float] = ({}, 0.0)
        self._cmdlines: dict[int, tuple[str, list[str]]] = {}   # pid -> (name, argv)
        self.net = NetSampler()
        self._net_last = None
        self._net_ts = 0.0
        self._users: dict[int, str] = {}                        # uid -> username
        self._cgroups: dict[int, tuple[str, float]] = {}        # pid -> (path, read at)
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
            self._cmdlines.pop(pid, None)
            self._cgroups.pop(pid, None)
            self._pss.pop(pid, None)
            self.apps.forget(pid)

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
            cmd = self._cmdline(pid, p, info.get("name") or "")
            gsm, gmb = gpu_procs.get(pid, (0.0, 0.0))
            n_thr = info.get("num_threads") or 0
            threads += n_thr
            name = info.get("name") or ""
            owned = bool(uids and uids.real == self.uid)
            app = self.apps.lookup(pid, name, cmd, owned)
            procs.append(ProcSample(
                pid=pid,
                ppid=info.get("ppid") or 0,
                name=name,
                username=self._username(uids.real) if uids else "",
                cmdline=" ".join(cmd),
                argv=tuple(cmd),
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
                owned=owned,
                app_name=app.name,
                icon=app.icon,
                category=app.category,
                program=app.program,
                steam_appid=app.steam_appid,
                cgroup=self._cgroup(pid, info.get("create_time") or 0.0, now),
            ))

        self._name_game_roots(procs)
        if self.group_memory:
            self._refresh_pss(procs)
        sys_sample = self._system(now, len(procs), threads)
        if now - self._net_ts >= NET_EVERY_S:
            self._net_ts = now
            self._net_last = self.net.sample({p.pid: p.display_name for p in procs})
        return Snapshot(system=sys_sample, procs=procs, net=self._net_last)

    def _name_game_roots(self, procs: list[ProcSample]) -> None:
        """Steam's "reaper" is the top of every game's tree. Give that root the
        game's name too, so a collapsed Steam shows "DOOM: The Dark Ages" as
        its child rather than "reaper". The real name stays in the tooltip."""
        appid_of = {p.pid: p.steam_appid for p in procs if p.steam_appid}
        for p in procs:
            if p.steam_appid and not p.app_name and appid_of.get(p.ppid) != p.steam_appid:
                p.app_name = self.apps.steam.name(p.steam_appid)

    def _cmdline(self, pid: int, p: psutil.Process, name: str) -> list[str]:
        cached = self._cmdlines.get(pid)
        if cached is not None and cached[0] == name:
            return cached[1]
        try:
            cmd = p.cmdline()
        except _DEAD:
            cmd = []
        self._cmdlines[pid] = (name, cmd)
        return cmd

    def _refresh_pss(self, procs: list[ProcSample]) -> None:
        """Group memory that counts shared pages once. Only processes that
        share a group are read, each once every PSS_EVERY ticks, spread by
        pid over PSS_SLOTS of those ticks; the remaining tick reads the
        sensors instead, so no tick carries both. Reading them all on one
        tick made that cycle three times as long (measured 130 to 168 ms
        against 47 ms), and spreading whole groups still put a browser's
        thirty processes on one tick. A newcomer counts its RSS until its
        first read, at most ten seconds; a group's figure mixes reads up to
        eight seconds apart, which is fine for a memory total."""
        slot = self._tick % PSS_EVERY
        if slot >= PSS_SLOTS:
            return self._apply_pss(procs)
        for members in build_groups(procs).values():
            if len(members) >= 2:
                for p in members:
                    if p.pid % PSS_SLOTS == slot:
                        self._pss[p.pid] = read_pss(p.pid)
        self._apply_pss(procs)

    def _apply_pss(self, procs: list[ProcSample]) -> None:
        for p in procs:
            p.mem_pss = self._pss.get(p.pid, 0)

    def _cgroup(self, pid: int, create_time: float, now: float) -> str:
        """The process's cgroup path. Read once, and again every 30 s while the
        process is young: a browser moves itself into its own scope right
        after starting. About 10 us per read."""
        cached = self._cgroups.get(pid)
        if cached is not None and (now - create_time > 300 or now - cached[1] < 30):
            return cached[0]
        try:
            with open(f"/proc/{pid}/cgroup") as fh:
                path = fh.read().strip().rpartition(":")[2]
        except OSError:
            path = cached[0] if cached else ""
        self._cgroups[pid] = (path, now)
        return path

    def _username(self, uid: int) -> str:
        user = self._users.get(uid)
        if user is None:
            try:
                import pwd
                user = pwd.getpwuid(uid).pw_name
            except (KeyError, ImportError):
                user = str(uid)
            self._users[uid] = user
        return user

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
        self._tick += 1      # the tick just finished was the PSS round's last slot when this is 0
        if self._tick % TEMPS_EVERY == 0 or not self._temps_cache[0]:
            self._temps_cache = self._temps()
        s.temps, s.cpu_temp_c = self._temps_cache
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
