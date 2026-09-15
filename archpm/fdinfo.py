"""Per-process GPU usage from DRM fdinfo, for every driver that exports it.

Every open DRM file descriptor of a process has a /proc/<pid>/fdinfo/<fd>
with "drm-*" lines, as specified in the kernel's
Documentation/gpu/drm-usage-stats.rst. No root and no extra package needed.

What the fields look like differs per driver, so the parser keys off what is
present rather than a fixed list:

- drm-engine-<name>: <ns> ns          busy time; amdgpu (gfx, compute, enc,
                                       dec, dma), i915 (render, copy, video)
- drm-cycles-<name> / drm-total-cycles-<name>   xe reports cycles instead
- drm-engine-capacity-<name>: <n>     a group of n identical engines
- drm-resident-<region>: <n> [KiB|MiB]  memory in use per region; vram* and
                                       local* are device memory. amdgpu also
                                       prints the older alias drm-memory-<region>.
- drm-client-id (+ drm-pdev)          one client can appear on several fds;
                                       count it once.

Utilisation needs two scans: busy time is a counter, so the share is the
delta divided by the wall time between scans. The first scan yields 0%.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

DRM_PREFIX = "/dev/dri/"
_UNITS = {"": 1.0, "B": 1.0, "KiB": 1024.0, "MiB": 1024.0 ** 2, "GiB": 1024.0 ** 3}
_MB = 1024.0 ** 2


def parse_fdinfo(text: str) -> dict[str, str]:
    """The drm-* lines as key -> raw value ("12 KiB", "500727657 ns", "amdgpu")."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        if not line.startswith("drm-"):
            continue
        key, sep, value = line.partition(":")
        if sep:
            out[key.strip()] = value.strip()
    return out


def parse_size(value: str) -> float:
    """"12 KiB" -> bytes. Bytes when no unit is given, as the spec says."""
    parts = value.split()
    if not parts:
        return 0.0
    try:
        n = float(parts[0])
    except ValueError:
        return 0.0
    return n * _UNITS.get(parts[1] if len(parts) > 1 else "", 0.0)


def parse_count(value: str) -> int:
    """"500727657 ns" or "1234" -> int."""
    try:
        return int(value.split(maxsplit=1)[0])
    except (ValueError, IndexError):
        return 0


@dataclass
class Client:
    driver: str
    engines_ns: dict[str, int] = field(default_factory=dict)      # name -> busy ns
    cycles: dict[str, tuple[int, int]] = field(default_factory=dict)  # name -> (busy, total)
    capacity: dict[str, int] = field(default_factory=dict)
    device_bytes: float = 0.0


def client_from_fields(fields: dict[str, str]) -> Client:
    c = Client(driver=fields.get("drm-driver", ""))
    regions: dict[str, float] = {}
    for key, value in fields.items():
        if key.startswith("drm-engine-capacity-"):
            c.capacity[key[len("drm-engine-capacity-"):]] = parse_count(value)
        elif key.startswith("drm-engine-"):
            c.engines_ns[key[len("drm-engine-"):]] = parse_count(value)
        elif key.startswith("drm-total-cycles-"):
            name = key[len("drm-total-cycles-"):]
            busy, _ = c.cycles.get(name, (0, 0))
            c.cycles[name] = (busy, parse_count(value))
        elif key.startswith("drm-cycles-"):
            name = key[len("drm-cycles-"):]
            _, total = c.cycles.get(name, (0, 0))
            c.cycles[name] = (parse_count(value), total)
        elif key.startswith(("drm-resident-", "drm-memory-", "drm-total-")):
            prefix = key.split("-", 2)[1]
            region = key[len("drm-") + len(prefix) + 1:]
            if region.startswith(("vram", "local")):
                # resident is the truth; drm-memory- is its deprecated alias;
                # total (requested) only when nothing better is printed
                rank = {"resident": 3, "memory": 2, "total": 1}[prefix]
                cur = regions.get(region)
                if cur is None or rank > cur[0]:
                    regions[region] = (rank, parse_size(value))
    c.device_bytes = sum(size for _, size in regions.values())
    return c


def read_clients(pid: int, proc_root: str = "/proc") -> dict[tuple[str, str], Client]:
    """The DRM clients of one process, one entry per (device, client id).

    Only fds that point into /dev/dri are read; a missing process, a
    permission problem or an fd closed under us simply yields nothing.
    """
    out: dict[tuple[str, str], Client] = {}
    fd_dir = f"{proc_root}/{pid}/fd"
    try:
        fds = os.listdir(fd_dir)
    except OSError:
        return out
    for fd in fds:
        try:
            if not os.readlink(f"{fd_dir}/{fd}").startswith(DRM_PREFIX):
                continue
            with open(f"{proc_root}/{pid}/fdinfo/{fd}", encoding="ascii", errors="replace") as fh:
                fields = parse_fdinfo(fh.read())
        except OSError:
            continue
        if "drm-driver" not in fields:
            continue
        key = (fields.get("drm-pdev", ""), fields.get("drm-client-id", fd))
        if key not in out:
            out[key] = client_from_fields(fields)
    return out


class DrmFdinfo:
    """Scans every process each call and turns counters into shares.

    `processes()` returns pid -> (busy %, device memory MB, drivers seen).
    The busy share is the busiest engine of the busiest client, so a game at
    90% gfx reads 90 and not "90 + 5 + 3". Memory is summed over clients.
    """

    def __init__(self, proc_root: str = "/proc", clock=time.monotonic) -> None:
        self.proc_root = proc_root
        self.clock = clock
        self._prev: dict[tuple[int, tuple[str, str]], tuple[float, Client]] = {}
        self.seen_any = False

    def _pids(self) -> list[int]:
        try:
            return [int(n) for n in os.listdir(self.proc_root) if n.isdigit()]
        except OSError:
            return []

    def _share(self, prev: Client, prev_ts: float, cur: Client, now: float) -> float:
        wall_ns = (now - prev_ts) * 1e9
        best = 0.0
        if wall_ns > 0:
            for name, busy in cur.engines_ns.items():
                delta = busy - prev.engines_ns.get(name, busy)
                cap = max(cur.capacity.get(name, 1), 1)
                best = max(best, delta / wall_ns * 100.0 / cap)
        for name, (busy, total) in cur.cycles.items():
            pb, pt = prev.cycles.get(name, (busy, total))
            if total - pt > 0:
                best = max(best, (busy - pb) / (total - pt) * 100.0)
        return min(max(best, 0.0), 100.0)

    def processes(self) -> dict[int, tuple[float, float, frozenset[str]]]:
        now = self.clock()
        out: dict[int, tuple[float, float, frozenset[str]]] = {}
        alive: set[tuple[int, tuple[str, str]]] = set()
        for pid in self._pids():
            clients = read_clients(pid, self.proc_root)
            if not clients:
                continue
            self.seen_any = True
            busy, mem, drivers = 0.0, 0.0, set()
            for key, client in clients.items():
                state = (pid, key)
                alive.add(state)
                prev = self._prev.get(state)
                if prev is not None:
                    busy = max(busy, self._share(prev[1], prev[0], client, now))
                self._prev[state] = (now, client)
                mem += client.device_bytes
                if client.driver:
                    drivers.add(client.driver)
            out[pid] = (busy, mem / _MB, frozenset(drivers))
        for state in list(self._prev):
            if state not in alive:
                del self._prev[state]
        return out
