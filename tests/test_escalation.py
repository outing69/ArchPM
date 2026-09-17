"""Every irreversible action asks first and says the one sentence; after a
Terminate the process is watched, and when it stays the toast offers one
button to force it. Nothing is forced by itself. Offscreen."""
from __future__ import annotations

import os
import signal
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import QItemSelectionModel, QSettings
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox
except ImportError:                       # pragma: no cover
    QApplication = None

from archpm.helptext import CANNOT_UNDO
from archpm.model import ProcSample, Snapshot, SystemSample


def proc(pid, name, born=1000.0):
    return ProcSample(pid=pid, ppid=1, name=name, username="alex", owned=True,
                      cmdline=f"/usr/bin/{name}", argv=(f"/usr/bin/{name}",), program=True,
                      create_time=born)


@unittest.skipUnless(QApplication, "PySide6 not installed")
class Escalation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
            QSettings.setPath(fmt, QSettings.Scope.UserScope, cls.tmp.name)
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        from archpm.actions import UserBackend
        from archpm.ui.procview import ProcessView
        self.sent = []
        backend = UserBackend()
        backend.send_signal = lambda pid, sig: self.sent.append((pid, sig))
        self.view = ProcessView(8, backend)
        self.view.show()
        self.view.set_mode("flat")
        self.view.cb_all.setChecked(True)
        self.procs = [proc(9000, "game"), proc(9001, "editor")]
        self.feed(self.procs)
        self.dialogs = []
        self.answer = False
        self.view._confirm = self._record
        self.offers = []
        self.view.offer.connect(lambda t, b, a: self.offers.append((t, b, a)))

    def _record(self, verdict):
        self.dialogs.append(verdict)
        return self.answer

    def feed(self, procs):
        self.view.update_view(Snapshot(system=SystemSample(), procs=list(procs)))

    def select(self, pid):
        idx = self.view.proxy.mapFromSource(self.view.model.index_for_pid(pid))
        self.assertTrue(idx.isValid())
        flag = QItemSelectionModel.SelectionFlag
        self.view.table.selectionModel().select(idx, flag.ClearAndSelect | flag.Rows)

    def test_terminate_and_force_kill_on_one_process_ask_and_say_the_sentence(self):
        self.select(9000)
        self.view._signal_selected(signal.SIGTERM)
        self.assertEqual(len(self.dialogs), 1, "a single process asks like a group")
        self.assertEqual(self.dialogs[0].title, "Ask game to quit?")
        self.assertTrue(self.dialogs[0].text.endswith(CANNOT_UNDO))
        self.assertEqual(self.sent, [], "refused: nothing sent")
        self.view._signal_selected(signal.SIGKILL, confirm=True)
        self.assertTrue(self.dialogs[1].text.endswith(CANNOT_UNDO))
        self.assertIn("Unsaved work is lost", self.dialogs[1].text)
        self.assertEqual(self.sent, [])

    def test_a_process_that_stays_after_terminate_gets_one_offer_to_force_it(self):
        from archpm.ui import procview
        self.answer = True
        self.select(9000)
        self.view._signal_selected(signal.SIGTERM)
        self.assertEqual(self.sent, [(9000, signal.SIGTERM)])
        self.assertEqual(len(self.view._watches), 1)
        self.feed(self.procs)                          # still there, but too soon
        self.assertEqual(self.offers, [])
        self.view._watches[0]["sent"] -= procview.WATCH_S + 1
        self.feed(self.procs)
        self.assertEqual(len(self.offers), 1)
        text, button, action = self.offers[0]
        self.assertEqual((text, button), ("game is still running.", "Force kill"))
        self.assertEqual(self.view._watches, [], "one offer per action")
        self.feed(self.procs)
        self.assertEqual(len(self.offers), 1)
        self.assertEqual(self.sent, [(9000, signal.SIGTERM)], "nothing forced by itself")
        # the button: the same confirmation as any Force kill, then SIGKILL
        self.answer = False
        action()
        self.assertTrue(self.dialogs[-1].text.endswith(CANNOT_UNDO))
        self.assertEqual(self.sent, [(9000, signal.SIGTERM)])
        self.answer = True
        action()
        self.assertEqual(self.sent, [(9000, signal.SIGTERM), (9000, signal.SIGKILL)])

    def test_a_process_that_went_or_was_replaced_is_not_offered(self):
        from archpm.ui import procview
        self.answer = True
        self.select(9000)
        self.view._signal_selected(signal.SIGTERM)
        self.view._watches[0]["sent"] -= procview.WATCH_S + 1
        self.feed([proc(9001, "editor")])              # gone
        self.assertEqual(self.offers, [])
        self.assertEqual(self.view._watches, [])
        self.select(9001)
        self.view._signal_selected(signal.SIGTERM)
        self.view._watches[0]["sent"] -= procview.WATCH_S + 1
        self.feed([proc(9001, "editor", born=2000.0)])   # the pid reused by another process
        self.assertEqual(self.offers, [])

    def test_a_watch_is_checked_while_another_page_is_shown(self):
        from archpm.ui import procview
        self.answer = True
        self.select(9000)
        self.view._signal_selected(signal.SIGTERM)
        self.view._watches[0]["sent"] -= procview.WATCH_S + 1
        self.view.hide()
        self.feed(self.procs)
        self.assertEqual(len(self.offers), 1, "the toast is not tied to the page")

    def test_end_game_and_the_journal_say_the_sentence(self):
        from archpm.cleanup import CleanupItem
        from archpm.root.client import RootClient
        from archpm.ui.cleanup import CleanupView
        from archpm.ui.dashboard import GameCard
        texts = []
        with mock.patch.object(QMessageBox, "question",
                               lambda *a, **k: texts.append(a[2]) or QMessageBox.StandardButton.No):
            card = GameCard(8)
            card.pid, card.name, card._tree_pids = 9000, "Space Pilot", [9000]
            card._confirm_terminate()
            v = CleanupView(RootClient())
            v.scan = lambda: None
            v.items = [CleanupItem(id="journal", name="System logs", description="", size=1 << 20,
                                   needs_root=True, helper_command="journal-vacuum")]
            v._fill()
            v._checks[0].setChecked(True)
            v._clean()
        self.assertEqual(len(texts), 2)
        for t in texts:
            self.assertIn(CANNOT_UNDO, t)


@unittest.skipUnless(QApplication, "PySide6 not installed")
class ToastButton(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
            QSettings.setPath(fmt, QSettings.Scope.UserScope, cls.tmp.name)
        cls.app = QApplication.instance() or QApplication([])
        from archpm.ui import theme
        theme.apply(cls.app, "dark")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_a_notice_with_a_button_runs_it_once_and_goes(self):
        from PySide6.QtWidgets import QWidget

        from archpm.ui.chrome import Toast
        host = QWidget()
        host.resize(800, 400)
        host.show()
        toast = Toast(host)
        ran = []
        toast.show_action("game is still running.", "Force kill", lambda: ran.append(1))
        QTest.qWait(200)
        self.assertEqual(toast.showing(), "game is still running.")
        self.assertTrue(toast.button.isVisible())
        self.assertEqual(toast.button.text(), "Force kill")
        toast.button.click()
        self.assertEqual(ran, [1])
        QTest.qWait(400)
        self.assertFalse(toast.isVisible())
        toast.show_message("plain")
        QTest.qWait(200)
        self.assertFalse(toast.button.isVisible(), "a plain message has no button")
        host.close()


if __name__ == "__main__":
    unittest.main()
