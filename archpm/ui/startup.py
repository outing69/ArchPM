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
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..autostart import Autostart, StartupEntry, running_pids
from . import theme
from .widgets import app_icon, mono

COL_ON, COL_NAME, COL_STATE, COL_SOURCE, COL_CATEGORY, COL_CMD = range(6)
HEADERS = ["", "Name", "Status", "Source", "Category", "Command"]


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
            "Untick an entry and it will not start at your next login. Nothing is closed "
            "now, nothing is deleted, and you can tick it back any time. ArchPM only writes "
            f"in your own folder ({self.auto.user_dir})."
        )
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
        header.setSectionResizeMode(COL_CMD, QHeaderView.ResizeMode.Stretch)
        header.setHighlightSections(False)
        for col, w in ((COL_ON, 36), (COL_NAME, 260), (COL_STATE, 170), (COL_SOURCE, 80),
                       (COL_CATEGORY, 110)):
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
        entries.sort(key=lambda e: (not e.for_this_desktop, e.name.lower()))
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
            name.setToolTip(str(e.path))
            self.table.setItem(row, COL_NAME, name)

            self.table.setItem(row, COL_STATE, QTableWidgetItem(""))
            src = QTableWidgetItem(e.source + (" (override)" if e.is_override else ""))
            src.setToolTip("Your own entry" if e.source == "User" else "Installed with the system")
            self.table.setItem(row, COL_SOURCE, src)
            self.table.setItem(row, COL_CATEGORY, QTableWidgetItem(e.category))
            cmd = QTableWidgetItem(e.exec)
            cmd.setFont(mono(9))
            cmd.setToolTip(e.exec)
            self.table.setItem(row, COL_CMD, cmd)
            for col in (COL_SOURCE, COL_CATEGORY, COL_CMD):
                self.table.item(row, col).setForeground(QColor(theme.MUTED))
            if not e.for_this_desktop:
                for col in range(len(HEADERS)):
                    self.table.item(row, col).setForeground(QColor(theme.FAINT))
        self._loading = False
        self._refresh_state()

    def update_view(self, snap) -> None:
        """Called every sample; only the Running column changes."""
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
        try:
            self.auto.set_enabled(entry, enabled)
        except OSError as exc:
            self.status.emit(f"Could not change {entry.name}: {exc}")
            self.reload()
            return
        verb = "will start at login" if enabled else "will no longer start at login"
        self.status.emit(f"{entry.name} {verb}")
        self.reload()
