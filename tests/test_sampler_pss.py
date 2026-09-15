"""PSS for grouped rows: only for processes that share a group, each process
once every fifth sample, spread by pid over four of the five ticks so no
single cycle carries all the reads, nor a whole large group; the fifth tick
reads the sensors instead. Runs the real sampler for ten ticks."""
from __future__ import annotations

import unittest

from archpm import sampler as sampler_mod
from archpm.grouping import build_groups
from archpm.sampler import PSS_EVERY, PSS_SLOTS, Sampler


class Cadence(unittest.TestCase):
    def test_each_group_is_read_once_per_five_ticks_and_the_reads_are_spread(self):
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
            for _ in range(2 * PSS_EVERY):
                reads.append([])
                snaps.append(s.sample())
        finally:
            sampler_mod.read_pss = original
        grouped_every_tick = set.intersection(*[
            {p.pid for g in build_groups(snap.procs).values() if len(g) >= 2 for p in g}
            for snap in snaps])
        self.assertTrue(grouped_every_tick,
                        "this machine has at least one steady multi-process application")
        for r in reads:
            self.assertTrue(set(r) <= {p.pid for snap in snaps for p in snap.procs},
                            "only members of groups")
        # over any five consecutive ticks every steady grouped pid is read exactly once
        for start in (0, PSS_EVERY):
            window = reads[start:start + PSS_EVERY]
            for pid in grouped_every_tick:
                self.assertEqual(sum(r.count(pid) for r in window), 1, pid)
        # and they are spread by pid, so no tick carries them all, nor a whole group
        biggest = max(len(r) for r in reads)
        self.assertLess(biggest, len(grouped_every_tick), "the reads are spread over the ticks")
        for i, r in enumerate(reads):
            slot = i % PSS_EVERY
            if slot >= PSS_SLOTS:
                self.assertEqual(r, [], "the fifth tick is the sensors' tick, no PSS reads")
            else:
                self.assertTrue(all(pid % PSS_SLOTS == slot for pid in r))
        for snap in snaps[PSS_EVERY:]:
            self.assertTrue(all(p.mem_pss == 4096
                                for p in snap.procs if p.pid in grouped_every_tick))

    def test_the_agent_can_switch_it_off(self):
        s = Sampler(None, group_memory=False)
        s.prime()
        snap = s.sample()
        self.assertTrue(all(p.mem_pss == 0 for p in snap.procs))


if __name__ == "__main__":
    unittest.main()
