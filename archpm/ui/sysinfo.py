"""The System page: the machine's specs as a reading card, with Copy."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import sysinfo
from ..failed import SESSION, FailedReport
from . import theme
from .widgets import BoxedList, Columns, FlowLayout, ListRow, scrolling


class _Gather(QThread):
    """nvidia-smi and disk stats can take a moment; keep the UI thread free."""
    done = Signal(object)

    def run(self) -> None:
        self.done.emit(sysinfo.gather())


class SystemView(QWidget):
    status = Signal(str)
    refresh_failed = Signal()    # the Refresh button on the failed-services block

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.sections: list[sysinfo.Section] = []
        self._thread: _Gather | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(*theme.page_margins())
        outer.setSpacing(theme.CARD_GAP)

        head = FlowLayout(spacing=12)   # wraps when the window is narrow
        title = QLabel("This machine")
        title.setFont(theme.font("title", bold=True))
        head.addWidget(title)
        self.lbl_state = QLabel("")
        theme.style(self.lbl_state, "color: {MUTED};")
        head.addWidget(self.lbl_state)
        head.addStretch(1)
        self.btn_copy = QPushButton("Copy as text")
        self.btn_copy.setToolTip("Puts all of this on the clipboard, "
                                 "ready for a forum post or bug report.")
        self.btn_copy.clicked.connect(self._copy)
        head.addWidget(self.btn_copy)
        btn = QPushButton("Refresh")
        btn.clicked.connect(self.reload)
        head.addWidget(btn)
        outer.addLayout(head)

        # -- failed services, above the specs: a snapshot, read-only ---------
        # The whole page scrolls: this group, then the spec groups, in two
        # columns when the window is wide enough for them.
        page = QWidget()
        groups = QVBoxLayout(page)
        groups.setContentsMargins(0, 0, 0, 0)
        groups.setSpacing(theme.GROUP_GAP)
        self.failed_list = BoxedList("Failed services", "not checked yet")
        self.lbl_failed_state = self.failed_list.description
        # Named for what it refreshes: the page's own Refresh, next to it,
        # rereads the machine's specs and does not touch this block.
        self.btn_failed = QPushButton("Refresh failed services")
        self.btn_failed.setToolTip("Asks systemctl --failed and systemctl --user --failed again. "
                                   "This is the only other time the check runs; it is not on a "
                                   "timer. The page's Refresh above rereads the machine's specs.")
        self.btn_failed.clicked.connect(self.refresh_failed.emit)
        self.failed_list.set_suffix(self.btn_failed)
        groups.addWidget(self.failed_list)
        self.columns = Columns(theme.GROUP_GAP)
        groups.addWidget(self.columns)
        groups.addStretch(1)
        outer.addWidget(scrolling(page), 1)

    def set_failed(self, report: FailedReport) -> None:
        """One row per failed unit with its last log lines; one row when none."""
        self.failed_list.clear()
        when = time.strftime("%H:%M:%S", time.localtime(report.taken_at))
        self.lbl_failed_state.setText(
            f"checked at {when} in {report.took_ms:.0f} ms" + (f"  ·  {report.error}"
                                                              if report.error else ""))
        if not report.units:
            row = ListRow("No failed services")
            row.dim("MUTED")
            self.failed_list.add_row(row)
            return
        for u in report.units:
            scope = "service of your session" if u.scope == SESSION else "system service"
            since = f"  ·  failed since {u.since}" if u.since else ""
            row = ListRow(u.title, f"{u.unit}  ·  {scope}{since}")
            body = QLabel("\n".join(u.log) if u.log else u.note)
            body.setWordWrap(True)
            theme.style(body, "color: {" + ("MUTED" if u.log else "WARN") + "}; margin-top: 4px;"
                        " font-family: monospace; font-size: {FONT_SMALL}pt;")
            body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row.add_body(body)
            self.failed_list.add_row(row)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self.sections and self._thread is None:
            self.reload()

    def reload(self) -> None:
        if self._thread is not None:
            return
        self.lbl_state.setText("reading…")
        self._thread = _Gather(self)
        self._thread.done.connect(self._loaded)
        self._thread.finished.connect(self._thread_finished)
        self._thread.start()

    @Slot()
    def _thread_finished(self) -> None:
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None

    @Slot(object)
    def _loaded(self, sections) -> None:
        self.sections = sections
        self.lbl_state.setText("")
        groups = []
        for title, rows in sections:
            group = BoxedList(title)
            for k, v in rows:
                group.add_row(ListRow(k, v, property=True, mono=True))
            groups.append((group, len(rows) + 1))
        self.columns.set_groups(groups)

    def _copy(self) -> None:
        if not self.sections:
            return
        QGuiApplication.clipboard().setText(sysinfo.as_text(self.sections))
        self.status.emit("System information copied to the clipboard")
