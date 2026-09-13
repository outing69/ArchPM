"""Main window: dashboard + processes, fed by a single sampler thread."""
from __future__ import annotations

import os
import sys
import time

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QLabel,
    QMainWindow,
    QMenu,
    QSystemTrayIcon,
    QTabWidget,
)

from .. import APP_NAME, __version__
from ..actions import get_backend
from ..model import Snapshot
from ..publisher import status_path
from ..root.client import ElevatedBackend, RootClient
from . import theme
from .cleanup import CleanupView
from .dashboard import Dashboard
from .help import HelpView
from .history import ProcHistory
from .procview import ProcessView
from .startup import StartupView
from .sysinfo import SystemView
from .widgets import mono
from .worker import SampleWorker, run_in_thread

INTERVALS = [("0.5 s", 0.5), ("1 s", 1.0), ("2 s", 2.0), ("5 s", 5.0)]

# One instance per user. A second launch connects to this socket, asks the
# running instance to raise its window, and exits.
INSTANCE_SOCKET = f"archpm-{os.getuid()}"


def raise_running_instance() -> bool:
    """True if another ArchPM is running for this user (and has been told to show itself)."""
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_SOCKET)
    if not sock.waitForConnected(300):
        return False
    sock.write(b"show\n")
    sock.waitForBytesWritten(300)
    sock.disconnectFromServer()
    return True


def listen_for_launches(on_launch) -> QLocalServer:
    """Own the instance socket; call `on_launch` whenever a second launch knocks."""
    QLocalServer.removeServer(INSTANCE_SOCKET)  # stale file from a crash
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    server.newConnection.connect(lambda: _drain(server, on_launch))
    server.listen(INSTANCE_SOCKET)
    return server


def _drain(server: QLocalServer, on_launch) -> None:
    while server.hasPendingConnections():
        conn = server.nextPendingConnection()
        conn.disconnected.connect(conn.deleteLater)
        conn.close()
    on_launch()


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
        self.history = ProcHistory()
        self.dashboard = Dashboard(ncpu, self.history)
        self.procs = ProcessView(ncpu, self.backend, self.history)
        self.startup = StartupView()
        self.system = SystemView()
        self.tabs.addTab(self.dashboard, "Overview")
        self.tabs.addTab(self.procs, "Processes")
        self.tabs.addTab(self.startup, "Startup")
        self.tabs.addTab(self.system, "System")
        self.cleanup = CleanupView(self.root_client)
        self.tabs.addTab(self.cleanup, "Cleanup")
        self.cleanup.leave.connect(lambda: self.tabs.setCurrentIndex(0))
        self.cleanup.status.connect(self._flash)
        self.tabs.addTab(HelpView(), "Help")
        self.setCentralWidget(self.tabs)

        self.procs.status.connect(self._flash)
        self.startup.status.connect(self._flash)
        self.system.status.connect(self._flash)
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
        self.act_game = QAction("No game running", self)
        self.act_game.setEnabled(False)
        menu.addAction(self.act_game)
        menu.addSeparator()
        act_show = QAction("Show / hide", self)
        act_show.triggered.connect(self._toggle_window)
        menu.addAction(act_show)
        act_root = QAction("Root tasks…", self)
        act_root.triggered.connect(lambda: (self.present(), self._open_root()))
        menu.addAction(act_root)
        menu.addSeparator()
        # Off by default: closing the window quits, as it always did. On: the
        # window hides here and Quit is how you leave.
        self.act_keep = QAction("Keep running in background when closing", self)
        self.act_keep.setCheckable(True)
        self.act_keep.setChecked(self.settings.value("keep_running", False, type=bool))
        self.act_keep.toggled.connect(lambda on: self.settings.setValue("keep_running", on))
        menu.addAction(self.act_keep)
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(QApplication.quit)
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
            self.present()

    def present(self) -> None:
        """Bring the window to the front, un-minimising or un-hiding as needed."""
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
        self.history.update(snap.procs)
        self.dashboard.update_view(snap)
        self.procs.update_view(snap)
        self.startup.update_view(snap)
        self.cleanup.update_view(snap)
        render_ms = (time.perf_counter() - t0) * 1000
        gpu = snap.system.gpu
        bits = [f"{snap.system.proc_count} processes", f"render {render_ms:.0f} ms"]
        if gpu is None:
            bits.append("no gpu")
        self.lbl_stats.setText("  ·  ".join(bits))
        if self.tray is not None:
            s = snap.system
            cpu_temp = f" · {s.cpu_temp_c:.0f}°" if s.cpu_temp_c else ""
            tip = [f"CPU {s.cpu_percent:.0f}%{cpu_temp}"]
            if gpu is not None:
                tip.append(f"GPU {gpu.util:.0f}% · {gpu.temp_c:.0f}° · VRAM "
                           f"{gpu.mem_used_mb / 1024:.1f} / {gpu.mem_total_mb / 1024:.0f} G")
            tip.append(f"RAM {s.mem_used / 2**30:.1f} / {s.mem_total / 2**30:.0f} G")
            if self.dashboard.game_name():
                tip.append(f"Game: {self.dashboard.game_name()}")
            self.tray.setToolTip("\n".join(t for t in tip if t))
            self.act_game.setText(self.dashboard.game_name() or "No game running")

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
        self.tabs.setCurrentIndex(0)  # always Overview; the tab is a place, not a setting

    def shutdown(self) -> None:
        """Idempotent: both closeEvent and aboutToQuit pass through here.

        Without this the sampler thread keeps running while the interpreter
        tears down, and that ends in a segfault on exit.
        """
        if getattr(self, "_stopped", False):
            return
        self._stopped = True
        self.settings.setValue("geometry", self.saveGeometry())
        self.worker.stop()
        self.thread.quit()
        self.thread.wait(3000)
        # A scan or a spec gather may still run; a QThread destroyed while
        # running takes the process down with it.
        for view in (self.cleanup, self.system):
            t = getattr(view, "_thread", None)
            if t is not None and t.isRunning():
                t.wait(5000)

    def closeEvent(self, event) -> None:
        if self.tray is not None and self.act_keep.isChecked():
            # The user asked for it: keep sampling, hide here, quit from the tray.
            event.ignore()
            self.hide()
            self.tray.showMessage(APP_NAME, "Still running in the background. "
                                  "Quit from the tray icon's menu.",
                                  QSystemTrayIcon.MessageIcon.NoIcon, 3000)
            return
        self.shutdown()
        super().closeEvent(event)
        # With a tray icon present Qt does not treat this as the last window,
        # so the process would linger with a dead icon in the tray. Closing the
        # window means quitting; the tray icon is for show/hide while it runs.
        QApplication.quit()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("archpm")
    app.setDesktopFileName("archpm")
    theme.apply(app)
    if raise_running_instance():
        return 0
    win = MainWindow()
    server = listen_for_launches(win.present)  # keep a reference for the app's lifetime
    app.aboutToQuit.connect(win.shutdown)
    app.aboutToQuit.connect(server.close)
    win.show()
    win.statusBar().showMessage(f"Status for the widget: {status_path()}", 6000)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
