"""The Startup tab: what starts when you log in, and a switch for each."""
from __future__ import annotations

from functools import partial

from PySide6.QtCore import Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QCheckBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..actions import ActionError, UserBackend
from ..autostart import Autostart, StartupEntry, running_pids, tilde
from . import theme
from .widgets import BoxedList, ElidedLabel, FlowLayout, ListRow, Switch, app_icon, scrolling

KIND_ORDER = {"App": 0, "System": 1, "Desktop": 2}
KIND_LABEL = {"App": "App", "System": "System", "Desktop": "Desktop · keep on"}
ICON = 24
NARROW_ROW = 600    # px: under this a row shows no kind and source; the title keeps its room


class StartupView(QWidget):
    status = Signal(str)
    help_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.auto = Autostart()
        self.entries: list[StartupEntry] = []
        self._argvs: dict[int, list[str]] = {}
        self._loading = False
        self._status: list[QLabel] = []       # one per entry, the Running column

        outer = QVBoxLayout(self)
        outer.setContentsMargins(*theme.page_margins())
        outer.setSpacing(theme.CARD_GAP)

        head = FlowLayout(spacing=12)   # wraps when the window is narrow
        title = QLabel("What starts when you log in")
        title.setFont(theme.font("title", bold=True))
        head.addWidget(title)
        head.addStretch(1)
        self.cb_others = QCheckBox("Show entries for other desktops")
        self.cb_others.setToolTip("Entries that only run on GNOME, XFCE and so on. "
                                  "Listed for completeness; they do not run on yours.")
        self.cb_others.toggled.connect(lambda _: self.reload())
        head.addWidget(self.cb_others)
        btn = QPushButton("Refresh")
        btn.clicked.connect(self.reload)
        head.addWidget(btn)
        outer.addLayout(head)

        # Two groups in GNOME's shape, the page scrolling as a whole: the
        # autostart entries under the page's own title, with the note as the
        # group's description, and the session's services with their own.
        page = QWidget()
        groups = QVBoxLayout(page)
        groups.setContentsMargins(0, 0, 0, 0)
        groups.setSpacing(theme.GROUP_GAP)
        self.list = BoxedList("", (
            "Autostart entries: switch one off and it will not start at your next login. "
            "Nothing is closed now, nothing is deleted, and you can switch it back any time; "
            f"ArchPM only writes in your own folder ({tilde(self.auto.user_dir)}). Services "
            "of your session that start at login are listed further down.<br>"
            f"<span style='color:{theme.WARN}'>Rows marked <b>Desktop · keep on</b> are parts "
            "of your desktop itself (panels, shortcuts, password prompts, power management). "
            "Switching those off gives you a broken login, not a faster one.</span>"
        ))
        groups.addWidget(self.list)

        # -- enabled user services: they start at login as well ---------------
        self.svc_list = BoxedList("Services of your session that start at login", (
            "These are started by systemd, not from the autostart folder, so the list above "
            "does not show them; without them the picture would look complete while it is "
            "not. Switch one off with <code>systemctl --user disable</code> in a terminal, "
            "and start, stop or restart it under Root tasks."
        ))
        self.svc_hint = self.svc_list.description
        groups.addWidget(self.svc_list)
        groups.addStretch(1)
        outer.addWidget(scrolling(page), 1)

    # -- data -----------------------------------------------------------------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.reload()

    def reload(self) -> None:
        try:
            entries = self.auto.entries()
        except OSError as exc:
            self.status.emit(f"Startup: {exc}")
            return
        if not self.cb_others.isChecked():
            entries = [e for e in entries if e.for_this_desktop]
        # Your own apps first, the desktop's own parts last, so what you may
        # want to switch off is at the top and what you should leave alone is
        # grouped at the bottom.
        entries.sort(key=lambda e: (not e.for_this_desktop, KIND_ORDER.get(e.kind, 1),
                                    e.name.lower()))
        self.entries = entries
        self._fill()
        self._fill_services()

    def _fill_services(self) -> None:
        self.svc_list.clear()
        try:
            services = UserBackend().enabled_services()
        except ActionError as exc:
            self.svc_hint.setText(f"Could not read your session's services: {exc}")
            return
        for svc in services:
            state = QLabel("Running" if svc.active else "Not running")
            theme.text(state, "OK" if svc.active else "MUTED")
            row = ListRow(svc.unit, svc.description, suffix=[state])
            row.setToolTip(f"systemctl --user status {svc.unit}")
            self.svc_list.add_row(row)

    @staticmethod
    def _meta(e: StartupEntry) -> str:
        """Kind and source in one short line: 'App · User', 'System · User (override)'."""
        source = e.source + (" (override)" if e.is_override else "")
        return f"{KIND_LABEL.get(e.kind, e.kind)} · {source}"

    def _fill(self) -> None:
        self._loading = True
        self.list.clear()
        self._status = []
        # the status and the kind stand in columns: one width for each
        status_w = QFontMetrics(theme.font("body")).horizontalAdvance("Running · pid 9999999")
        small = QFontMetrics(theme.font("small"))
        meta_w = max((small.horizontalAdvance(self._meta(e)) for e in self.entries), default=0)
        for e in self.entries:
            icon = QLabel()
            icon.setFixedSize(ICON, ICON)      # the slot stays, so the titles line up
            pm = app_icon(e.icon).pixmap(ICON, ICON)
            if not pm.isNull():
                icon.setPixmap(pm)

            status = QLabel("")
            status.setMinimumWidth(status_w)
            meta = ElidedLabel(self._meta(e))
            meta.set_width_hint(meta_w)
            theme.style(meta, "color: {" + ("WARN" if e.essential else "MUTED")
                        + "}; font-size: {FONT_SMALL}pt;")
            meta.setToolTip(("Part of your desktop session. Leave it on. " if e.essential else "")
                            + ("Your own entry" if e.source == "User"
                               else "Installed with the system"))
            switch = Switch()
            switch.set_checked(e.enabled)
            switch.setToolTip("Starts at login" if e.enabled else "Switched off")
            switch.setAccessibleName(f"{e.name} starts at login")
            switch.toggled.connect(partial(self._toggled, e, switch))

            row = ListRow(e.name, e.description, prefix=icon, suffix=[status, meta, switch])
            row.setToolTip(f"{e.exec}\n{e.path}")
            row.set_collapsible(meta, NARROW_ROW)   # kind and source go first when narrow
            if not e.for_this_desktop:
                row.dim("FAINT")
            self.list.add_row(row)
            self._status.append(status)
        self._loading = False
        self._refresh_state()

    def update_view(self, snap) -> None:
        """Called every sample; only the Status column changes."""
        self._argvs = {p.pid: list(p.argv) for p in snap.procs if p.argv}
        if self.isVisible():
            self._refresh_state()

    def _refresh_state(self) -> None:
        running = running_pids(self.entries, self._argvs)
        for e, label in zip(self.entries, self._status, strict=False):
            if not e.for_this_desktop:
                text, colour = "Other desktop", "FAINT"
            elif e.id in running:
                text, colour = f"Running · pid {running[e.id]}", "OK"
            else:
                text, colour = "Not running", "MUTED"
            if label.text() != text:
                label.setText(text)
                theme.text(label, colour)

    # -- toggling -------------------------------------------------------------
    def _toggled(self, entry: StartupEntry, switch: Switch, enabled: bool) -> None:
        if self._loading:
            return
        if not enabled and entry.essential and not self._confirm_essential(entry):
            switch.set_checked(True)
            return
        try:
            self.auto.set_enabled(entry, enabled)
        except OSError as exc:
            self.status.emit(f"Could not change {entry.name}: {exc}")
            self.reload()
            return
        verb = "will start at login" if enabled else "will no longer start at login"
        self.status.emit(f"{entry.name} {verb}")
        self.reload()

    def _confirm_essential(self, entry: StartupEntry) -> bool:
        what = entry.description or entry.exec
        answer = QMessageBox.warning(
            self, "This is part of your desktop",
            f"<b>{entry.name}</b> is part of the desktop session itself.<br><br>"
            f"{what}<br><br>"
            "If it does not start, your next login may come up without panels, shortcuts, "
            "password prompts or power management. This is not a way to make the PC faster."
            "<br><br>Switch it off anyway?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes
