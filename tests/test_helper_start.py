"""A pkexec that cannot be started emits QProcess.errorOccurred and never
finished. Every page that calls the root helper must clear its busy flag
and say what happened; through 0.2.55 three pages connected finished only
and stayed busy for good, and the root panel called it "exit code -1"."""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import QEventLoop, QSettings, QTimer
    from PySide6.QtWidgets import QApplication
except ImportError:                       # pragma: no cover
    QApplication = None

READY = SimpleNamespace(ready=True, problem="", helper=True, policy=True, pkexec=True)
NOWHERE = "/nonexistent/pkexec-for-this-test"


class Broken:
    """A client whose pkexec does not exist."""

    def argv(self, *args, elevated=True):
        return [NOWHERE, "helper", *args]

    @staticmethod
    def parse(code, out, err, command=""):
        raise AssertionError("parse must not run when nothing started")

    @staticmethod
    def status():
        return {"uid": 1000, "swappiness": 60}     # the root panel's in-process read


def pump(until, timeout_ms=2000) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    while not until() and time.monotonic() < deadline:
        loop = QEventLoop()
        QTimer.singleShot(10, loop.quit)
        loop.exec()


@unittest.skipUnless(QApplication, "PySide6 not installed")
class StartFailure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
            QSettings.setPath(fmt, QSettings.Scope.UserScope, cls.tmp.name)
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_snapshots_page_recovers_and_says_so(self):
        from archpm import snapshots
        from archpm.ui import snapshots as page
        v = page.SnapshotsView(Broken())
        v.setup = snapshots.Setup(snapper=True, configs=["root"])
        v.listing = snapshots.Listing(tool="snapper", needs_root=True)
        with patch.object(page, "check", lambda: READY):
            v.read_root()
            self.assertIsNotNone(v._proc, "the call was started")
            pump(lambda: v._proc is None)
        self.assertIsNone(v._proc, "busy flag cleared")
        self.assertTrue(v.btn_read.isEnabled())
        self.assertIn("could not be started", v.lbl_state.text())

    def test_network_page_recovers_and_says_so(self):
        from archpm import firewall
        from archpm.ui import network as page
        v = page.NetworkView(lambda _port: "", Broken())
        v.fw_setup = firewall.Setup(ufw=True)
        v.fw_state = firewall.State(tool="ufw", needs_root=True)
        with patch.object(page, "check", lambda: READY):
            v.read_firewall_root()
            self.assertIsNotNone(v._fw_proc)
            pump(lambda: v._fw_proc is None)
        self.assertIsNone(v._fw_proc)
        self.assertIn("could not be started", v.fw_state.error)

    def test_cleanup_page_recovers_and_says_so(self):
        from archpm.cleanup import CleanupItem
        from archpm.ui import cleanup as page
        v = page.CleanupView(Broken())
        v.scan = lambda: None
        item = CleanupItem(id="journal", name="System logs", description="", size=1,
                           needs_root=True, helper_item="journal")
        v._queue = [item]
        v._next_root()
        self.assertIsNotNone(v._proc)
        pump(lambda: v._proc is None)
        self.assertIsNone(v._proc)
        log = v.log.toPlainText()
        self.assertIn("System logs: the root helper could not be started", log)
        self.assertIn("Done.", log)

    def test_root_panel_recovers_and_names_the_failure(self):
        from archpm.actions import UserBackend
        from archpm.ui import rootpanel as page
        v = page.RootPanel(Broken(), UserBackend())
        with patch.object(page, "check", lambda: READY):
            v._run("swappiness", "60")
            self.assertIsNotNone(v._proc)
            pump(lambda: v._proc is None)
        self.assertIsNone(v._proc)
        self.assertTrue(v.isEnabled())
        log = v.log.toPlainText()
        self.assertIn("the root helper could not be started", log)
        self.assertNotIn("exit code -1", log)


if __name__ == "__main__":
    unittest.main()
