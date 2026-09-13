"""Sampling happens in its own thread; the UI thread only receives ready-made snapshots."""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot

from ..gpu import GpuMonitor
from ..model import Snapshot
from ..publisher import publish
from ..sampler import Sampler


class SampleWorker(QObject):
    sampled = Signal(object)
    failed = Signal(str)

    def __init__(self, interval: float = 2.0, publish_status: bool = True) -> None:
        super().__init__()
        self.interval = interval
        self.publish_status = publish_status
        self._timer: QTimer | None = None
        self._sampler: Sampler | None = None
        self.gpu = GpuMonitor()

    @Slot()
    def start(self) -> None:
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
        if self.publish_status:
            try:
                publish(snap)
            except OSError:
                pass
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
