"""The Startup tab: what starts when you log in, and a switch for each."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..autostart import Autostart, StartupEntry, running_pids
from . import theme
from .widgets import app_icon

COL_ON, COL_NAME, COL_DESC, COL_STATE, COL_KIND, COL_SOURCE = range(6)
HEADERS = ["", "Name", "What it does", "Status", "Kind", "Source"]
KIND_ORDER = {"App": 0, "System": 1, "Desktop": 2}
KIND_LABEL = {"App": "App", "System": "System", "Desktop": "Desktop · keep on"}


class StartupView(QWidget):
    status = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.auto = Autostart()
        self.entries: list[StartupEntry] = []
        self._argvs: dict[int, list[str]] = {}
        self._loading = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 12)
        outer.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(12)
        title = QLabel("What starts when you log in")
        f = title.font()
        f.setPointSize(11)
        f.setBold(True)
        title.setFont(f)
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

        hint = QLabel(
            "Untick an entry and it will not start at your next login. Nothing is closed now, "
            "nothing is deleted, and you can tick it back any time; ArchPM only writes in your "
            f"own folder ({self.auto.user_dir}).<br>"
            f"<span style='color:{theme.WARN}'>Rows marked <b>Desktop · keep on</b> are parts of "
            "your desktop itself (panels, shortcuts, password prompts, power management). "
            "Switching those off gives you a broken login, not a faster one.</span>"
        )
        hint.setTextFormat(Qt.TextFormat.RichText)
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.MUTED};")
        outer.addWidget(hint)

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(26)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(COL_DESC, QHeaderView.ResizeMode.Stretch)
        header.setHighlightSections(False)
        for col, w in ((COL_ON, 36), (COL_NAME, 250), (COL_STATE, 170), (COL_KIND, 140),
                       (COL_SOURCE, 120)):
            self.table.setColumnWidth(col, w)
        self.table.itemChanged.connect(self._toggled)
        outer.addWidget(self.table, 1)

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

    def _fill(self) -> None:
        self._loading = True
        self.table.setRowCount(len(self.entries))
        for row, e in enumerate(self.entries):
            on = QTableWidgetItem()
            on.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                        | Qt.ItemFlag.ItemIsSelectable)
            on.setCheckState(Qt.CheckState.Checked if e.enabled else Qt.CheckState.Unchecked)
            on.setToolTip("Starts at login" if e.enabled else "Switched off")
            self.table.setItem(row, COL_ON, on)

            name = QTableWidgetItem(e.name)
            icon = app_icon(e.icon)
            if not icon.isNull():
                name.setIcon(icon)
            name.setToolTip(f"{e.exec}\n{e.path}")
            self.table.setItem(row, COL_NAME, name)

            desc = QTableWidgetItem(e.description)
            desc.setToolTip(e.exec)
            self.table.setItem(row, COL_DESC, desc)

            self.table.setItem(row, COL_STATE, QTableWidgetItem(""))

            kind = QTableWidgetItem(KIND_LABEL.get(e.kind, e.kind))
            if e.essential:
                kind.setForeground(QColor(theme.WARN))
                kind.setToolTip("Part of your desktop session. Leave it on.")
            self.table.setItem(row, COL_KIND, kind)

            src = QTableWidgetItem(e.source + (" (override)" if e.is_override else ""))
            src.setToolTip("Your own entry" if e.source == "User" else "Installed with the system")
            self.table.setItem(row, COL_SOURCE, src)

            for col in (COL_DESC, COL_SOURCE):
                self.table.item(row, col).setForeground(QColor(theme.MUTED))
            if not e.for_this_desktop:
                for col in range(len(HEADERS)):
                    self.table.item(row, col).setForeground(QColor(theme.FAINT))
        self._loading = False
        self._refresh_state()

    def update_view(self, snap) -> None:
        """Called every sample; only the Status column changes."""
        self._argvs = {p.pid: p.cmdline.split() for p in snap.procs if p.cmdline}
        if self.isVisible():
            self._refresh_state()

    def _refresh_state(self) -> None:
        running = running_pids(self.entries, self._argvs)
        for row, e in enumerate(self.entries):
            item = self.table.item(row, COL_STATE)
            if item is None:
                continue
            if not e.for_this_desktop:
                item.setText("Other desktop")
                item.setForeground(QColor(theme.FAINT))
            elif e.id in running:
                item.setText(f"Running · pid {running[e.id]}")
                item.setForeground(QColor(theme.OK))
            else:
                item.setText("Not running")
                item.setForeground(QColor(theme.MUTED))

    # -- toggling -------------------------------------------------------------
    def _toggled(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() != COL_ON:
            return
        entry = self.entries[item.row()]
        enabled = item.checkState() == Qt.CheckState.Checked
        if not enabled and entry.essential and not self._confirm_essential(entry):
            self._loading = True
            item.setCheckState(Qt.CheckState.Checked)
            self._loading = False
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
