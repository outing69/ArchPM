"""Main window: dashboard + processes, fed by a single sampler thread."""
from __future__ import annotations

import os
import signal
import sys

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
from ..helptext import plural
from ..model import Snapshot
from ..root.client import ElevatedBackend, RootClient
from . import chrome, theme
from .chrome import HeaderBar, Toast
from .cleanup import CleanupView
from .dashboard import Dashboard
from .help import HelpView
from .history import ProcHistory
from .navrail import NavShell
from .network import NetworkView
from .procview import ProcessView
from .snapshots import SnapshotsView
from .startup import StartupView
from .sysinfo import SystemView
from .widgets import scrolling
from .worker import SampleWorker, run_in_thread, wait_for_threads

INTERVALS = [("0.5 s", 0.5), ("1 s", 1.0), ("2 s", 2.0), ("5 s", 5.0)]

# One instance per user. A second launch connects to this socket, sends one
# request line, and exits. The socket file is created for this user only,
# and it lives in the session's runtime directory ($XDG_RUNTIME_DIR, which
# only this user can enter), so no other user can take the name first: a
# squatted name would make every launch believe an ArchPM is running and
# exit. Without a runtime directory it falls back to a bare name, which Qt
# puts in the shared temporary directory.
#
# The widgets use the same route: "Open ArchPM" is a plain launch, "End game"
# is a launch with --end-game. The widget itself signals nothing; the window
# asks, runs the signal guard and sends, exactly as from its own button.
SHOW, END_GAME = "show", "end-game"
REQUESTS = (SHOW, END_GAME)


def instance_socket(env: dict[str, str] | None = None) -> str:
    """The socket's path in the runtime directory, or its bare name without one."""
    env = os.environ if env is None else env
    name = f"archpm-{os.getuid()}"
    runtime = env.get("XDG_RUNTIME_DIR", "")
    return os.path.join(runtime, name) if runtime else name


def parse_request(data: bytes) -> str | None:
    """The request in the first line from the socket: exactly one of REQUESTS,
    ended by a newline (a \\r before it is tolerated). Anything else, a word
    with something appended included, is None and does nothing."""
    line = data.split(b"\n", 1)[0].removesuffix(b"\r").decode("ascii", "replace")
    return line if line in REQUESTS else None


def raise_running_instance(request: str = SHOW, name: str | None = None) -> bool:
    """True if another ArchPM is running for this user (and has been handed the request)."""
    sock = QLocalSocket()
    sock.connectToServer(instance_socket() if name is None else name)
    if not sock.waitForConnected(300):
        return False
    sock.write(request.encode() + b"\n")
    sock.waitForBytesWritten(300)
    sock.disconnectFromServer()
    return True


def listen_for_launches(on_request, name: str | None = None) -> QLocalServer:
    """Own the instance socket; call `on_request(word)` for every request that
    comes in. When the socket cannot be taken the window still opens, as a
    second instance if need be, and says so on stderr: `isListening()` tells."""
    name = instance_socket() if name is None else name
    QLocalServer.removeServer(name)  # stale file from a crash
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    server.newConnection.connect(lambda: _drain(server, on_request))
    if not server.listen(name):
        print(f"archpm: not listening for launches on {name}: {server.errorString()}",
              file=sys.stderr)
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
        # A page that does not fit the window scrolls, with the bar in a
        # gutter beside it, instead of setting the window's minimum height
        # or clipping its content. The Overview was first (its tiles and
        # graphs would put the minimum above a 1080p screen with a panel);
        # Processes and Network follow, since their toolbar, cards and tree
        # stand in a column that a short window would otherwise squeeze. The
        # other pages scroll their body under a head of their own already.
        self.shell.add_page(scrolling(self.dashboard), "Overview")
        self.shell.add_page(scrolling(self.procs), "Processes")
        self.network = NetworkView(self.worker_services, self.root_client)
        self.shell.add_page(scrolling(self.network), "Network")
        self.shell.add_page(self.startup, "Startup")
        self.shell.add_page(self.system, "System")
        self.cleanup = CleanupView(self.root_client)
        self.shell.add_page(self.cleanup, "Cleanup")
        self.cleanup.leave.connect(lambda: self.shell.set_current(0))
        self.cleanup.status.connect(self._flash)
        self.snapshots = SnapshotsView(self.root_client)
        self.shell.add_page(self.snapshots, "Snapshots")
        self.snapshots.status.connect(self._flash)
        self.help = HelpView()
        self.shell.add_page(self.help, "Help")
        self.setCentralWidget(self.shell)
        for view in (self.dashboard, self.procs, self.network, self.startup, self.cleanup,
                     self.snapshots):
            view.help_requested.connect(self._show_help)

        self.procs.status.connect(self._flash)
        self.startup.status.connect(self._flash)
        self.system.status.connect(self._flash)
        self.dashboard.root_requested.connect(self._open_root)
        self.dashboard.process_requested.connect(self._show_process)
        self.dashboard.failed_clicked.connect(lambda: self.shell.set_current(self.system))
        theme.signals.changed.connect(self._retheme)
        self.system.refresh_failed.connect(self.check_failed_services)
        self.dashboard.game.terminate_requested.connect(self._terminate_game)
        self._end_game_pending = False   # asked before the first sample; answered after it
        self._build_header()
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
    def _build_header(self) -> None:
        """The header bar over the pages: the page's name as the title, the
        theme and the interval on the right. Transient messages go to a
        toast over the content; nothing else of the old status bar remains
        (the process count and the GPU are on the Overview)."""
        self.header = HeaderBar()
        self.combo = QComboBox()
        for label, _ in INTERVALS:
            self.combo.addItem(label)
        saved = float(self.settings.value("interval", 2.0))
        self.combo.setCurrentIndex(
            next((i for i, (_, v) in enumerate(INTERVALS) if v == saved), 2)
        )
        self.combo.currentIndexChanged.connect(self._set_interval)
        # Theme: follow the system, light, dark. Stored with the other
        # settings and applied at once; see theme.py.
        self.combo_theme = QComboBox()
        for label, pref in (("Follow system", "system"), ("Light", "light"), ("Dark", "dark")):
            self.combo_theme.addItem(label, pref)
        self.combo_theme.setCurrentIndex(max(self.combo_theme.findData(theme.preference()), 0))
        self.combo_theme.setToolTip(
            "Follow system: the desktop's light or dark preference, as Qt or the desktop "
            "portal reports it; dark when neither says. Light and Dark: always that."
        )
        self.combo_theme.currentIndexChanged.connect(
            lambda i: theme.set_preference(QApplication.instance(),
                                           self.combo_theme.itemData(i), self.settings))
        self.combo_theme.setAccessibleName("Theme")
        self.combo.setAccessibleName("Sampling interval")
        self.combo.setToolTip("How often the window samples the machine.")
        lbl_theme = QLabel("Theme")
        lbl_interval = QLabel("Interval")
        theme.style(lbl_interval, "color: {MUTED};")
        theme.style(lbl_theme, "color: {MUTED};")
        self.header.add_control(lbl_theme)
        self.header.add_control(self.combo_theme)
        self.header.add_gap()
        self.header.add_control(lbl_interval)
        self.header.add_control(self.combo)
        self.shell.set_header(self.header)
        self.shell.pages.currentChanged.connect(
            lambda i: self.header.set_title(self.shell.label_of(i)))
        self.header.set_title(self.shell.label_of(self.shell.current_index()))
        # Over the content column: a child of the shell, since the stack
        # raises each page it shows and would cover a child of its own.
        self.toast = Toast(self.shell, left=self.shell.placeholder.width)
        self.procs.offer.connect(self.toast.show_action)   # "still running": one button

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

    def _retheme(self, mode: str) -> None:
        """Rows that were painted with a colour at fill time are filled again;
        the rest reads the tokens at paint and only needed the repaint."""
        self.setWindowIcon(app_icon())
        if self.tray is not None:
            self.tray.setIcon(app_icon())
        i = self.combo_theme.findData(theme.preference())
        if i >= 0 and i != self.combo_theme.currentIndex():
            self.combo_theme.blockSignals(True)
            self.combo_theme.setCurrentIndex(i)
            self.combo_theme.blockSignals(False)
        if self.startup.isVisible():
            self.startup.reload()
        if self.system.sections:
            self.system._loaded(self.system.sections)
        if getattr(self.cleanup, "items", None):
            self.cleanup._scanned(self.cleanup.items)
        if self.snapshots.listing is not None:
            self.snapshots._fill()      # the origin icons are tinted per mode

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
        self._flash(f"{name}: asked {plural(done, 'process')} to quit"
                    + (f", {failed} refused" if failed else ""))
        self.procs.watch([by_pid[pid] for pid in pids if pid in by_pid], name)

    def _show_process(self, pid: int) -> None:
        """The verdict was clicked: Processes, with that row selected."""
        self.shell.set_current(self.procs)
        if not self.procs.show_pid(pid):
            self._flash("That process is gone.")

    def _show_help(self, term: str) -> None:
        self.help.show_term(term)
        self.shell.set_current(self.help)

    # -- data -------------------------------------------------------------
    def _on_sample(self, snap: Snapshot) -> None:
        self.history.update(snap.procs)
        self.dashboard.update_view(snap)
        self.procs.update_view(snap)
        self.network.update_view(snap)
        self.startup.update_view(snap)
        self.cleanup.update_view(snap)
        gpu = snap.system.gpu
        if self.tray is not None:
            s = snap.system
            cpu_temp = f" · {s.cpu_temp_c:.0f}°" if s.cpu_temp_c else ""
            tip = [f"CPU {s.cpu_percent:.0f}%{cpu_temp}"]
            if gpu is not None:
                tip.append(f"GPU {gpu.util:.0f}% · {gpu.temp_c:.0f}° · video memory "
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

    def _flash(self, message: str, msec: int = chrome.TOAST_MS) -> None:
        """A toast over the content, gone by itself after `msec`."""
        self.toast.show_message(message, msec)

    def _set_interval(self, index: int) -> None:
        seconds = INTERVALS[index][1]
        self.settings.setValue("interval", seconds)
        # The worker's timer lives on its thread; this hands the change over.
        self.worker.request_interval(seconds)

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
        self.worker.request_stop()     # on the worker's thread, like the timer
        self.thread.quit()
        self.thread.wait(3000)
        # A page's read may still run (a scan, a spec gather, a snapshot or
        # firewall read); a QThread destroyed while running takes the process
        # down with it. Every page thread is a child of its page, so the
        # object tree names them all, without a list here to keep up to date.
        wait_for_threads(self, 5000)

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
    chrome.install(app)    # overlay scrollbars; before the stylesheet goes on
    theme.start(app, QSettings("archpm", "ArchPM"))
    if raise_running_instance(request):
        return 0
    win = MainWindow()
    server = listen_for_launches(win.request)  # keep a reference for the app's lifetime
    app.aboutToQuit.connect(win.shutdown)
    app.aboutToQuit.connect(server.close)
    win.show()
    win.check_failed_services()
    if request == END_GAME:
        win.end_game()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
