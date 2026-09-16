"""Sampling happens in its own thread; the UI thread only receives ready-made snapshots."""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot

from ..gpu import GpuMonitor
from ..model import Snapshot
from ..publisher import PublishError, agent_service_active, publish
from ..sampler import Sampler


class SampleWorker(QObject):
    sampled = Signal(object)
    failed = Signal(str)
    notice = Signal(str)     # something worth a line in the status bar, not an error in sampling

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
        self.interval = seconds
        if self._timer:
            self._timer.start(int(seconds * 1000))

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
