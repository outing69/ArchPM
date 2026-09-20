"""One way to do background work: a Task under a parent. Its result lands
on the GUI thread after the thread has finished, its fault reaches the page
instead of vanishing, the window's shutdown finds and joins every one of
them through the object tree, and the sampler is a Task like the rest.
These tests drive the worker the way the window does, from the main
thread, and count what arrives."""
from __future__ import annotations

import sys
import threading
import time
import unittest
from unittest.mock import patch

try:
    from PySide6.QtCore import QEventLoop, QObject, QThread, QTimer, qInstallMessageHandler
    from PySide6.QtWidgets import QApplication, QWidget

    from archpm import firewall, snapshots
    from archpm.model import Snapshot, SystemSample
    from archpm.root.client import RootClient
    from archpm.ui import worker as worker_mod
    from archpm.ui.network import NetworkView
    from archpm.ui.snapshots import SnapshotsView
    from archpm.ui.worker import (
        SampleWorker,
        Task,
        active,
        fault,
        run_in_thread,
        start_task,
        wait_for_threads,
    )
except ImportError:   # PySide6 not installed
    QApplication = None
    QThread = object      # so the helper class below still defines; its tests are skipped


class FakeSampler:
    """Answers at once, so the tick rate is the loop's and nothing else's."""

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def prime(self) -> None:
        pass

    def sample(self) -> Snapshot:
        return Snapshot(system=SystemSample(ts=time.time()))


class BrokenSampler(FakeSampler):
    def prime(self) -> None:
        raise OSError("no /proc here")


class FakeGpu:
    stopped = 0

    def start(self) -> None:
        pass

    def stop(self) -> None:
        FakeGpu.stopped += 1


def pump(ms: int) -> None:
    """Run the main thread's event loop for a while, as the window does.
    QTest.qWait would hold the GIL while it sleeps and starve the worker
    thread of Python time, which the real app's exec() never does."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def pump_until(cond, timeout_ms: int = 3000) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    while not cond() and time.monotonic() < deadline:
        pump(10)


@unittest.skipUnless(QApplication, "PySide6 not installed")
class Tasks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def setUp(self):
        self.owner = QObject()
        self.addCleanup(wait_for_threads, self.owner, 5000)

    def test_the_result_lands_on_the_gui_thread_after_the_thread_finished(self):
        got = []

        def done(value):
            got.append((value, QThread.currentThread() is self.app.thread(),
                        active(self.owner, "read") is None))
        task = start_task(lambda _t: threading.current_thread().name, self.owner, "read",
                          done=done, failed=got.append)
        self.assertIs(task.parent(), self.owner, "a child, so shutdown finds it")
        self.assertIsNotNone(active(self.owner, "read"))
        pump_until(lambda: got)
        self.assertEqual(len(got), 1)
        value, on_gui, finished = got[0]
        self.assertNotEqual(value, threading.current_thread().name, "the function ran elsewhere")
        self.assertTrue(on_gui, "delivered on the GUI thread")
        self.assertTrue(finished, "delivered once the thread is no longer running")

    def test_a_fault_reaches_the_page_as_the_exception(self):
        got = []

        def boom(_t):
            raise ValueError("a shape the parser did not expect")
        start_task(boom, self.owner, "read", done=lambda _v: got.append("done"),
                   failed=got.append)
        pump_until(lambda: got)
        self.assertEqual(len(got), 1)
        self.assertIsInstance(got[0], ValueError)
        self.assertEqual(fault(got[0]), "ValueError: a shape the parser did not expect")

    def test_progress_lines_arrive_in_order_before_the_result(self):
        got = []

        def work(task):
            for i in range(3):
                task.progress.emit(f"line {i}")
            return "total"
        start_task(work, self.owner, "empty", done=got.append, failed=got.append,
                   progress=got.append)
        pump_until(lambda: len(got) == 4)
        self.assertEqual(got, ["line 0", "line 1", "line 2", "total"])

    def test_active_asks_by_name_and_ignores_what_has_finished(self):
        release = threading.Event()
        start_task(lambda _t: release.wait(10), self.owner, "slow",
                   failed=lambda _e: None)
        try:
            self.assertIsNotNone(active(self.owner, "slow"))
            self.assertIsNotNone(active(self.owner))
            self.assertIsNone(active(self.owner, "other"))
        finally:
            release.set()
        pump_until(lambda: active(self.owner) is None)
        self.assertIsNone(active(self.owner, "slow"))

    def test_cancel_ends_an_idle_and_a_poke_does_not(self):
        seen = []

        def loop(task):
            while not task.idle(10):
                seen.append("poked")
            return "cancelled"
        got = []
        task = start_task(loop, self.owner, "loop", done=got.append, failed=got.append)
        pump(50)
        task.poke()
        pump_until(lambda: seen)
        self.assertEqual(seen, ["poked"])
        self.assertTrue(task.isRunning(), "a poke does not end the loop")
        task.cancel()
        pump_until(lambda: got)
        self.assertEqual(got, ["cancelled"])

    def test_a_poke_before_the_idle_ends_it_at_once(self):
        task = Task(lambda t: None, self.owner, "x", failed=lambda _e: None)
        task.poke()
        t0 = time.monotonic()
        self.assertFalse(task.idle(5.0))
        self.assertLess(time.monotonic() - t0, 1.0)
        self.assertFalse(task.idle(0), "the next idle is a plain one; not cancelled")
        task.cancel()
        self.assertTrue(task.idle(5.0))

    def test_wait_for_threads_cancels_a_loop_it_would_otherwise_wait_out(self):
        start_task(lambda t: t.idle(30), self.owner, "loop", failed=lambda _e: None)
        t0 = time.monotonic()
        self.assertEqual(wait_for_threads(self.owner, 5000), [])
        self.assertLess(time.monotonic() - t0, 2.0)


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
        self.owner = QObject()
        self.worker = SampleWorker(interval=0.3, publish_status=False)
        self.worker.sampled.connect(lambda _snap: self.stamps.append(time.monotonic()))
        self.thread = run_in_thread(self.worker, self.owner)

    def tearDown(self):
        wait_for_threads(self.owner, 3000)
        qInstallMessageHandler(self._previous)

    def _wait_for(self, count: int, timeout_ms: int) -> None:
        pump_until(lambda: len(self.stamps) >= count, timeout_ms)

    def test_the_sampler_is_a_task_under_the_window(self):
        self.assertIs(self.thread.parent(), self.owner)
        self.assertIs(active(self.owner, "sampler"), self.thread)

    def test_a_change_from_the_main_thread_is_followed_by_samples_at_the_new_rate(self):
        self._wait_for(2, 2000)
        self.assertGreaterEqual(len(self.stamps), 2, "no samples at the starting interval")
        self.worker.request_interval(0.05)
        before = len(self.stamps)
        pump(600)
        after = self.stamps[before + 1:]
        gaps = [b - a for a, b in zip(after, after[1:], strict=False)]
        self.assertGreaterEqual(len(self.stamps) - before, 6,
                                f"{len(self.stamps) - before} samples in 600 ms after asking "
                                "for 50 ms; the change did not reach the loop")
        self.assertLess(max(gaps), 0.2, f"gaps after the change: {[round(g, 3) for g in gaps]}")
        self.assertFalse([m for m in self.messages if "thread" in m], self.messages)

    def test_a_change_takes_effect_at_once_not_after_the_old_interval(self):
        self.worker.request_interval(2.0)
        self._wait_for(1, 3000)
        t0 = time.monotonic()
        self.worker.request_interval(0.05)
        self._wait_for(2, 2000)
        self.assertLess(self.stamps[-1] - t0, 1.0, "the next sample waited out the old interval")

    def test_stop_from_the_main_thread_ends_the_loop_without_a_warning(self):
        self._wait_for(1, 2000)
        stopped = FakeGpu.stopped
        self.worker.request_stop()
        self.assertTrue(self.thread.wait(3000), "the loop ended")
        self.assertEqual(FakeGpu.stopped, stopped + 1, "the GPU monitor is stopped with it")
        seen = len(self.stamps)
        pump(400)
        self.assertEqual(len(self.stamps), seen, "samples kept coming after stop")
        self.assertFalse([m for m in self.messages if "thread" in m], self.messages)

    def test_a_fault_before_the_loop_is_a_sampling_error_not_a_silent_thread(self):
        wait_for_threads(self.owner, 3000)
        FakeGpu.stopped = 0
        failures = []
        with patch.object(worker_mod, "Sampler", BrokenSampler):
            worker = SampleWorker(interval=0.3, publish_status=False)
            worker.failed.connect(failures.append)
            run_in_thread(worker, self.owner)
            pump_until(lambda: failures)
        self.assertEqual(failures, ["OSError: no /proc here"])
        self.assertEqual(FakeGpu.stopped, 1, "the GPU monitor is stopped on the way out")


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
                self.assertIsNotNone(active(view), "and active() sees it")
                self.assertEqual(wait_for_threads(view, 5000), [])
                self.assertFalse(threads[0].isRunning())
                pump(20)     # the result lands while the page is alive


if __name__ == "__main__":
    unittest.main()
