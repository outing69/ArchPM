"""The sampler runs on a thread of its own with a QTimer made there. Qt
refuses to start or stop that timer from another thread and drops the call
with a warning, so a control that reaches it from the GUI thread appears to
work and does nothing. These tests drive the worker the way the window does,
from the main thread, and count what arrives."""
from __future__ import annotations

import sys
import threading
import time
import unittest
from unittest.mock import patch

try:
    from PySide6.QtCore import QEventLoop, QThread, QTimer, qInstallMessageHandler
    from PySide6.QtWidgets import QApplication, QWidget

    from archpm import firewall, snapshots
    from archpm.model import Snapshot, SystemSample
    from archpm.root.client import RootClient
    from archpm.ui import worker as worker_mod
    from archpm.ui.network import NetworkView
    from archpm.ui.snapshots import SnapshotsView
    from archpm.ui.worker import SampleWorker, run_in_thread, wait_for_threads
except ImportError:   # PySide6 not installed
    QApplication = None
    QThread = object      # so the helper class below still defines; its tests are skipped


class FakeSampler:
    """Answers at once, so the tick rate is the timer's and nothing else's."""

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def prime(self) -> None:
        pass

    def sample(self) -> Snapshot:
        return Snapshot(system=SystemSample(ts=time.time()))


class FakeGpu:
    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


@unittest.skipUnless(QApplication, "PySide6 not installed")
class Interval(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def setUp(self):
        self.messages: list[str] = []
        self._previous = qInstallMessageHandler(lambda _t, _c, m: self.messages.append(m))
        patches = [patch.object(worker_mod, "Sampler", FakeSampler),
                   patch.object(worker_mod, "GpuMonitor", FakeGpu),
                   patch.object(worker_mod, "agent_service_active", lambda: False)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.stamps: list[float] = []
        self.worker = SampleWorker(interval=0.3, publish_status=False)
        self.worker.sampled.connect(lambda _snap: self.stamps.append(time.monotonic()))
        self.thread = run_in_thread(self.worker)

    def tearDown(self):
        if self.thread.isRunning():
            self.worker.request_stop()
            self.thread.quit()
            self.thread.wait(3000)
        qInstallMessageHandler(self._previous)

    @staticmethod
    def _pump(ms: int) -> None:
        """Run the main thread's event loop for a while, as the window does.
        QTest.qWait would hold the GIL while it sleeps and starve the worker
        thread of Python time, which the real app's exec() never does."""
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def _wait_for(self, count: int, timeout_ms: int) -> None:
        deadline = time.monotonic() + timeout_ms / 1000
        while len(self.stamps) < count and time.monotonic() < deadline:
            self._pump(10)

    def test_a_change_from_the_main_thread_is_followed_by_samples_at_the_new_rate(self):
        self._wait_for(2, 2000)
        self.assertGreaterEqual(len(self.stamps), 2, "no samples at the starting interval")
        self.worker.request_interval(0.05)
        before = len(self.stamps)
        self._pump(600)
        after = self.stamps[before + 1:]
        gaps = [b - a for a, b in zip(after, after[1:], strict=False)]
        self.assertGreaterEqual(len(self.stamps) - before, 6,
                                f"{len(self.stamps) - before} samples in 600 ms after asking "
                                "for 50 ms; the change did not reach the timer")
        self.assertLess(max(gaps), 0.2, f"gaps after the change: {[round(g, 3) for g in gaps]}")
        self.assertFalse([m for m in self.messages if "thread" in m], self.messages)

    def test_stop_from_the_main_thread_stops_the_timer_without_a_warning(self):
        self._wait_for(1, 2000)
        self.worker.request_stop()
        self.assertFalse(self.worker._timer.isActive())
        seen = len(self.stamps)
        self._pump(400)
        self.assertEqual(len(self.stamps), seen, "samples kept coming after stop")
        self.assertFalse([m for m in self.messages if "thread" in m], self.messages)
        self.assertIsNot(QThread.currentThread(), self.worker.thread())


class _Slow(QThread):
    """Runs for a moment, long enough for shutdown to arrive first; or, given
    an event, until that event is set."""

    def __init__(self, parent=None, until: threading.Event | None = None) -> None:
        super().__init__(parent)
        self.until = until

    def run(self) -> None:
        if self.until is not None:
            self.until.wait(10)
        else:
            time.sleep(0.3)


def _slow_detect(result):
    def detect(*_args, **_kwargs):
        time.sleep(0.3)
        return result
    return detect


@unittest.skipUnless(QApplication, "PySide6 not installed")
class PageThreads(unittest.TestCase):
    """Closing the window while a page still reads must wait for that read.
    The window used to wait for two pages by attribute name and missed the
    other two; now it joins every thread under it in the object tree."""

    @classmethod
    def setUpClass(cls):
        import tempfile

        from PySide6.QtCore import QSettings
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])
        cls.tmp = tempfile.TemporaryDirectory()
        for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
            QSettings.setPath(fmt, QSettings.Scope.UserScope, cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_threads_anywhere_under_the_root_are_joined_and_others_are_left_alone(self):
        root = QWidget()
        page = QWidget(root)
        deep = _Slow(page)
        release = threading.Event()
        loose = _Slow(until=release)    # no parent: not the window's to wait for
        deep.start()
        loose.start()
        try:
            self.assertEqual(wait_for_threads(root, 5000), [])
            self.assertFalse(deep.isRunning())
            self.assertTrue(loose.isRunning())
        finally:
            release.set()
            loose.wait(5000)

    def test_a_running_read_is_reported_when_the_wait_runs_out(self):
        root = QWidget()
        slow = _Slow(root)
        slow.start()
        try:
            self.assertEqual(wait_for_threads(root, 1), [slow])
        finally:
            slow.wait(5000)

    def test_the_snapshot_and_firewall_reads_are_found_through_their_page(self):
        cases = [
            (SnapshotsView(RootClient()), snapshots, snapshots.Setup(), "read"),
            (NetworkView(lambda _port: "", RootClient()), firewall, firewall.Setup(),
             "read_firewall"),
        ]
        for view, backend, setup, start in cases:
            with self.subTest(page=type(view).__name__), \
                    patch.object(backend, "detect", _slow_detect(setup)):
                getattr(view, start)()
                threads = [t for t in view.findChildren(QThread) if t.isRunning()]
                self.assertEqual(len(threads), 1, "the read did not start a thread")
                self.assertEqual(wait_for_threads(view, 5000), [])
                self.assertFalse(threads[0].isRunning())


if __name__ == "__main__":
    unittest.main()
