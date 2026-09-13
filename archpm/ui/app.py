"""Main window: dashboard + processes, fed by a single sampler thread."""
from __future__ import annotations

import sys
import time

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QLabel, QMainWindow, QMenu, QSystemTrayIcon, QTabWidget,
)

from .. import APP_NAME, __version__
from ..actions import get_backend
from ..model import Snapshot
from ..publisher import status_path
from ..root.client import ElevatedBackend, RootClient
from . import theme
from .dashboard import Dashboard
from .procview import ProcessView
from .widgets import mono
from .worker import SampleWorker, run_in_thread

INTERVALS = [("0.5 s", 0.5), ("1 s", 1.0), ("2 s", 2.0), ("5 s", 5.0)]


def app_icon() -> QIcon:
    """Small bar chart as icon -- no separate assets needed."""
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(theme.SURFACE_ALT))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(2, 2, 60, 60, 14, 14)
    for i, (h, col) in enumerate(((22, theme.CPU), (38, theme.GPU), (30, theme.MEM))):
        p.setBrush(QColor(col))
        p.drawRoundedRect(14 + i * 13, 48 - h, 9, h, 4, 4)
    p.end()
    return QIcon(pm)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings("archpm", "ArchPM")
        self.backend = get_backend()
        self.root_client = RootClient()
        self.root_panel = None
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setWindowIcon(app_icon())
        self.resize(1180, 760)

        import psutil
        ncpu = psutil.cpu_count(logical=True) or 1

        self.tabs = QTabWidget()
        self.dashboard = Dashboard(ncpu)
        self.procs = ProcessView(ncpu, self.backend)
        self.tabs.addTab(self.dashboard, "Overview")
        self.tabs.addTab(self.procs, "Processes")
        self.setCentralWidget(self.tabs)

        self.procs.status.connect(self._flash)
        self.dashboard.root_requested.connect(self._open_root)
        self._build_statusbar()
        self._build_tray()
        self._restore()

        interval = float(self.settings.value("interval", 2.0))
        self.worker = SampleWorker(interval=interval)
        self.worker.sampled.connect(self._on_sample)
        self.worker.failed.connect(lambda m: self._flash(f"Sampling error: {m}"))
        self.thread = run_in_thread(self.worker)
        self._last_ts = 0.0

    # -- chrome -----------------------------------------------------------
    def _build_statusbar(self) -> None:
        sb = self.statusBar()
        self.lbl_msg = QLabel("")
        self.lbl_stats = QLabel("")
        self.lbl_stats.setFont(mono(8))
        self.lbl_stats.setStyleSheet(f"color: {theme.MUTED};")
        self.combo = QComboBox()
        for label, _ in INTERVALS:
            self.combo.addItem(label)
        saved = float(self.settings.value("interval", 2.0))
        self.combo.setCurrentIndex(
            next((i for i, (_, v) in enumerate(INTERVALS) if v == saved), 2)
        )
        self.combo.currentIndexChanged.connect(self._set_interval)
        spacer = QLabel("   ")
        lbl_interval = QLabel("Interval")
        lbl_interval.setStyleSheet(f"color: {theme.MUTED};")
        sb.addWidget(self.lbl_msg, 1)
        sb.addPermanentWidget(self.lbl_stats)
        sb.addPermanentWidget(spacer)
        sb.addPermanentWidget(lbl_interval)
        sb.addPermanentWidget(self.combo)

    def _build_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = None
            return
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        act_show = QAction("Show / hide", self)
        act_show.triggered.connect(self._toggle_window)
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(QApplication.quit)
        menu.addAction(act_show)
        menu.addSeparator()
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self._toggle_window()
            if reason == QSystemTrayIcon.ActivationReason.Trigger else None
        )
        self.tray.show()

    def _toggle_window(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.showNormal()
            self.raise_()
            self.activateWindow()

    # -- root ---------------------------------------------------------------
    def _open_root(self) -> None:
        if self.root_panel is None:
            from .rootpanel import RootPanel
            self.root_panel = RootPanel(self.root_client, self)
            self.root_panel.unlocked.connect(self._set_elevated)
        self.root_panel.show()
        self.root_panel.raise_()
        self.root_panel.activateWindow()

    def _set_elevated(self, on: bool) -> None:
        """Swaps the backend of the process list; the rest of the app is unaffected."""
        backend = ElevatedBackend(self.root_client) if on else get_backend()
        self.procs.set_backend(backend)
        self.dashboard.set_root_state(on)
        self._flash("Root actions enabled" if on else "Back to user privileges")

    # -- data -------------------------------------------------------------
    def _on_sample(self, snap: Snapshot) -> None:
        t0 = time.perf_counter()
        self.dashboard.update_view(snap)
        self.procs.update_view(snap)
        render_ms = (time.perf_counter() - t0) * 1000
        gpu = snap.system.gpu
        bits = [f"{snap.system.proc_count} processes", f"render {render_ms:.0f} ms"]
        if gpu is None:
            bits.append("no gpu")
        self.lbl_stats.setText("  ·  ".join(bits))

    def _flash(self, message: str, msec: int = 4000) -> None:
        self.lbl_msg.setText(message)
        QTimer.singleShot(msec, lambda: self.lbl_msg.setText(""))

    def _set_interval(self, index: int) -> None:
        seconds = INTERVALS[index][1]
        self.settings.setValue("interval", seconds)
        QTimer.singleShot(0, lambda: self.worker.set_interval(seconds))

    # -- window -----------------------------------------------------------
    def _restore(self) -> None:
        geo = self.settings.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        self.tabs.setCurrentIndex(int(self.settings.value("tab", 0)))

    def shutdown(self) -> None:
        """Idempotent: both closeEvent and aboutToQuit pass through here.

        Without this the sampler thread keeps running while the interpreter
        tears down, and that ends in a segfault on exit.
        """
        if getattr(self, "_stopped", False):
            return
        self._stopped = True
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("tab", self.tabs.currentIndex())
        self.worker.stop()
        self.thread.quit()
        self.thread.wait(3000)

    def closeEvent(self, event) -> None:
        self.shutdown()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("archpm")
    app.setDesktopFileName("archpm")
    theme.apply(app)
    win = MainWindow()
    app.aboutToQuit.connect(win.shutdown)
    win.show()
    win.statusBar().showMessage(f"Status for the widget: {status_path()}", 6000)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
