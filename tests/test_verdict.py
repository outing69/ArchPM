"""The verdict line: is anything straining the machine, from the sample
already taken, named only when it holds; and the game card's own rule,
where the card fully used is green."""
from __future__ import annotations

import os
import tempfile
import unittest

from archpm import verdict as vd
from archpm.model import GpuSample, ProcSample, Snapshot, SystemSample


def proc(pid, name, cpu=0.0, mem=0, app="", **kw):
    return ProcSample(pid=pid, ppid=1, name=name, cpu_percent=cpu, mem_rss=mem, app_name=app,
                      owned=True, program=bool(app), cmdline=f"/usr/bin/{name}",
                      argv=(f"/usr/bin/{name}",), **kw)


def system(cpu=5.0, mem_pct=50.0, cpu_temp=50.0, gpu_temp=0.0):
    total = 16 * 2**30
    gpu = GpuSample(temp_c=gpu_temp) if gpu_temp else None
    return SystemSample(cpu_percent=cpu, mem_used=int(total * mem_pct / 100), mem_total=total,
                        cpu_temp_c=cpu_temp, gpu=gpu)


class Candidate(unittest.TestCase):
    def test_calm_when_nothing_reaches_a_threshold(self):
        v = vd.candidate(system(), [proc(10, "brave", cpu=50, app="Brave")], 16)
        self.assertEqual((v.text, v.level, v.pid), (vd.CALM, "calm", 0))

    def test_a_program_above_a_quarter_of_the_processor_is_named_and_linked(self):
        procs = [proc(10, "pycharm", cpu=300, app="PyCharm"), proc(11, "java", cpu=200,
                                                                    app="PyCharm")]
        v = vd.candidate(system(cpu=40), procs, 16)
        self.assertEqual(v.text, "PyCharm is using 31% of the processor.")
        self.assertEqual((v.level, v.pid, v.program), ("strain", 10, "PyCharm"))
        self.assertEqual(vd.candidate(system(cpu=40), procs, 32).level, "calm",
                         "the same load is only 16% of a bigger machine")

    def test_a_game_at_that_share_is_the_game_not_a_strain(self):
        game = proc(20, "game", cpu=800, app="Doom", steam_appid=1, gpu_sm=90.0)
        v = vd.candidate(system(cpu=60), [game], 16)
        self.assertEqual(v.level, "game")
        self.assertIn("that is the game", v.text)

    def test_the_whole_processor_busy_without_one_culprit(self):
        procs = [proc(i, f"w{i}", cpu=100, app=f"W{i}") for i in range(1, 16)]
        v = vd.candidate(system(cpu=94), procs, 16)
        self.assertTrue(v.text.startswith("The processor is fully busy; the biggest user is"))
        self.assertEqual(v.level, "strain")

    def test_memory_nearly_full_names_the_largest_program(self):
        procs = [proc(10, "brave", mem=6 * 2**30, app="Brave"),
                 proc(11, "brave", mem=2 * 2**30, app="Brave"),
                 proc(12, "game", cpu=900, mem=2**30, app="Game")]
        v = vd.candidate(system(mem_pct=90), procs, 16)
        self.assertEqual(v.text, "Memory is nearly full: Brave holds 8.0 GB.")
        self.assertEqual((v.level, v.pid), ("strain", 10))
        self.assertEqual(vd.candidate(system(mem_pct=84), procs, 16).level, "strain",
                         "the game at 56% of the processor is a strain instead")

    def test_hot_wins_over_everything_and_has_no_link(self):
        procs = [proc(10, "x", cpu=1600, app="X")]
        v = vd.candidate(system(cpu=100, mem_pct=95, cpu_temp=92), procs, 16)
        self.assertEqual((v.text, v.level, v.pid), ("The processor is running hot: 92°.", "hot", 0))
        v = vd.candidate(system(gpu_temp=91), [], 16)
        self.assertEqual(v.text, "The graphics card is running hot: 91°.")


class Sustain(unittest.TestCase):
    def test_a_strain_is_named_after_three_samples_and_calm_at_once(self):
        w = vd.StrainWatch()
        busy = [proc(10, "pycharm", cpu=800, app="PyCharm")]
        self.assertEqual(w.update(system(cpu=50), busy, 16).level, "calm")
        self.assertEqual(w.update(system(cpu=50), busy, 16).level, "calm")
        self.assertEqual(w.update(system(cpu=50), busy, 16).level, "strain")
        self.assertEqual(w.update(system(cpu=50), busy, 16).text,
                         "PyCharm is using 50% of the processor.")
        self.assertEqual(w.update(system(), [proc(10, "pycharm", cpu=10, app="PyCharm")], 16).level,
                         "calm")

    def test_a_spike_that_moves_between_programs_is_not_named(self):
        w = vd.StrainWatch()
        for name in ("A", "B", "A", "B"):
            v = w.update(system(cpu=50), [proc(10, name.lower(), cpu=800, app=name)], 16)
            self.assertEqual(v.level, "calm")

    def test_hot_shows_at_once(self):
        w = vd.StrainWatch()
        self.assertEqual(w.update(system(cpu_temp=95), [], 16).level, "hot")


class Game(unittest.TestCase):
    def test_the_cards_own_rule(self):
        self.assertEqual(vd.game_verdict(400, 93, 60, 70)[1], "OK")
        self.assertIn("as it should be", vd.game_verdict(400, 93, 60, 70)[0])
        self.assertEqual(vd.game_verdict(95, 30, 60, 60)[1], "WARN")
        self.assertIn("processor is the limit", vd.game_verdict(95, 30, 60, 60)[0])
        self.assertEqual(vd.game_verdict(20, 10, 60, 60)[1], "MUTED")
        self.assertEqual(vd.game_verdict(200, 70, 60, 60)[1], "TEXT")
        text, token = vd.game_verdict(400, 93, 60, 91)
        self.assertEqual(token, "CRIT")
        self.assertIn("graphics card is at 91°", text)
        self.assertEqual(vd.gpu_caption(93), "fully used")
        self.assertEqual(vd.gpu_caption(30), "mostly idle")


@unittest.skipUnless(True, "")
class OnThePage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtCore import QSettings
            from PySide6.QtWidgets import QApplication
        except ImportError:                       # pragma: no cover
            raise unittest.SkipTest("PySide6 not installed") from None
        cls.tmp = tempfile.TemporaryDirectory()
        for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
            QSettings.setPath(fmt, QSettings.Scope.UserScope, cls.tmp.name)
        cls.app = QApplication.instance() or QApplication([])
        from archpm.ui import theme
        theme.apply(cls.app, "dark")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_verdict_leads_the_page_and_root_tasks_comes_last(self):
        from PySide6.QtTest import QTest

        from archpm.ui.dashboard import Dashboard
        from archpm.ui.history import ProcHistory
        d = Dashboard(16, ProcHistory())
        d.resize(1100, 900)
        d.show()
        QTest.qWait(30)
        self.assertEqual(d.lbl_verdict.text(), vd.CALM)
        self.assertLess(d.lbl_verdict.y(), d.tiles.y(), "above the tiles")
        self.assertLess(d.lbl_verdict.y(), d.lbl_machine.y(), "and above the machine line")
        self.assertGreater(d.btn_root.y(), d.wide_cards[-1].y(), "Root tasks is last")
        self.assertEqual(d.lbl_verdict.font().pointSizeF(), float(12))
        self.assertTrue(d.lbl_verdict.font().bold())
        busy = [proc(10, "pycharm", cpu=800, app="PyCharm")]
        asked = []
        d.process_requested.connect(asked.append)
        for _ in range(3):
            d.update_view(Snapshot(system=system(cpu=50), procs=busy))
        self.assertEqual(d.lbl_verdict.text().count("PyCharm is using 50% of the processor."), 1)
        self.assertTrue(d.lbl_verdict._link, "a link when there is a row")
        d.lbl_verdict.activated.emit()
        self.assertEqual(asked, [10])
        d.update_view(Snapshot(system=system(), procs=[]))
        self.assertEqual(d.lbl_verdict.text(), vd.CALM)
        self.assertFalse(d.lbl_verdict._link, "plain when there is nothing to open")
        d.close()

    def test_the_game_card_says_its_verdict_in_its_own_colours(self):
        from archpm.ui import theme
        from archpm.ui.dashboard import GameCard
        card = GameCard(16)
        game = proc(20, "game", cpu=400, app="Doom", steam_appid=1, gpu_sm=93.0, gpu_mem_mb=2000)
        card.update_view([game], None, system(cpu=30))
        self.assertTrue(card.lbl_verdict.isVisibleTo(card))
        self.assertIn("as it should be", card.lbl_verdict.text())
        self.assertIn(theme.OK, card.lbl_verdict.styleSheet())
        self.assertIn(theme.OK, card.t_gpu._value.styleSheet())
        self.assertNotIn(theme.CRIT, card.t_gpu._value.styleSheet(), "never red for a busy card")
        self.assertEqual(card.t_gpu._sub.text(), "fully used")
        card.update_view([], None, system())
        self.assertFalse(card.lbl_verdict.isVisibleTo(card))

    def test_the_process_page_shows_the_pid(self):
        from PySide6.QtTest import QTest

        from archpm.actions import UserBackend
        from archpm.ui.procview import ProcessView
        v = ProcessView(16, UserBackend())
        v.show()
        v.set_mode("flat")
        v.search.setText("zzz")
        v.update_view(Snapshot(system=system(), procs=[proc(10, "pycharm", app="PyCharm"),
                                                        proc(11, "brave", app="Brave")]))
        QTest.qWait(20)
        self.assertTrue(v.show_pid(11))
        self.assertEqual(v.search.text(), "")
        self.assertEqual([p.pid for p in v._selected()], [11])
        self.assertFalse(v.show_pid(999))
        v.close()


if __name__ == "__main__":
    unittest.main()
