"""Tests for the per-process history store (no Qt)."""
from __future__ import annotations

import unittest

from archpm.model import ProcSample
from archpm.ui.history import ProcHistory


def snap(**cpu_by_pid: float) -> list[ProcSample]:
    return [ProcSample(pid=int(pid[1:]), cpu_percent=c, gpu_sm=c / 10, mem_rss=int(c) << 20)
            for pid, c in cpu_by_pid.items()]


class Store(unittest.TestCase):
    def test_records_per_pid_and_forgets_the_gone(self):
        h = ProcHistory(length=4)
        h.update(snap(p1=10, p2=20))
        h.update(snap(p1=30))
        self.assertEqual(list(h.get(1).cpu), [10, 30])
        self.assertIsNone(h.get(2), "a process that vanished is dropped")
        self.assertEqual(len(h), 1)

    def test_bounded_length(self):
        h = ProcHistory(length=3)
        for c in (1, 2, 3, 4, 5):
            h.update(snap(p1=c))
        self.assertEqual(list(h.get(1).cpu), [3, 4, 5])
        self.assertEqual(list(h.get(1).gpu), [0.3, 0.4, 0.5])
        self.assertEqual(h.get(1).rss[-1], 5 << 20)

    def test_tree_sums_aligned_on_the_newest_sample(self):
        h = ProcHistory(length=5)
        h.update(snap(p1=10))             # child p2 does not exist yet
        h.update(snap(p1=10, p2=5))
        h.update(snap(p1=10, p2=5))
        t = h.tree([1, 2])
        self.assertEqual(list(t.cpu), [10, 15, 15])
        self.assertEqual(list(h.tree([1, 999]).cpu), [10, 10, 10], "unknown pids are ignored")
        self.assertEqual(len(h.tree([])), 0)


if __name__ == "__main__":
    unittest.main()
