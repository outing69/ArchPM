"""Sampling happens in its own thread; the UI thread only receives ready-made snapshots."""
from __future__ import annotations

from PySide6.QtCore import QMetaObject, QObject, Qt, QThread, QTimer, Signal, Slot

from ..gpu import GpuMonitor
from ..model import Snapshot
from ..publisher import PublishError, agent_service_active, publish
from ..sampler import Sampler


class SampleWorker(QObject):
    sampled = Signal(object)
    failed = Signal(str)
    notice = Signal(str)     # something worth a line in the status bar, not an error in sampling
    # Carries an interval change from the GUI thread to set_interval over
    # here; see request_interval.
    _interval_requested = Signal(float)

    AGENT_CHECK_EVERY = 15   # ticks between looks at the agent service (30 s at 2 s)

    def __init__(self, interval: float = 2.0, publish_status: bool = True) -> None:
        super().__init__()
        self.interval = interval
        self.publish_status = publish_status   # False = never write status.json
        self.agent_active = False              # True = the service writes it; we stay out
        self._ticks = 0
        self._timer: QTimer | None = None
        self._sampler: Sampler | None = None
        self.gpu = GpuMonitor()
        self._interval_requested.connect(self.set_interval)

    @Slot()
    def start(self) -> None:
        self.agent_active = agent_service_active()
        self.gpu.start()
        self._sampler = Sampler(self.gpu)
        self._sampler.prime()
        self._timer = QTimer()
        self._timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._timer.timeout.connect(self._tick)
        self._timer.start(int(self.interval * 1000))

    @Slot(float)
    def set_interval(self, seconds: float) -> None:
        """Runs on the worker thread only: the timer was made there in
        start(), and Qt refuses to start or stop a timer from any other
        thread (the call is dropped with a warning, and the timer is left
        stopped). Other threads go through request_interval."""
        self.interval = seconds
        if self._timer:
            self._timer.start(int(seconds * 1000))

    def request_interval(self, seconds: float) -> None:
        """Change the interval from any thread. Delivered as a queued signal,
        so set_interval runs on the worker thread, where the timer lives."""
        self._interval_requested.emit(seconds)

    def request_stop(self) -> None:
        """Stop from any thread, and return once it is done. The timer is
        stopped on its own thread through a blocking queued call; when that
        thread is not running (or we are on it), stop() runs in place."""
        thread = self.thread()
        if thread is None or not thread.isRunning() or QThread.currentThread() is thread:
            self.stop()
            return
        QMetaObject.invokeMethod(self, "stop", Qt.ConnectionType.BlockingQueuedConnection)

    @Slot()
    def _tick(self) -> None:
        if self._sampler is None:
            return
        try:
            snap: Snapshot = self._sampler.sample()
        except Exception as exc:  # noqa: BLE001 - sampling must never take the app down
            self.failed.emit(str(exc))
            return
        self._ticks += 1
        if self._ticks % self.AGENT_CHECK_EVERY == 0:
            self.agent_active = agent_service_active()
        if self.publish_status and not self.agent_active:
            try:
                publish(snap)
            except PublishError as exc:
                # Nowhere safe to write: say so once and stop writing for this run.
                self.publish_status = False
                self.notice.emit(f"Not publishing for the widgets: {exc}")
        self.sampled.emit(snap)

    @Slot()
    def stop(self) -> None:
        if self._timer:
            self._timer.stop()
        self.gpu.stop()


def run_in_thread(worker: SampleWorker) -> QThread:
    thread = QThread()
    thread.setObjectName("archpm-sampler")
    worker.moveToThread(thread)
    thread.started.connect(worker.start)
    thread.start()
    return thread


def wait_for_threads(root: QObject, msec: int) -> list[QThread]:
    """Join every QThread that lives under `root` in the object tree, and
    return the ones still running when the time ran out.

    A QThread destroyed while it runs takes the process down with it. The
    pages make their threads (a scan, a spec gather, a snapshot read, a
    firewall read) as children of the page, so the window finds them here
    without a list to keep: a page added later is covered the moment its
    thread has a parent. The sampler's own thread has none and is stopped
    by the window itself."""
    late: list[QThread] = []
    for thread in root.findChildren(QThread):
        if thread.isRunning() and not thread.wait(msec):
            late.append(thread)
    return late
