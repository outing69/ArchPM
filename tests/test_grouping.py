"""Grouping processes into applications: the key chain and the group row's numbers."""
from __future__ import annotations

import unittest

from archpm import grouping
from archpm.model import ProcSample

SLICE = "/user.slice/user-1000.slice/user@1000.service/app.slice/"


def proc(pid, name, ppid=1, cgroup="", argv=(), **kw):
    kw.setdefault("owned", True)
    kw.setdefault("username", "alex")
    return ProcSample(pid=pid, ppid=ppid, name=name, cgroup=cgroup, argv=tuple(argv),
                      cmdline=" ".join(argv) or name, **kw)


class Keys(unittest.TestCase):
    def test_app_unit_wins_even_when_nested(self):
        self.assertEqual(grouping.unit_of(SLICE + "app-org.kde.konsole-5694.scope/main.scope"),
                         "app-org.kde.konsole-5694.scope")
        self.assertEqual(grouping.unit_of(SLICE + "app-steam@ecab.service"),
                         "app-steam@ecab.service")

    def test_plain_service_is_a_unit_too(self):
        path = ("/user.slice/user-1000.slice/user@1000.service/session.slice/"
                "plasma-kwin_wayland.service")
        self.assertEqual(grouping.unit_of(path), "plasma-kwin_wayland.service")
        self.assertEqual(grouping.unit_of("/system.slice/sshd.service"), "sshd.service")

    def test_slices_without_a_unit_give_nothing(self):
        for path in ("/", "/init.scope", "/user.slice/user-1000.slice", ""):
            self.assertEqual(grouping.unit_of(path), "", path)

    def test_the_chain_cgroup_then_exe_then_name(self):
        self.assertEqual(grouping.group_key(proc(1, "steam", cgroup=SLICE + "app-steam@1.service",
                                                 argv=["/usr/bin/steam"])),
                         ("cgroup:app-steam@1.service", "cgroup"))
        self.assertEqual(grouping.group_key(proc(2, "brave", cgroup="/init.scope",
                                                 argv=["/opt/brave-bin/brave", "--x"])),
                         ("exe:/opt/brave-bin/brave", "exe"))
        self.assertEqual(grouping.group_key(proc(3, "kthreadd")), ("name:kthreadd", "name"))

    def test_a_steam_game_is_its_own_application(self):
        game = proc(9, "game.exe", cgroup=SLICE + "app-steam@1.service", steam_appid=440)
        self.assertEqual(grouping.group_key(game), ("steam:440", "steam"))


class Merge(unittest.TestCase):
    """A browser registers its main process in a scope of its own; its
    helpers stay in the launch service. Same executable, parent in the other
    group: fold."""

    def brave(self):
        exe = ["/opt/brave-bin/brave"]
        scope = SLICE + "app-org.chromium.Chromium-4582.scope"
        unit = SLICE + "app-brave@1f72.service"
        return [
            proc(4582, "brave", ppid=1014, cgroup=scope, argv=exe, program=True, app_name="Brave"),
            proc(4600, "brave", ppid=4582, cgroup=scope, argv=exe),
            proc(4597, "brave", ppid=4582, cgroup=unit, argv=exe + ["--type=zygote"]),
            proc(4598, "brave", ppid=4582, cgroup=unit, argv=exe + ["--type=utility"]),
            proc(4700, "brave", ppid=4597, cgroup=unit, argv=exe + ["--type=renderer"]),
        ]

    def test_brave_becomes_one_group_led_by_its_main_process(self):
        groups = grouping.build_groups(self.brave())
        self.assertEqual(list(groups), ["cgroup:app-org.chromium.Chromium-4582.scope"])
        members = groups["cgroup:app-org.chromium.Chromium-4582.scope"]
        self.assertEqual(len(members), 5)
        self.assertEqual(grouping.main_process(members).pid, 4582)

    def test_a_different_executable_is_not_folded(self):
        procs = self.brave() + [
            proc(9000, "steam", ppid=1014, cgroup=SLICE + "app-steam@2.service",
                 argv=["/usr/bin/steam"]),
            proc(9001, "game.sh", ppid=9000, cgroup=SLICE + "app-game@3.service",
                 argv=["/bin/sh", "game.sh"]),
        ]
        groups = grouping.build_groups(procs)
        self.assertIn("cgroup:app-steam@2.service", groups)
        self.assertIn("cgroup:app-game@3.service", groups, "different exe, stays apart")

    def test_folding_follows_a_chain(self):
        exe = ["/usr/bin/app"]
        procs = [
            proc(1, "app", ppid=0, cgroup=SLICE + "app-a.scope", argv=exe),
            proc(2, "app", ppid=1, cgroup=SLICE + "app-b.scope", argv=exe),
            proc(3, "app", ppid=2, cgroup=SLICE + "app-c.scope", argv=exe),
        ]
        self.assertEqual(list(grouping.build_groups(procs)), ["cgroup:app-a.scope"])

    def test_read_pss_parses_kib_and_is_zero_when_unreadable(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            Path(d, "7").mkdir()
            Path(d, "7", "smaps_rollup").write_text(
                "00400000-7fff Pss_Rollup\nRss:  1000 kB\nPss:   640 kB\nPss_Anon: 1 kB\n")
            self.assertEqual(grouping.read_pss(7, d), 640 * 1024)
            self.assertEqual(grouping.read_pss(8, d), 0)


class Summary(unittest.TestCase):
    def members(self):
        return [
            proc(100, "brave", ppid=1, cgroup="x", argv=["/opt/brave/brave"], cpu_percent=5.0,
                 mem_rss=300, num_threads=30, gpu_sm=2.0, gpu_mem_mb=50, io_read_bps=10,
                 app_name="Brave Web Browser", icon="brave", category="Browser", program=True,
                 create_time=1000.0),
            proc(101, "brave", ppid=100, cgroup="x", argv=["/opt/brave/brave", "--type=zygote"],
                 cpu_percent=1.0, mem_rss=100, num_threads=5, create_time=1001.0),
            proc(102, "brave", ppid=101, cgroup="x", argv=["/opt/brave/brave", "--type=renderer"],
                 cpu_percent=20.0, mem_rss=600, num_threads=15, gpu_sm=3.0, gpu_mem_mb=25,
                 io_write_bps=5, create_time=1002.0),
        ]

    def test_sums_and_count(self):
        g = grouping.summarize(-1, "cgroup:x", self.members())
        self.assertEqual((g.pid, g.members, g.mem_approx), (-1, 3, True))
        self.assertEqual(g.cpu_percent, 26.0)
        self.assertEqual(g.mem_rss, 1000)
        self.assertEqual(g.num_threads, 50)
        self.assertEqual((g.gpu_sm, g.gpu_mem_mb), (5.0, 75))
        self.assertEqual(g.io_read_bps + g.io_write_bps, 15)
        self.assertEqual(g.create_time, 1000.0)

    def test_memory_prefers_pss_and_flags_members_without_it(self):
        m = self.members()
        m[0].mem_pss, m[1].mem_pss, m[2].mem_pss = 150, 40, 300
        g = grouping.summarize(-1, "k", m)
        self.assertEqual((g.mem_rss, g.mem_approx), (490, False))
        m[2].mem_pss = 0
        g = grouping.summarize(-1, "k", m)
        self.assertEqual((g.mem_rss, g.mem_approx), (150 + 40 + 600, True))

    def test_the_root_program_names_the_group(self):
        g = grouping.summarize(-1, "cgroup:x", self.members())
        self.assertEqual((g.name, g.app_name, g.icon, g.category),
                         ("brave", "Brave Web Browser", "brave", "Browser"))
        self.assertTrue(g.program)
        self.assertEqual(g.cmdline, "/opt/brave/brave")

    def test_a_helper_without_a_name_borrows_the_group_name(self):
        m = self.members()
        m[0].app_name = ""
        m[2].app_name = "Brave Web Browser"
        self.assertEqual(grouping.summarize(-1, "k", m).app_name, "Brave Web Browser")

    def test_owned_only_when_every_member_is(self):
        m = self.members()
        m[1].owned = False
        self.assertFalse(grouping.summarize(-1, "k", m).owned)


if __name__ == "__main__":
    unittest.main()
