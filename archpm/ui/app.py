"""Main window: dashboard + processes, fed by a single sampler thread."""
from __future__ import annotations

import os
import signal
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
)

from .. import APP_NAME, __version__, failed, signalguard
from ..actions import ActionError, get_backend
from ..model import Snapshot
from ..publisher import status_path
from ..root.client import ElevatedBackend, RootClient
from . import theme
from .cleanup import CleanupView
from .dashboard import Dashboard
from .help import HelpView
from .history import ProcHistory
from .navrail import NavShell
from .network import NetworkView
from .procview import ProcessView
from .startup import StartupView
from .sysinfo import SystemView
from .widgets import mono
from .worker import SampleWorker, run_in_thread

INTERVALS = [("0.5 s", 0.5), ("1 s", 1.0), ("2 s", 2.0), ("5 s", 5.0)]

# One instance per user. A second launch connects to this socket, sends one
# request line, and exits. The socket is only reachable by the same user.
#
# The widgets use the same route: "Open ArchPM" is a plain launch, "End game"
# is a launch with --end-game. The widget itself signals nothing; the window
# asks, runs the signal guard and sends, exactly as from its own button.
INSTANCE_SOCKET = f"archpm-{os.getuid()}"
SHOW, END_GAME = "show", "end-game"
REQUESTS = (SHOW, END_GAME)


def parse_request(data: bytes) -> str | None:
    """The request in the first line from the socket: exactly one of REQUESTS,
    ended by a newline (a \\r before it is tolerated). Anything else, a word
    with something appended included, is None and does nothing."""
    line = data.split(b"\n", 1)[0].removesuffix(b"\r").decode("ascii", "replace")
    return line if line in REQUESTS else None


def raise_running_instance(request: str = SHOW, name: str = INSTANCE_SOCKET) -> bool:
    """True if another ArchPM is running for this user (and has been handed the request)."""
    sock = QLocalSocket()
    sock.connectToServer(name)
    if not sock.waitForConnected(300):
        return False
    sock.write(request.encode() + b"\n")
    sock.waitForBytesWritten(300)
    sock.disconnectFromServer()
    return True


def listen_for_launches(on_request, name: str = INSTANCE_SOCKET) -> QLocalServer:
    """Own the instance socket; call `on_request(word)` for every request that comes in."""
    QLocalServer.removeServer(name)  # stale file from a crash
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    server.newConnection.connect(lambda: _drain(server, on_request))
    server.listen(name)
    return server


def _drain(server: QLocalServer, on_request) -> None:
    while server.hasPendingConnections():
        conn = server.nextPendingConnection()
        conn.disconnected.connect(conn.deleteLater)

        def serve(conn=conn):
            if not conn.canReadLine():
                return
            request = parse_request(bytes(conn.readLine()))
            conn.close()
            if request is not None:
                on_request(request)

        conn.readyRead.connect(serve)
        serve()   # the line may be there already


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

        self.shell = NavShell(self.settings)
        self.worker_services = lambda port: (self.worker._sampler.net.service(port)
                                             if self.worker._sampler else "")
        self.history = ProcHistory()
        self.dashboard = Dashboard(ncpu, self.history)
        self.procs = ProcessView(ncpu, self.backend, self.history)
        self.startup = StartupView()
        self.system = SystemView()
        self.shell.add_page(self.dashboard, "Overview")
        self.shell.add_page(self.procs, "Processes")
        self.network = NetworkView(self.worker_services)
        self.shell.add_page(self.network, "Network")
        self.shell.add_page(self.startup, "Startup")
        self.shell.add_page(self.system, "System")
        self.cleanup = CleanupView(self.root_client)
        self.shell.add_page(self.cleanup, "Cleanup")
        self.cleanup.leave.connect(lambda: self.shell.set_current(0))
        self.cleanup.status.connect(self._flash)
        self.help = HelpView()
        self.shell.add_page(self.help, "Help")
        self.setCentralWidget(self.shell)
        for view in (self.dashboard, self.procs, self.network, self.startup, self.cleanup):
            view.help_requested.connect(self._show_help)

        self.procs.status.connect(self._flash)
        self.startup.status.connect(self._flash)
        self.system.status.connect(self._flash)
        self.dashboard.root_requested.connect(self._open_root)
        self.dashboard.failed_clicked.connect(lambda: self.shell.set_current(self.system))
        self.system.refresh_failed.connect(self.check_failed_services)
        self.dashboard.game.terminate_requested.connect(self._terminate_game)
        self._end_game_pending = False   # asked before the first sample; answered after it
        self._build_statusbar()
        self._build_tray()
        self._restore()
        if self.tray is not None and self.act_top.isChecked():
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        interval = float(self.settings.value("interval", 2.0))
        self.worker = SampleWorker(interval=interval)
        self.worker.sampled.connect(self._on_sample)
        self.worker.failed.connect(lambda m: self._flash(f"Sampling error: {m}"))
        self.worker.notice.connect(lambda m: self._flash(m, 10000))
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
        self.act_end_game = QAction("End game…", self)
        self.act_end_game.setVisible(False)
        self.act_end_game.triggered.connect(self.dashboard.game._confirm_terminate)
        menu.addAction(self.act_end_game)
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
        # Off by default. On: the window floats above everything, so you can
        # watch a measurement while a game or another program has the screen.
        self.act_top = QAction("Always keep on foreground", self)
        self.act_top.setCheckable(True)
        self.act_top.setChecked(self.settings.value("always_on_top", False, type=bool))
        self.act_top.toggled.connect(self._set_on_top)
        menu.addAction(self.act_top)
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

    def _set_on_top(self, on: bool) -> None:
        self.settings.setValue("always_on_top", on)
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        if visible:
            self.show()   # changing a window flag hides the window; bring it back
            self.raise_()

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

    def check_failed_services(self) -> None:
        """Once at start and on the System page's Refresh; read-only, nothing
        is started or stopped, and it is not on the sampling cycle."""
        report = failed.check()
        self.dashboard.set_failed(len(report.units))
        self.system.set_failed(report)

    def request(self, name: str) -> None:
        """A request from a second launch or from a widget; see REQUESTS."""
        self.present()
        if name == END_GAME:
            self.end_game()

    def end_game(self) -> None:
        """The same road as the button on the Overview card and the tray menu:
        the window asks, the signal guard checks, the active backend sends. The
        tree comes from the window's own sample, never from the status file."""
        if self.dashboard.game_name():
            self.dashboard.game._confirm_terminate()
        elif self.procs.model._last:
            self._flash("No game running")
        else:
            self._end_game_pending = True   # answered by the first sample

    # -- root ---------------------------------------------------------------
    def _open_root(self) -> None:
        if self.root_panel is None:
            from .rootpanel import RootPanel
            self.root_panel = RootPanel(self.root_client, self.backend, self)
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

    def _terminate_game(self, pids: list, name: str) -> None:
        """SIGTERM to the whole game tree, through whichever backend is active."""
        by_pid = {p.pid: p for p in self.procs.model._last}
        verdict = signalguard.check([by_pid[pid] for pid in pids if pid in by_pid],
                                    "TERM", tree=True)
        if verdict.refused:
            self._flash(verdict.refused)
            return
        done, failed = 0, 0
        for pid in pids:
            try:
                self.procs.backend.send_signal(pid, signal.SIGTERM)
                done += 1
            except ActionError:
                failed += 1
        self._flash(f"{name}: asked {done} process(es) to quit"
                    + (f", {failed} refused" if failed else ""))

    def _show_help(self, term: str) -> None:
        self.help.show_term(term)
        self.shell.set_current(self.help)

    # -- data -------------------------------------------------------------
    def _on_sample(self, snap: Snapshot) -> None:
        t0 = time.perf_counter()
        self.history.update(snap.procs)
        self.dashboard.update_view(snap)
        self.procs.update_view(snap)
        self.network.update_view(snap)
        self.startup.update_view(snap)
        self.cleanup.update_view(snap)
        render_ms = (time.perf_counter() - t0) * 1000
        gpu = snap.system.gpu
        bits = [f"{snap.system.proc_count} processes", f"Render {render_ms:.0f} ms"]
        if gpu is None:
            bits.append("No GPU")
        self.lbl_stats.setText("  ·  ".join(bits))
        if self.tray is not None:
            s = snap.system
            cpu_temp = f" · {s.cpu_temp_c:.0f}°" if s.cpu_temp_c else ""
            tip = [f"CPU {s.cpu_percent:.0f}%{cpu_temp}"]
            if gpu is not None:
                tip.append(f"GPU {gpu.util:.0f}% · {gpu.temp_c:.0f}° · VRAM "
                           f"{gpu.mem_used_mb / 1024:.1f} / {gpu.mem_total_mb / 1024:.0f} GB")
            tip.append(f"RAM {s.mem_used / 2**30:.1f} / {s.mem_total / 2**30:.0f} GB")
            if self.dashboard.game_name():
                tip.append(f"Game: {self.dashboard.game_name()}")
            self.tray.setToolTip("\n".join(t for t in tip if t))
            name = self.dashboard.game_name()
            self.act_game.setText(name or "No game running")
            self.act_end_game.setVisible(bool(name))
            self.act_end_game.setText(f"End {name}…" if name else "End game…")
        if self._end_game_pending:
            self._end_game_pending = False
            QTimer.singleShot(0, self.end_game)   # a modal inside the sample handler is fragile

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
        self.shell.set_current(0)  # always Overview; the page is a place, not a setting

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
    # --end-game: what the widget's button sends. Ask the running window, or
    # start one and ask it as soon as it knows what is running.
    request = END_GAME if "--end-game" in sys.argv[1:] else SHOW
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("archpm")
    app.setDesktopFileName("archpm")
    theme.apply(app)
    if raise_running_instance(request):
        return 0
    win = MainWindow()
    server = listen_for_launches(win.request)  # keep a reference for the app's lifetime
    app.aboutToQuit.connect(win.shutdown)
    app.aboutToQuit.connect(server.close)
    win.show()
    win.check_failed_services()
    win.statusBar().showMessage(f"Status for the widget: {status_path()}", 6000)
    if request == END_GAME:
        win.end_game()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
