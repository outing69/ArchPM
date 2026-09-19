"""The sampler runs on a thread of its own with a QTimer made there. Qt
refuses to start or stop that timer from another thread and drops the call
with a warning, so a control that reaches it from the GUI thread appears to
work and does nothing. These tests drive the worker the way the window does,
from the main thread, and count what arrives."""
from __future__ import annotations

import sys
import time
import unittest
from unittest.mock import patch

try:
    from PySide6.QtCore import QEventLoop, QThread, QTimer, qInstallMessageHandler
    from PySide6.QtWidgets import QApplication

    from archpm.model import Snapshot, SystemSample
    from archpm.ui import worker as worker_mod
    from archpm.ui.worker import SampleWorker, run_in_thread
except ImportError:   # PySide6 not installed
    QApplication = None


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


if __name__ == "__main__":
    unittest.main()
