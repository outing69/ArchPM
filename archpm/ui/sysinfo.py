"""The System tab: the machine's specs as a reading card, with Copy."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import sysinfo
from ..failed import SESSION, FailedReport
from . import theme
from .widgets import Card, mono


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
        outer.setContentsMargins(12, 10, 12, 12)
        outer.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(12)
        title = QLabel("This machine")
        f = title.font()
        f.setPointSize(11)
        f.setBold(True)
        title.setFont(f)
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

        # -- failed services, above the cards: a snapshot, read-only ---------
        self.failed_card = Card("Failed services")
        self.failed_body = QVBoxLayout()
        self.failed_body.setSpacing(6)
        frow = QHBoxLayout()
        self.lbl_failed_state = QLabel("not checked yet")
        theme.style(self.lbl_failed_state, "color: {MUTED};")
        frow.addWidget(self.lbl_failed_state, 1)
        # Named for what it refreshes: the page's own Refresh, next to it,
        # rereads the machine's specs and does not touch this block.
        self.btn_failed = QPushButton("Refresh failed services")
        self.btn_failed.setToolTip("Asks systemctl --failed and systemctl --user --failed again. "
                                   "This is the only other time the check runs; it is not on a "
                                   "timer. The page's Refresh above rereads the machine's specs.")
        self.btn_failed.clicked.connect(self.refresh_failed.emit)
        frow.addWidget(self.btn_failed)
        self.failed_card.body.addLayout(frow)
        self.failed_card.body.addLayout(self.failed_body)
        outer.addWidget(self.failed_card)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.body = QWidget()
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 0, 0)
        self.body_lay.setSpacing(10)
        self.body_lay.addStretch(1)
        self.scroll.setWidget(self.body)
        outer.addWidget(self.scroll, 1)

    def set_failed(self, report: FailedReport) -> None:
        """One row per failed unit with its last log lines; one line when none."""
        while self.failed_body.count():
            item = self.failed_body.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        when = time.strftime("%H:%M:%S", time.localtime(report.taken_at))
        self.lbl_failed_state.setText(
            f"checked at {when} in {report.took_ms:.0f} ms" + (f"  ·  {report.error}"
                                                              if report.error else ""))
        if not report.units:
            line = QLabel("No failed services found.")
            theme.style(line, "color: {MUTED};")
            self.failed_body.addWidget(line)
            return
        for u in report.units:
            scope = "service of your session" if u.scope == SESSION else "system service"
            since = f"  ·  failed since {u.since}" if u.since else ""
            head = QLabel(f"<b>{u.title}</b>&nbsp;&nbsp;<span style='color:{theme.MUTED}; "
                          f"font-size: 8.5pt'>{u.unit}</span><br>"
                          f"<span style='color:{theme.MUTED}'>{scope}{since}</span>")
            head.setTextFormat(Qt.TextFormat.RichText)
            head.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.failed_body.addWidget(head)
            body = QLabel("\n".join(u.log) if u.log else u.note)
            body.setFont(mono(8.5))
            body.setWordWrap(True)
            theme.style(body,
                        "color: {" + ("MUTED" if u.log else "WARN") + "}; padding-left: 12px;")
            body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.failed_body.addWidget(body)

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
        while self.body_lay.count() > 1:  # keep the trailing stretch
            item = self.body_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for title, rows in sections:
            card = Card(title)
            grid = QGridLayout()
            grid.setHorizontalSpacing(18)
            grid.setVerticalSpacing(4)
            grid.setColumnStretch(1, 1)
            for r, (k, v) in enumerate(rows):
                key = QLabel(k)
                theme.style(key, "color: {MUTED};")
                key.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
                key.setMinimumWidth(130)  # same label column in every card
                val = QLabel(v)
                val.setFont(mono(9.5))
                val.setWordWrap(True)
                val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                grid.addWidget(key, r, 0)
                grid.addWidget(val, r, 1)
            card.body.addLayout(grid)
            self.body_lay.insertWidget(self.body_lay.count() - 1, card)

    def _copy(self) -> None:
        if not self.sections:
            return
        QGuiApplication.clipboard().setText(sysinfo.as_text(self.sections))
        self.status.emit("System information copied to the clipboard")
