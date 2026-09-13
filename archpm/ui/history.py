"""Per-process history of the last few minutes, for every process at once.

You click a process *after* it misbehaved, so the history has to exist before
you ask for it. Three numbers per process per tick (CPU %, GPU %, resident
memory) for ~450 processes over 180 ticks is a few hundred kilobytes: cheap
enough to keep for everything. No Qt in here.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from ..model import ProcSample


@dataclass
class Track:
    cpu: deque = field(default_factory=lambda: deque(maxlen=180))
    gpu: deque = field(default_factory=lambda: deque(maxlen=180))
    rss: deque = field(default_factory=lambda: deque(maxlen=180))

    def __len__(self) -> int:
        return len(self.cpu)


class ProcHistory:
    def __init__(self, length: int = 180) -> None:
        self.length = length
        self._tracks: dict[int, Track] = {}

    def update(self, procs: list[ProcSample]) -> None:
        seen: set[int] = set()
        for p in procs:
            seen.add(p.pid)
            t = self._tracks.get(p.pid)
            if t is None:
                t = Track(deque(maxlen=self.length), deque(maxlen=self.length),
                          deque(maxlen=self.length))
                self._tracks[p.pid] = t
            t.cpu.append(p.cpu_percent)
            t.gpu.append(p.gpu_sm)
            t.rss.append(p.mem_rss)
        for pid in [pid for pid in self._tracks if pid not in seen]:
            del self._tracks[pid]

    def get(self, pid: int) -> Track | None:
        return self._tracks.get(pid)

    def tree(self, pids: list[int]) -> Track:
        """Summed track over several processes (a program and its children).
        Tracks of different lengths are aligned on their newest sample."""
        tracks = [t for t in (self._tracks.get(pid) for pid in pids) if t is not None]
        out = Track(deque(maxlen=self.length), deque(maxlen=self.length),
                    deque(maxlen=self.length))
        if not tracks:
            return out
        n = max(len(t) for t in tracks)
        for i in range(n):
            back = n - i  # samples from the end
            cpu = gpu = rss = 0.0
            for t in tracks:
                if len(t) >= back:
                    cpu += t.cpu[-back]
                    gpu += t.gpu[-back]
                    rss += t.rss[-back]
            out.cpu.append(cpu)
            out.gpu.append(gpu)
            out.rss.append(rss)
        return out

    def __len__(self) -> int:
        return len(self._tracks)
