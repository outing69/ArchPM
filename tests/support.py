"""Shared helpers for the tests that run pages offscreen."""
from __future__ import annotations

import time

try:
    from PySide6.QtCore import QEventLoop, QTimer

    from archpm.ui.worker import wait_for_threads
except ImportError:                       # pragma: no cover - CI has no PySide6
    QEventLoop = None


def pump(ms: int = 10) -> None:
    """Run the main thread's event loop for a while, as the window does.
    QTest.qWait would hold the GIL while it sleeps and starve a worker
    thread of Python time, which the real app's exec() never does."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def pump_until(cond, timeout_ms: int = 3000) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    while not cond() and time.monotonic() < deadline:
        pump(10)


def settle(widget, msec: int = 5000) -> None:
    """Join the widget's tasks and let their results land while the widget
    is alive. A widget dropped by Python with a task's delivery or its
    deleteLater still queued crashes a later test's event loop."""
    wait_for_threads(widget, msec)
    pump(10)
