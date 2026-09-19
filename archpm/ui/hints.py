"""Tooltips with a plain sentence, an "is this normal?" line and a right-click
that opens the term in Help. One place, so every tile, legend and column
header behaves the same."""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QHeaderView, QMenu, QTableWidget, QTreeWidget, QWidget

from .. import helptext
from . import theme


def tooltip_html(key: str) -> str:
    h = helptext.hint(key)
    if h is None:
        return ""
    parts = [f"<p style='margin:0'>{h.text}</p>"]
    if h.normal:
        parts.append(f"<p style='margin:4px 0 0 0'><span style='color:{theme.ACCENT}'>"
                     f"Normal?</span> {h.normal}</p>")
    if h.term:
        parts.append(f"<p style='margin:4px 0 0 0;color:{theme.MUTED}'>"
                     f"Right-click: explain “{h.term}” in Help</p>")
    return "<div style='max-width:340px'>" + "".join(parts) + "</div>"


def _menu_for(key: str, on_help, parent: QWidget) -> QMenu | None:
    h = helptext.hint(key)
    if h is None or not h.term:
        return None
    menu = QMenu(parent)
    menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)   # gone with the click, not the window
    act = QAction(f"Explain “{h.term}” in Help", menu)
    act.triggered.connect(lambda _=False, t=h.term: on_help(t))
    menu.addAction(act)
    return menu


def attach(widget: QWidget, key: str, on_help) -> None:
    """Tooltip plus right-click → Help on any widget."""
    tip = tooltip_html(key)
    if tip:
        widget.setToolTip(tip)
    widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def show(pos):
        menu = _menu_for(key, on_help, widget)
        if menu is not None:
            menu.exec(widget.mapToGlobal(pos))

    widget.customContextMenuRequested.connect(show)


def header_tooltips(view: QTreeWidget | QTableWidget, keys: list[str]) -> None:
    """Tooltips on the column headers of a tree or table widget."""
    for col, key in enumerate(keys):
        tip = tooltip_html(key)
        if not tip:
            continue
        if isinstance(view, QTreeWidget):
            view.headerItem().setToolTip(col, tip)
        else:
            item = view.horizontalHeaderItem(col)
            if item is not None:
                item.setToolTip(tip)


def attach_header(header: QHeaderView, keys: list[str], on_help, names: list[str] | None = None,
                  hideable: tuple[int, ...] = (), settings: QSettings | None = None,
                  settings_key: str = "hidden_columns",
                  default_hidden: tuple[int, ...] = ()) -> None:
    """Right-click on a column header: explain the column in Help and, when
    `hideable` is given, tick columns on and off (remembered in `settings`)."""
    header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    if hideable and settings is not None:
        stored = settings.value(settings_key, None)
        hidden = ({int(c) for c in stored} if stored is not None else set(default_hidden))
        for col in hideable:
            header.setSectionHidden(col, col in hidden)

    def remember():
        if hideable and settings is not None:
            settings.setValue(settings_key,
                              [c for c in hideable if header.isSectionHidden(c)])

    def show(pos):
        col = header.logicalIndexAt(pos)
        menu = QMenu(header)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        if 0 <= col < len(keys):
            h = helptext.hint(keys[col])
            if h is not None and h.term:
                act = QAction(f"Explain “{h.term}” in Help", menu)
                act.triggered.connect(lambda _=False, t=h.term: on_help(t))
                menu.addAction(act)
        if hideable and names:
            if not menu.isEmpty():
                menu.addSeparator()
            title = menu.addAction("Columns")
            title.setEnabled(False)
            for c in hideable:
                act = QAction(names[c], menu)
                act.setCheckable(True)
                act.setChecked(not header.isSectionHidden(c))

                def toggle(on, c=c):
                    header.setSectionHidden(c, not on)
                    remember()
                act.toggled.connect(toggle)
                menu.addAction(act)
        if menu.isEmpty():
            menu.deleteLater()      # never shown, so never closed: let it go here
            return
        menu.exec(header.mapToGlobal(pos))

    header.customContextMenuRequested.connect(show)
