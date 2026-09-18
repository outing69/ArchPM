"""The words on the five paths a Windows user walks: no term where a plain
word carries the same meaning, one scale for one thing, and a reference on
a number the user has to judge. The Help glossary keeps its own terms."""
from __future__ import annotations

import os
import signal
import tempfile
import unittest

try:
    from PySide6.QtWidgets import QApplication
except ImportError:                       # pragma: no cover
    QApplication = None

from archpm.helptext import plural
from archpm.verdict import temp_level


class Plain(unittest.TestCase):
    def test_plurals_are_words_not_parentheses(self):
        self.assertEqual(plural(1, "process"), "1 process")
        self.assertEqual(plural(3, "process"), "3 processes")
        self.assertEqual(plural(2, "page"), "2 pages")

    @unittest.skipUnless(QApplication, "PySide6 not installed")
    def test_the_process_columns_have_no_abbreviations(self):
        from archpm.ui.proc_model import HEADERS
        for hard in ("Thr", "VRAM", "Nice", "Disk I/O"):
            self.assertNotIn(hard, HEADERS)
        for plain in ("Threads", "Video memory", "Priority", "Disk"):
            self.assertIn(plain, HEADERS)
        self.assertIn("PID", HEADERS, "the id is the thing itself; the column keeps it")

    @unittest.skipUnless(QApplication, "PySide6 not installed")
    def test_the_toasts_after_a_signal_are_sentences(self):
        from archpm.ui.procview import SIGNAL_DONE
        self.assertEqual(SIGNAL_DONE[signal.SIGTERM].format(n=plural(1, "process")),
                         "Asked 1 process to quit")
        self.assertEqual(SIGNAL_DONE[signal.SIGKILL].format(n=plural(3, "process")),
                         "Force-killed 3 processes")
        for text in SIGNAL_DONE.values():
            self.assertNotIn("SIG", text)

    def test_a_temperature_carries_its_reference(self):
        self.assertEqual(temp_level(49), ("normal", "OK"))
        self.assertEqual(temp_level(79), ("normal", "OK"))
        self.assertEqual(temp_level(80), ("warm", "WARN"))
        self.assertEqual(temp_level(90), ("hot", "CRIT"))


class OnScreen(unittest.TestCase):
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

    def test_the_game_card_uses_one_scale_and_plain_captions(self):
        from archpm.model import GpuSample, ProcSample, SystemSample
        from archpm.ui.dashboard import GameCard
        card = GameCard(16)
        game = ProcSample(pid=20, name="game", app_name="Doom", owned=True, program=True,
                          steam_appid=1, cpu_percent=300.0, gpu_sm=93.0, gpu_mem_mb=2100,
                          num_threads=42, nice=-4, cmdline="/g", argv=("/g",))
        card.update_view([game], None, SystemSample(gpu=GpuSample(mem_total_mb=12288)))
        self.assertEqual(card.t_cpu._value.text(), "19%")
        self.assertEqual(card.t_cpu._sub.text(), "of all 16 cores")
        self.assertEqual(card.t_vram._sub.text(), "of the card's 12 GB")
        self.assertEqual(card.t_mem._sub.text(), "with everything it started")
        self.assertEqual(card.t_thr._sub.text(), "across 1 process")
        self.assertEqual(card.t_cores._sub.text(), "it may use")
        self.assertIn("Priority raised", card.lbl_sub.text())
        self.assertNotIn("pid", card.lbl_name.text())
        self.assertIn("process 20", card.lbl_name.text())
        self.assertEqual(card.t_vram._title.text(), "VIDEO MEMORY")

    def test_the_overview_tiles_and_lines(self):
        from archpm.model import GpuSample, ProcSample, Snapshot, SystemSample
        from archpm.ui import theme
        from archpm.ui.dashboard import Dashboard
        from archpm.ui.history import ProcHistory
        d = Dashboard(16, ProcHistory())
        s = SystemSample(cpu_temp_c=61.0, mem_used=1, mem_total=2, swap_used=1, swap_total=2,
                         gpu=GpuSample(temp_c=84.0, fan_pct=30.0, mem_total_mb=12288))
        d.update_view(Snapshot(system=s, procs=[ProcSample(pid=1, name="x")]))
        self.assertEqual(d.t_cputemp._sub.text(), "normal")
        self.assertIn(theme.OK, d.t_cputemp._value.styleSheet(), "61° is by design, not amber")
        self.assertEqual(d.t_gputemp._sub.text(), "warm  ·  fan 30%")
        self.assertIn(theme.WARN, d.t_gputemp._value.styleSheet())
        self.assertIn("On disk (swap)", d.mem_sub.text())
        self.assertIn("cores,", d.lbl_machine.text())
        self.assertNotIn("c/", d.lbl_machine.text())
        self.assertEqual(d.t_vram._title.text(), "VIDEO MEMORY")

    def test_startup_rows_say_your_own_copy_and_process(self):
        from pathlib import Path
        from unittest import mock

        from archpm.autostart import StartupEntry
        from archpm.ui.startup import StartupView
        v = StartupView()
        v.auto = mock.Mock()
        e = StartupEntry(id="x.desktop", name="X", icon="", exec="/usr/bin/x",
                         path=Path("/u/x.desktop"), system_path=Path("/s/x.desktop"),
                         user_path=Path("/u/x.desktop"), enabled=True, for_this_desktop=True,
                         kind="System")
        v.auto.entries.return_value = [e]
        v._fill_services = lambda: None
        v.reload()
        row = {r.title.text(): r for r in v.list.rows()}["X"]
        self.assertEqual(row.suffix[1].text(), "System · your own copy")
        running = {"x.desktop": 4242}
        with mock.patch("archpm.ui.startup.running_pids", lambda entries, argvs: running):
            v._refresh_state()
        self.assertEqual(row.suffix[0].text(), "Running · process 4242")

    def test_the_process_page_words(self):
        from archpm.actions import UserBackend
        from archpm.ui.procview import ProcessView
        v = ProcessView(16, UserBackend())
        self.assertNotIn("PID", v.search.placeholderText())
        self.assertIn("process id", v.search.placeholderText())
        self.assertEqual(v.cb_norm.text(), "CPU as % of all cores")
        v.close()


if __name__ == "__main__":
    unittest.main()
