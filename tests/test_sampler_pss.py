"""PSS for grouped rows: read every fifth sample, only for processes that
share a group, and reused in between. Runs the real sampler for six ticks."""
from __future__ import annotations

import unittest

from archpm import sampler as sampler_mod
from archpm.grouping import build_groups
from archpm.sampler import PSS_EVERY, Sampler


class Cadence(unittest.TestCase):
    def test_reads_on_the_first_and_sixth_sample_only_for_grouped_processes(self):
        reads: list[list[int]] = []
        original = sampler_mod.read_pss

        def fake(pid, proc_root="/proc"):
            reads[-1].append(pid)
            return 4096
        sampler_mod.read_pss = fake
        try:
            s = Sampler(None)
            s.prime()
            snaps = []
            for _ in range(PSS_EVERY + 1):
                reads.append([])
                snaps.append(s.sample())
        finally:
            sampler_mod.read_pss = original
        ticks_with_reads = [i for i, r in enumerate(reads) if r]
        self.assertEqual(ticks_with_reads, [0, PSS_EVERY])
        grouped = {p.pid for g in build_groups(snaps[0].procs).values() if len(g) >= 2 for p in g}
        self.assertTrue(set(reads[0]) <= grouped, "only members of multi-process groups")
        self.assertTrue(reads[0], "this machine has at least one multi-process application")
        # the value is carried into every sample in between
        for snap in snaps[1:PSS_EVERY]:
            measured = [p for p in snap.procs if p.mem_pss]
            self.assertTrue(measured)
            self.assertTrue(all(p.mem_pss == 4096 for p in measured))

    def test_the_agent_can_switch_it_off(self):
        s = Sampler(None, group_memory=False)
        s.prime()
        snap = s.sample()
        self.assertTrue(all(p.mem_pss == 0 for p in snap.procs))


if __name__ == "__main__":
    unittest.main()
