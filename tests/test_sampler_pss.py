"""PSS for grouped rows: only for processes that share a group, each process
once every fifth sample, spread by pid over four of the five ticks so no
single cycle carries all the reads, nor a whole large group; the fifth tick
reads the sensors instead. Runs the real sampler for ten ticks.

The group it needs, it builds: a few sleep children of its own, which share
an exe (and a cgroup unit) and so form a group. Nothing here depends on what
else happens to be running, so it passes in a clean build chroot too."""
from __future__ import annotations

import shutil
import subprocess
import unittest

from archpm import sampler as sampler_mod
from archpm.grouping import build_groups
from archpm.sampler import PSS_EVERY, PSS_SLOTS, Sampler

SLEEP = shutil.which("sleep") or "/usr/bin/sleep"
MAX_CHILDREN = 16


class Forgetting(unittest.TestCase):
    """A process that dies between the pid scan and its read is dropped
    with every per-pid cache, the way one that dies before the scan is;
    through 0.2.53 only the process object went, and a reused pid inherited
    the old IO counters, PSS, command line and cgroup."""

    def test_a_process_gone_mid_tick_leaves_no_cache_behind(self):
        import psutil

        class Dead:
            def oneshot(self):
                raise psutil.NoSuchProcess(4194000)

        s = Sampler(None, group_memory=False)
        s._refresh_cache()
        pid = 4194000
        s._procs[pid] = Dead()
        s._io[pid] = (1, 2, 0.0)
        s._starts[pid] = 1.0
        s._cmdlines[pid] = ("old", ["/usr/bin/old"])
        s._cgroups[pid] = ("/old", 0.0)
        s._pss[pid] = 5
        s.apps._cache[pid] = ("old", None)
        s.sample()
        for name in ("_procs", "_io", "_starts", "_cmdlines", "_cgroups", "_pss"):
            with self.subTest(cache=name):
                self.assertNotIn(pid, getattr(s, name))
        self.assertNotIn(pid, s.apps._cache)


class Cadence(unittest.TestCase):
    def setUp(self):
        # Enough children to sit in at least two of the pid slots, so their
        # reads cannot all land on one tick; pids come out nearly consecutive,
        # so a handful is enough, and 16 is the cap in case they do not.
        self.children: list[subprocess.Popen] = []
        while len(self.children) < MAX_CHILDREN:
            self.children.append(subprocess.Popen([SLEEP, "300"]))
            slots = {c.pid % PSS_SLOTS for c in self.children}
            if len(self.children) >= 3 and len(slots) >= 2:
                break
        self.pids = {c.pid for c in self.children}

    def tearDown(self):
        for c in self.children:
            c.kill()
        for c in self.children:
            c.wait()

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

        # our children form one group in every sample
        for snap in snaps:
            seen = {p.pid for p in snap.procs}
            self.assertTrue(self.pids <= seen, "every child is sampled")
            grouped = {p.pid for g in build_groups(snap.procs).values() if len(g) >= 2 for p in g}
            self.assertTrue(self.pids <= grouped, "the children share a group")
        all_pids = {p.pid for snap in snaps for p in snap.procs}
        for r in reads:
            self.assertTrue(set(r) <= all_pids, "only sampled processes are read")
        # over any five consecutive ticks every child is read exactly once
        for start in (0, PSS_EVERY):
            window = reads[start:start + PSS_EVERY]
            for pid in self.pids:
                self.assertEqual(sum(r.count(pid) for r in window), 1, pid)
        # and the reads are spread by pid: no tick carries all the children,
        # the fifth tick carries none, and every tick carries only its slot
        biggest = max(sum(1 for pid in r if pid in self.pids) for r in reads)
        self.assertLess(biggest, len(self.pids), "the reads are spread over the ticks")
        for i, r in enumerate(reads):
            slot = i % PSS_EVERY
            if slot >= PSS_SLOTS:
                self.assertEqual(r, [], "the fifth tick is the sensors' tick, no PSS reads")
            else:
                self.assertTrue(all(pid % PSS_SLOTS == slot for pid in r))
        for snap in snaps[PSS_EVERY:]:
            self.assertTrue(all(p.mem_pss == 4096 for p in snap.procs if p.pid in self.pids))

    def test_the_agent_can_switch_it_off(self):
        s = Sampler(None, group_memory=False)
        s.prime()
        snap = s.sample()
        self.assertTrue(all(p.mem_pss == 0 for p in snap.procs))


if __name__ == "__main__":
    unittest.main()
