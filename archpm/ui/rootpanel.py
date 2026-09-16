"""The root panel: everything that does require privileges, in one visible place.

Deliberately limited to process management and memory. GPU tuning (power
limit, clock cap) used to be here but does not belong in a process manager.
Your own session's services live here too, but they run as you through
`systemctl --user`: no pkexec, no password, and never the root helper. System
services are not managed by ArchPM.

It is a separate window. In the rest of the app you cannot break anything; here
each button states which command runs, and what its effect is.
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

from ..actions import ActionError, UserBackend
from ..root.client import HELPER, RootClient, check
from . import theme
from .widgets import mono


class RootPanel(QDialog):
    unlocked = Signal(bool)

    def __init__(self, client: RootClient, backend: UserBackend, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.backend = backend
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
        lay.addWidget(self._service_group())
        lay.addWidget(self._system_group())

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(120)
        self.log.setFont(mono(8))
        theme.style(
            self.log, "QPlainTextEdit {{ background: {SURFACE}; border: 1px solid {BORDER};"
            " border-radius: 8px; color: {MUTED}; padding: 6px; }}"
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

    def _service_group(self) -> QWidget:
        box = QGroupBox("your session's services (no root needed)")
        lay = QVBoxLayout(box)
        row = QHBoxLayout()
        row.addWidget(QLabel("Service"))
        self.combo_service = QComboBox()
        self.combo_service.setEditable(True)
        self.combo_service.setMinimumWidth(220)
        self.combo_service.setToolTip(
            "Services of your own login session (systemctl --user). "
            "System services are not managed by ArchPM."
        )
        row.addWidget(self.combo_service, 1)
        for label, action in (("Stop", "stop"), ("Start", "start"), ("Restart", "restart")):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, a=action: self._run_service(a))
            row.addWidget(b)
        lay.addLayout(row)
        lay.addWidget(self._hint(
            "These run as you, so no password is asked. The ones your desktop itself "
            "runs on (plasmashell, kwin, ksmserver, the session bus, pipewire, wireplumber, "
            "the desktop portal) cannot be stopped from here, only restarted."
        ))
        return box

    def _system_group(self) -> QWidget:
        box = QGroupBox("memory")
        grid = QGridLayout(box)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)

        grid.addWidget(QLabel("Swappiness"), 0, 0)
        self.spin_swap = QSpinBox()
        self.spin_swap.setRange(0, 200)
        self.spin_swap.setToolTip(
            "How eagerly the kernel resorts to swap. CachyOS sets this high because "
            "zram is fast; lower keeps more in RAM.\n"
            "Applies now and lasts until the next restart, when the system's own "
            "setting comes back."
        )
        grid.addWidget(self.spin_swap, 0, 1, Qt.AlignmentFlag.AlignLeft)
        self.btn_swap = QPushButton("Apply")
        self.btn_swap.clicked.connect(
            lambda: self._run("swappiness", str(self.spin_swap.value()), then=self._load_status)
        )
        grid.addWidget(self.btn_swap, 0, 2, Qt.AlignmentFlag.AlignLeft)

        self.btn_caches = QPushButton("Drop caches")
        self.btn_caches.setToolTip(
            "sync + drop_caches 3: asks the kernel to forget the files it kept in RAM for "
            "speed.\nThe memory shows as free, but the kernel would have freed it itself "
            "the moment a program needed it, and everything is read from disk again "
            "afterwards, so the system is slower for a moment. Rarely helps."
        )
        self.btn_caches.clicked.connect(lambda: self._run("drop-caches", "3"))
        grid.addWidget(self.btn_caches, 1, 0, 1, 2, Qt.AlignmentFlag.AlignLeft)
        return box

    @staticmethod
    def _hint(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        theme.style(lbl, "color: {FAINT};")
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
                f"<span style='color:{theme.MUTED}'>Every root action runs through "
                f"<code>pkexec {HELPER.name}</code>.</span>"
            )
        self.btn_unlock.setEnabled(ready and not self.client.authenticated)
        self.btn_unlock.setText("Unlocked" if self.client.authenticated else "Unlock")
        self.cb_elevated.setEnabled(ready)
        for w in (self.btn_swap, self.btn_caches):
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
        try:
            units = self.backend.list_services()
        except ActionError as exc:
            self._say(f"services: {exc}")
            return
        current = self.chosen_unit()
        self.combo_service.clear()
        for svc in sorted(units, key=lambda s: s.label.lower()):
            self.combo_service.addItem(svc.label, svc.unit)
        if current:
            index = self.combo_service.findData(current)
            if index >= 0:
                self.combo_service.setCurrentIndex(index)
            else:
                self.combo_service.setCurrentText(current)

    def chosen_unit(self) -> str:
        """The unit behind the chosen entry, or what was typed in the box."""
        combo = self.combo_service
        i = combo.currentIndex()
        if i >= 0 and combo.currentText() == combo.itemText(i):
            return combo.itemData(i) or ""
        return combo.currentText().strip()

    # -- execution ---------------------------------------------------------
    def _run_service(self, action: str) -> None:
        """Your own session's services: systemctl --user as you, asynchronous, never pkexec."""
        if self._proc is not None:
            self._say("An action is already running.")
            return
        try:
            argv = self.backend.service_argv(action, self.chosen_unit())
        except ActionError as exc:
            self._say(f"  ✗ {exc}")
            return
        unit = argv[-1]
        self._say(f"$ {' '.join(argv)}")
        self._proc = QProcess(self)
        self._proc.finished.connect(lambda *_: self._service_finished(unit, action))
        self._proc.errorOccurred.connect(
            lambda _: self._service_finished(unit, action, failed=True))
        self.setEnabled(False)
        self._proc.start(argv[0], argv[1:])

    def _service_finished(self, unit: str, action: str, failed: bool = False) -> None:
        proc, self._proc = self._proc, None
        self.setEnabled(True)
        if proc is None:
            return
        err = bytes(proc.readAllStandardError()).decode(errors="replace").strip().splitlines()
        if failed or proc.exitCode() != 0:
            self._say(f"  ✗ {err[-1] if err else f'systemctl {action} {unit} failed'}")
        else:
            self._say(f"  ✓ {unit}: {action} done")
        self._load_services()

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
