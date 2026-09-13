"""The root panel: everything that does require privileges, in one visible place.

Deliberately limited to process management, services and memory. GPU tuning
(power limit, clock cap) used to be here but does not belong in a process
manager.

It is a separate window. In the rest of the app you cannot break anything; here
each button states which command runs via pkexec, and what its effect is.
"""
from __future__ import annotations

from PySide6.QtCore import QProcess, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..actions import ActionError
from ..root.client import HELPER, RootClient, check
from . import theme
from .widgets import mono


class RootPanel(QDialog):
    unlocked = Signal(bool)

    def __init__(self, client: RootClient, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.setWindowTitle("Root tasks")
        self.setMinimumWidth(560)
        self.resize(600, 540)
        self._proc: QProcess | None = None
        self._pending: tuple[str, ...] = ()
        self._on_done = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(12)

        lay.addWidget(self._header())
        lay.addWidget(self._proc_group())
        lay.addWidget(self._system_group())

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(120)
        self.log.setFont(mono(8))
        self.log.setStyleSheet(
            f"QPlainTextEdit {{ background: {theme.SURFACE}; border: 1px solid {theme.BORDER};"
            f" border-radius: 8px; color: {theme.MUTED}; padding: 6px; }}"
        )
        lay.addWidget(self.log)
        lay.addStretch(1)

        self._refresh_state()
        self._load_status()
        self._load_services()

    # -- layout ------------------------------------------------------------
    def _header(self) -> QWidget:
        box = QGroupBox("access")
        row = QHBoxLayout(box)
        row.setSpacing(12)
        self.lbl_lock = QLabel()
        self.lbl_lock.setWordWrap(True)
        row.addWidget(self.lbl_lock, 1)
        self.btn_unlock = QPushButton("Unlock")
        self.btn_unlock.setObjectName("accent")
        self.btn_unlock.clicked.connect(self._unlock)
        row.addWidget(self.btn_unlock)
        return box

    def _proc_group(self) -> QWidget:
        box = QGroupBox("processes")
        lay = QVBoxLayout(box)
        self.cb_elevated = QCheckBox("Enable root actions in the process list")
        self.cb_elevated.setToolTip(
            "Enables negative nice, realtime IO priority and actions on other "
            "users' processes."
        )
        self.cb_elevated.toggled.connect(self.unlocked.emit)
        lay.addWidget(self.cb_elevated)
        lay.addWidget(self._hint(
            "Without root you can only raise nice (less priority). "
            "With root you can put a game on nice -10 and push background tasks "
            "out of the way."
        ))
        return box

    def _system_group(self) -> QWidget:
        box = QGroupBox("services and memory")
        grid = QGridLayout(box)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)

        grid.addWidget(QLabel("Service"), 0, 0)
        self.combo_service = QComboBox()
        self.combo_service.setEditable(True)
        self.combo_service.setMinimumWidth(220)
        grid.addWidget(self.combo_service, 0, 1)
        btns = QHBoxLayout()
        for label, action in (("Stop", "stop"), ("Start", "start"), ("Restart", "restart")):
            b = QPushButton(label)
            b.clicked.connect(
                lambda _=False, a=action: self._run(
                    "service", a, self.combo_service.currentText().strip(),
                    then=self._load_services,
                )
            )
            btns.addWidget(b)
            self._service_buttons = getattr(self, "_service_buttons", [])
            self._service_buttons.append(b)
        grid.addLayout(btns, 0, 2)

        grid.addWidget(QLabel("Swappiness"), 1, 0)
        self.spin_swap = QSpinBox()
        self.spin_swap.setRange(0, 200)
        self.spin_swap.setToolTip(
            "How eagerly the kernel resorts to swap. CachyOS sets this high because "
            "zram is fast; lower keeps more in RAM."
        )
        grid.addWidget(self.spin_swap, 1, 1, Qt.AlignmentFlag.AlignLeft)
        self.btn_swap = QPushButton("Apply")
        self.btn_swap.clicked.connect(
            lambda: self._run("swappiness", str(self.spin_swap.value()), then=self._load_status)
        )
        grid.addWidget(self.btn_swap, 1, 2, Qt.AlignmentFlag.AlignLeft)

        self.btn_caches = QPushButton("Drop caches")
        self.btn_caches.setToolTip("sync + drop_caches 3 — frees the page cache.")
        self.btn_caches.clicked.connect(lambda: self._run("drop-caches", "3"))
        grid.addWidget(self.btn_caches, 2, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)
        return box

    @staticmethod
    def _hint(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {theme.FAINT};")
        f = lbl.font()
        f.setPointSize(8)
        lbl.setFont(f)
        return lbl

    # -- status ------------------------------------------------------------
    def _refresh_state(self) -> None:
        st = check()
        ready = st.ready
        if not ready:
            self.lbl_lock.setText(
                f"<b style='color:{theme.CRIT}'>Not available</b><br>"
                f"<span style='color:{theme.MUTED}'>{st.problem}<br>"
                f"Run <code>./install.sh --root</code>.</span>"
            )
        elif self.client.authenticated:
            self.lbl_lock.setText(
                f"<b style='color:{theme.OK}'>Unlocked</b><br>"
                f"<span style='color:{theme.MUTED}'>Polkit remembers your password "
                f"for about five minutes.</span>"
            )
        else:
            self.lbl_lock.setText(
                f"<b style='color:{theme.ACCENT}'>Locked</b><br>"
                f"<span style='color:{theme.MUTED}'>Every action runs through "
                f"<code>pkexec {HELPER.name}</code>.</span>"
            )
        self.btn_unlock.setEnabled(ready and not self.client.authenticated)
        self.btn_unlock.setText("Unlocked" if self.client.authenticated else "Unlock")
        self.cb_elevated.setEnabled(ready)
        for w in (self.btn_swap, self.btn_caches,
                  *getattr(self, "_service_buttons", [])):
            w.setEnabled(ready)

    def _load_status(self) -> None:
        try:
            st = self.client.status()
        except ActionError as exc:
            self._say(f"status: {exc}")
            return
        if "swappiness" in st:
            self.spin_swap.setValue(int(st["swappiness"]))

    def _load_services(self) -> None:
        proc = QProcess(self)
        proc.finished.connect(lambda *_: self._services_loaded(proc))
        proc.start("systemctl", ["list-units", "--type=service", "--state=running",
                                 "--no-legend", "--plain", "--no-pager"])

    def _services_loaded(self, proc: QProcess) -> None:
        text = bytes(proc.readAllStandardOutput()).decode(errors="replace")
        units = [line.split()[0] for line in text.splitlines() if line.strip()]
        current = self.combo_service.currentText()
        self.combo_service.clear()
        self.combo_service.addItems(units)
        if current:
            self.combo_service.setCurrentText(current)

    # -- execution ---------------------------------------------------------
    def _unlock(self) -> None:
        self._run("status", then=lambda: (self._refresh_state(), self._load_status()))

    def _run(self, *args: str, then=None) -> None:
        """Asynchronous via QProcess: the polkit dialog must not block the UI."""
        if self._proc is not None:
            self._say("An action is already running.")
            return
        st = check()
        if not st.ready:
            self._say(st.problem)
            return
        argv = self.client.argv(*args)
        self._say(f"$ {' '.join(argv)}")
        self._pending = args
        self._on_done = then
        self._proc = QProcess(self)
        self._proc.finished.connect(self._finished)
        self._proc.errorOccurred.connect(lambda _: self._finished(-1))
        self.setEnabled(False)
        self._proc.start(argv[0], argv[1:])

    def _finished(self, code: int = -1, *_) -> None:
        proc, self._proc = self._proc, None
        self.setEnabled(True)
        if proc is None:
            return
        out = bytes(proc.readAllStandardOutput()).decode(errors="replace")
        err = bytes(proc.readAllStandardError()).decode(errors="replace")
        try:
            result = self.client.parse(proc.exitCode() if code != -1 else code, out, err)
        except ActionError as exc:
            self._say(f"  ✗ {exc}")
            self._refresh_state()
            return
        self._say(f"  ✓ {result if result else 'ok'}")
        self._refresh_state()
        if self._on_done:
            fn, self._on_done = self._on_done, None
            fn()

    def _say(self, text: str) -> None:
        self.log.appendPlainText(text)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    @property
    def elevated_enabled(self) -> bool:
        return self.cb_elevated.isChecked()
