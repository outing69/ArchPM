"""Everything that runs off the GUI thread goes through one class, Task; the
sampler is the one Task that runs for the window's lifetime.

A Task is a QThread with a parent, so the window finds every one of them in
the object tree at shutdown (wait_for_threads) and a page cannot forget to
be joined. Its result, or the exception its function raised, is delivered
on the GUI thread once the thread has finished, so a page can start the
next read from its done slot. Whether a page is busy is asked of the tree
(active), not of an attribute the page keeps and clears in a copied slot.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot

from ..actions import ActionError, Cancelled
from ..gpu import GpuMonitor
from ..model import Snapshot
from ..publisher import PublishError, agent_service_active, publish
from ..sampler import Sampler


def fault(exc: BaseException) -> str:
    """An unexpected exception as one line for a page: the type and the
    message, the process list's failure box's shape."""
    return f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__


class Task(QThread):
    """One piece of work off the GUI thread.

    `fn` runs on the thread with the task as its argument, for the progress
    signal and for idle(). What it returns goes to `done`, what it raises
    goes to `failed`; both are called on the GUI thread after the thread has
    finished, and the task deletes itself afterwards. `failed` is not
    optional: a fault that goes nowhere is a page stuck on "reading…" for
    good. `name` is what active() asks for."""

    progress = Signal(str)

    def __init__(self, fn: Callable[[Task], object], parent: QObject, name: str, *,
                 failed: Callable[[BaseException], None], done: Callable | None = None,
                 progress: Callable[[str], None] | None = None) -> None:
        super().__init__(parent)
        self.name = name
        self.setObjectName(f"archpm-{name}")
        self._fn = fn
        self._done, self._failed = done, failed
        self._result: object = None
        self._error: BaseException | None = None
        self._cv = threading.Condition()
        self._cancelled = False
        self._poked = False
        if progress is not None:
            self.progress.connect(progress)
        # both queued to the GUI thread, in this order: the page hears the
        # result while the task still exists, then the task goes
        self.finished.connect(self._deliver)
        self.finished.connect(self.deleteLater)

    def run(self) -> None:
        try:
            self._result = self._fn(self)
        except Exception as exc:  # noqa: BLE001 - delivered to the page, never swallowed
            self._error = exc

    @Slot()
    def _deliver(self) -> None:
        if self._error is not None:
            self._failed(self._error)
        elif self._done is not None:
            self._done(self._result)

    # -- for the function on the thread ---------------------------------------
    def idle(self, seconds: float) -> bool:
        """Sleep on the thread for up to `seconds`, and say whether the task
        has been cancelled. A poke() ends the sleep early without cancelling;
        the function decides what to do with the time that is left."""
        with self._cv:
            if not self._cancelled and not self._poked and seconds > 0:
                self._cv.wait(seconds)
            self._poked = False      # a poke before the sleep ends it at once
            return self._cancelled

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        """From any thread: the function is asked to stop at its next idle()."""
        with self._cv:
            self._cancelled = True
            self._cv.notify_all()

    def poke(self) -> None:
        """From any thread: wake an idle() before its time, without cancelling."""
        with self._cv:
            self._poked = True
            self._cv.notify_all()


def start_task(fn: Callable[[Task], object], parent: QObject, name: str, *,
               failed: Callable[[BaseException], None], done: Callable | None = None,
               progress: Callable[[str], None] | None = None) -> Task:
    """A Task under `parent`, started."""
    task = Task(fn, parent, name, failed=failed, done=done, progress=progress)
    task.start()
    return task


def call_helper(owner: QObject, client, *args: str, done: Callable, failed: Callable[[str], None],
                cancelled: Callable[[str], None] | None = None, name: str = "helper") -> Task:
    """One root helper call on a task under `owner`: the polkit prompt must
    not block the UI, and a call that cannot start must not leave a page
    busy. `done(result, elapsed_ms)` gets the helper's reply and the call's
    time; `cancelled(text)` a cancelled prompt, or `failed` when there is no
    `cancelled`; `failed(text)` the helper's refusal, a pkexec that could not
    be started, and any other fault as its type and message. Nothing is
    swallowed. No timeout: a prompt left open is not a hung helper."""
    def run(_task: Task):
        t0 = time.perf_counter()
        result = client.invoke(*args, timeout=None)
        return result, (time.perf_counter() - t0) * 1000

    def on_error(exc: BaseException) -> None:
        if isinstance(exc, Cancelled):
            (cancelled or failed)(str(exc))
        elif isinstance(exc, ActionError):
            failed(str(exc))
        else:
            failed(fault(exc))

    return start_task(run, owner, name, done=lambda reply: done(*reply), failed=on_error)


def active(owner: QObject, name: str | None = None) -> Task | None:
    """The running task with that name under `owner`, or any running task
    under it when no name is given; None when there is none. A task that
    has finished but is not deleted yet does not count."""
    for task in owner.findChildren(Task):
        if task.isRunning() and (name is None or task.name == name):
            return task
    return None


def wait_for_threads(root: QObject, msec: int) -> list[QThread]:
    """Cancel every task under `root` in the object tree, join every thread
    there, and return the ones still running when the time ran out.

    A QThread destroyed while it runs takes the process down with it. The
    sampler's task is a child of the window and the pages' reads (a scan,
    a spec gather, a snapshot read, a firewall read, the failed-services
    check) are children of their page, so the window finds them all here
    without a list to keep: a page added later is covered the moment its
    task has a parent."""
    for task in root.findChildren(Task):
        task.cancel()
    late: list[QThread] = []
    for thread in root.findChildren(QThread):
        if thread.isRunning() and not thread.wait(msec):
            late.append(thread)
    return late


class SampleWorker(QObject):
    """The sampling loop: one Snapshot every interval, on a Task of its own.
    The interval is measured from the previous sample's due time, so a slow
    sample does not push the cadence; a sample that overran is followed by
    the next at once, as a timer would coalesce it."""
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
        self._retime = False                   # request_interval: count anew from now
        self._sampler: Sampler | None = None
        self.gpu = GpuMonitor()
        self.task: Task | None = None

    def run(self, task: Task) -> None:
        """On the task's thread, until the task is cancelled."""
        self.agent_active = agent_service_active()
        self.gpu.start()
        try:
            self._sampler = Sampler(self.gpu)
            self._sampler.prime()
            due = time.monotonic() + self.interval
            while not task.idle(due - time.monotonic()):
                now = time.monotonic()
                if self._retime:
                    # a new interval: the next sample comes that long after
                    # the change, as restarting a timer would have it
                    self._retime = False
                    due = now + self.interval
                    continue
                if now < due:
                    continue      # woken early for nothing: sleep the rest
                self._tick()
                due = max(due + self.interval, time.monotonic())
        finally:
            self.gpu.stop()

    def request_interval(self, seconds: float) -> None:
        """Change the interval from any thread."""
        self.interval = seconds
        self._retime = True
        if self.task is not None:
            self.task.poke()

    def request_stop(self) -> None:
        """Stop from any thread: the loop ends after the sample in progress.
        Joining is the window's shutdown, through wait_for_threads."""
        if self.task is not None:
            self.task.cancel()

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


def run_in_thread(worker: SampleWorker, parent: QObject) -> Task:
    """The sampler's task, a child of the window so shutdown finds it with
    the pages' reads. A fault before the loop (the GPU monitor, the first
    sample) reaches the window as a sampling error instead of a silent
    thread with no samples."""
    worker.task = start_task(worker.run, parent, "sampler",
                             failed=lambda exc: worker.failed.emit(fault(exc)))
    return worker.task
