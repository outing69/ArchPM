"""A pkexec that cannot be started must not leave a page busy. Through
0.2.55 three pages listened for the call's end only and stayed busy for
good, and the root panel called it "exit code -1". Since 0.2.59 every page
goes through one wrapper (ui.worker.call_helper around RootClient.invoke),
so the start failure is one OSError branch; these tests hold each page to
what it shows and to its buttons coming back."""
from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from archpm.ui.worker import active
    from tests.support import pump_until, settle
except ImportError:                       # pragma: no cover
    QApplication = None

from archpm.root.client import RootClient

READY = SimpleNamespace(ready=True, problem="", helper=True, policy=True, pkexec=True)
NOWHERE = "/nonexistent/pkexec-for-this-test"


class Broken(RootClient):
    """The real client, with a pkexec that does not exist."""

    def argv(self, *args, elevated=True):
        return [NOWHERE, "helper", *args]

    @staticmethod
    def parse(code, out, err, command=""):
        raise AssertionError("parse must not run when nothing started")

    @staticmethod
    def status():
        return {"uid": 1000, "swappiness": 60}     # the root panel's in-process read


def pump(until, timeout_ms=2000) -> None:
    pump_until(until, timeout_ms)


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
            self.assertIsNotNone(active(v, "helper"), "the call was started")
            pump(lambda: active(v, "helper") is None)
            settle(v)
        self.assertIsNone(active(v), "busy flag cleared")
        self.assertTrue(v.btn_read.isEnabled())
        self.assertIn("could not be started", v.lbl_state.text())
        self.assertIn("No such file or directory", v.lbl_state.text())

    def test_network_page_recovers_and_says_so(self):
        from archpm import firewall
        from archpm.ui import network as page
        v = page.NetworkView(lambda _port: "", Broken())
        v.fw_setup = firewall.Setup(ufw=True)
        v.fw_state = firewall.State(tool="ufw", needs_root=True)
        with patch.object(page, "check", lambda: READY):
            v.read_firewall_root()
            self.assertIsNotNone(active(v, "helper"))
            pump(lambda: active(v, "helper") is None)
            settle(v)
        self.assertIsNone(active(v))
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
        self.assertIsNotNone(active(v, "helper"))
        pump(lambda: active(v, "helper") is None)
        settle(v)
        self.assertIsNone(active(v))
        log = v.log.toPlainText()
        self.assertIn("System logs: the root helper could not be started", log)
        self.assertIn("Done.", log)

    def test_root_panel_recovers_and_names_the_failure(self):
        from archpm.actions import UserBackend
        from archpm.ui import rootpanel as page
        from tests.support import settle
        v = page.RootPanel(Broken(), UserBackend())
        self.addCleanup(settle, v)       # the service list's read lands before v goes
        with patch.object(page, "check", lambda: READY):
            v._run("swappiness", "60")
            self.assertIsNotNone(active(v, "action"))
            pump(lambda: active(v, "action") is None)
            settle(v)
        self.assertIsNone(active(v, "action"))
        self.assertTrue(v.isEnabled())
        log = v.log.toPlainText()
        self.assertIn("the root helper could not be started", log)
        self.assertNotIn("exit code -1", log)


if __name__ == "__main__":
    unittest.main()
