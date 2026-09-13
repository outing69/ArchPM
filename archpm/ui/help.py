"""The Help tab: what the words mean, what the colours mean, and About."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import helptext
from . import theme
from .widgets import Card, mono


class HelpView(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 12)
        outer.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(12)
        title = QLabel("What does this mean?")
        f = title.font()
        f.setPointSize(11)
        f.setBold(True)
        title.setFont(f)
        head.addWidget(title)
        head.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search the glossary… e.g. nice, VRAM, SIGKILL")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(320)
        self.search.textChanged.connect(self._rebuild)
        head.addWidget(self.search)
        outer.addLayout(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.body = QWidget()
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 0, 0)
        self.body_lay.setSpacing(10)
        self.scroll.setWidget(self.body)
        outer.addWidget(self.scroll, 1)
        self._rebuild("")

    # -- building ------------------------------------------------------------
    def _clear(self) -> None:
        while self.body_lay.count():
            item = self.body_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _rebuild(self, query: str) -> None:
        self._clear()
        sections = helptext.search(query)
        if not sections:
            lbl = QLabel(f"Nothing in the glossary matches \"{query.strip()}\". "
                         "Try another word, or ask on GitHub.")
            lbl.setStyleSheet(f"color: {theme.MUTED};")
            self.body_lay.addWidget(lbl)
        for sec in sections:
            card = Card(sec.title)
            grid = QGridLayout()
            grid.setHorizontalSpacing(18)
            grid.setVerticalSpacing(10)
            grid.setColumnStretch(1, 1)
            for r, term in enumerate(sec.terms):
                name = QLabel(term.name)
                name.setFont(mono(9.5, bold=True))
                name.setStyleSheet(f"color: {theme.ACCENT};")
                name.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
                name.setMinimumWidth(170)
                name.setWordWrap(True)
                text = QLabel(term.text + (f"<br><span style='color:{theme.FAINT}'>"
                                           f"Where: {term.where}</span>" if term.where else ""))
                text.setTextFormat(Qt.TextFormat.RichText)
                text.setWordWrap(True)
                text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                grid.addWidget(name, r, 0)
                grid.addWidget(text, r, 1)
            card.body.addLayout(grid)
            self.body_lay.addWidget(card)
        if not query.strip():
            self.body_lay.addWidget(self._colours_card())
            self.body_lay.addWidget(self._about_card())
        self.body_lay.addStretch(1)

    def _colours_card(self) -> Card:
        card = Card("what the colours mean")
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        swatches = {"Yellow": theme.ACCENT, "Blue": theme.SELECT,
                    "Green · orange · red": theme.WARN, "Series colours": theme.GPU,
                    "Grey": theme.MUTED}
        for r, (name, text) in enumerate(helptext.COLOURS):
            lbl = QLabel(name)
            lbl.setFont(mono(9.5, bold=True))
            lbl.setStyleSheet(f"color: {swatches.get(name, theme.TEXT)};")
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
            lbl.setMinimumWidth(170)
            val = QLabel(text)
            val.setWordWrap(True)
            grid.addWidget(lbl, r, 0)
            grid.addWidget(val, r, 1)
        card.body.addLayout(grid)
        return card

    def _about_card(self) -> Card:
        card = Card("about archpm")
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)
        for r, (k, v) in enumerate(helptext.about_lines()):
            key = QLabel(k)
            key.setStyleSheet(f"color: {theme.MUTED};")
            key.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
            key.setMinimumWidth(170)
            if v.startswith("http"):
                val = QLabel(f"<a href='{v}' style='color:{theme.ACCENT}'>{v}</a>")
                val.setTextFormat(Qt.TextFormat.RichText)
                val.setOpenExternalLinks(True)
            else:
                val = QLabel(v)
                val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            val.setFont(mono(9.5))
            val.setWordWrap(True)
            grid.addWidget(key, r, 0)
            grid.addWidget(val, r, 1)
        card.body.addLayout(grid)

        heading = QLabel("Changelog")
        heading.setStyleSheet(f"color: {theme.LABEL}; font-weight: 700;")
        card.body.addWidget(heading)
        log = QPlainTextEdit()
        log.setReadOnly(True)
        log.setPlainText(helptext.changelog_text())
        log.setFont(mono(8.5))
        log.setMinimumHeight(260)
        log.setStyleSheet(
            f"QPlainTextEdit {{ background: {theme.BG}; border: 1px solid {theme.BORDER};"
            f" border-radius: 8px; color: {theme.TEXT}; padding: 8px; }}"
        )
        card.body.addWidget(log)
        return card
