"""A vertical navigation rail on the left, instead of a tab bar.

Collapsed it is a narrow strip of icons with a hamburger button on top.
Hovering expands it to icon plus label as an overlay over the page, so the
page does not reflow while the mouse moves. The hamburger pins it open; then
the rail takes real width and the page shifts once. Tab reaches the rail,
Up/Down move between items, Enter or Space selects; every item has an
accessible name and, while collapsed, a tooltip with its label.

Icons come from the icon theme with a fallback name each, so a third-party
theme that lacks one name does not leave the rail blank.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QKeyEvent, QPalette
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QToolButton, QVBoxLayout, QWidget

from . import theme

COLLAPSED = 52      # px: icon only
EXPANDED = 200      # px: icon and label
ITEM_H = 44
ICON = QSize(22, 22)
SETTINGS_KEY = "nav_pinned"

# Breeze names checked with QIcon.hasThemeIcon() on the development machine;
# the second name is the fallback for themes that lack the first.
PAGE_ICONS = {
    "Overview": ("utilities-system-monitor", "view-statistics"),
    "Processes": ("view-process-tree", "view-list-details"),
    "Network": ("network-wired", "network-connect"),
    "Startup": ("system-run", "media-playback-start"),
    "System": ("computer", "cpu"),
    "Cleanup": ("edit-clear-history", "trash-empty"),
    "Help": ("help-contents", "system-help"),
}
MENU_ICON = ("application-menu", "open-menu-symbolic")


def pick_icon_name(name: str, fallback: str, has=None) -> str:
    """The first name the theme has, else the fallback name."""
    has = QIcon.hasThemeIcon if has is None else has
    return name if has(name) else fallback


def theme_icon(name: str, fallback: str) -> QIcon:
    """The theme's icon by name, or by the fallback name when the first is missing."""
    return QIcon.fromTheme(pick_icon_name(name, fallback))


class NavRail(QWidget):
    """The strip itself. Owns the buttons; NavShell places it over the page."""

    current_changed = Signal(int)
    pinned_changed = Signal(bool)
    hover_changed = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("navrail")
        self.setAccessibleName("Navigation")
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        # An overlay must be opaque. A plain QWidget subclass paints its
        # stylesheet background only with WA_StyledBackground. The palette
        # fill below covers the case of the stylesheet ever being removed;
        # while the stylesheet is in force Qt turns autoFillBackground off
        # itself and paints the rule instead.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(theme.SURFACE))
        self.setPalette(pal)
        self.items: list[QToolButton] = []
        self._current = 0
        self._focused = 0
        self._expanded = False
        self.pinned = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 6, 4, 6)
        lay.setSpacing(2)
        self.menu = QToolButton()
        self.menu.setCheckable(True)
        self.menu.setIcon(theme_icon(*MENU_ICON))
        self.menu.setIconSize(ICON)
        self.menu.setAccessibleName("Menu")
        self.menu.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.menu.setFixedHeight(ITEM_H)
        self.menu.toggled.connect(self.set_pinned)
        lay.addWidget(self.menu)
        lay.addSpacing(6)
        self._items_layout = QVBoxLayout()
        self._items_layout.setSpacing(2)
        lay.addLayout(self._items_layout)
        lay.addStretch(1)

        self.setStyleSheet(f"""
            #navrail {{ background: {theme.SURFACE}; border-right: 1px solid {theme.BORDER}; }}
            #navrail QToolButton {{
                background: transparent; color: {theme.MUTED}; border: none;
                border-left: 2px solid transparent; border-radius: 6px;
                padding: 0 10px; text-align: left; font-weight: 600;
            }}
            #navrail QToolButton:hover {{ color: {theme.TEXT}; background: {theme.SURFACE_ALT}; }}
            #navrail QToolButton:checked {{ color: {theme.ACCENT}; border-left: 2px solid {theme.ACCENT}; }}
            #navrail QToolButton[cursor="true"] {{ background: {theme.SURFACE_HI}; }}
        """)
        self._apply_width()

    # -- items --------------------------------------------------------------
    def add_item(self, label: str, icon: QIcon) -> QToolButton:
        b = QToolButton()
        b.setText(label)
        b.setIcon(icon)
        b.setIconSize(ICON)
        b.setCheckable(True)
        b.setAutoExclusive(True)
        b.setAccessibleName(label)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # the rail holds the focus
        b.setFixedHeight(ITEM_H)
        b.setSizePolicy(b.sizePolicy().horizontalPolicy().Expanding, b.sizePolicy().verticalPolicy())
        index = len(self.items)
        b.clicked.connect(lambda _=False, i=index: self.set_current(i))
        self.items.append(b)
        self._items_layout.addWidget(b)
        if index == 0:
            b.setChecked(True)
        self._apply_width()
        return b

    def current(self) -> int:
        return self._current

    def set_current(self, index: int) -> None:
        if not 0 <= index < len(self.items):
            return
        changed = index != self._current
        self._current = index
        self.items[index].setChecked(True)
        self._set_focused(index)
        if changed:
            self.current_changed.emit(index)

    # -- width -------------------------------------------------------------
    @property
    def expanded(self) -> bool:
        return self._expanded or self.pinned

    def set_expanded(self, on: bool) -> None:
        """Hover state; ignored while pinned (pinned is always expanded)."""
        if on == self._expanded:
            return
        self._expanded = on
        self._apply_width()
        self.hover_changed.emit(on)

    def set_pinned(self, on: bool) -> None:
        if on == self.pinned:
            return
        self.pinned = on
        if self.menu.isChecked() != on:
            self.menu.setChecked(on)
        self._apply_width()
        self.pinned_changed.emit(on)

    def _apply_width(self) -> None:
        wide = self.expanded
        style = (Qt.ToolButtonStyle.ToolButtonTextBesideIcon if wide
                 else Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.menu.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.menu.setToolTip("Unpin the menu" if self.pinned else "Pin the menu open")
        for b in self.items:
            b.setToolButtonStyle(style)
            b.setToolTip("" if wide else b.text())
        self.setFixedWidth(EXPANDED if wide else COLLAPSED)

    # -- hover and keyboard ----------------------------------------------------
    def enterEvent(self, event) -> None:
        self.set_expanded(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.set_expanded(False)
        super().leaveEvent(event)

    def _set_focused(self, index: int) -> None:
        self._focused = index
        for i, b in enumerate(self.items):
            b.setProperty("cursor", "true" if (i == index and self.hasFocus()) else "false")
            b.style().unpolish(b)
            b.style().polish(b)

    def focusInEvent(self, event) -> None:
        self._set_focused(self.current())
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        self._set_focused(self._focused)
        super().focusOutEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        n = len(self.items)
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Right) and n:
            self._set_focused((self._focused + 1) % n)
        elif key in (Qt.Key.Key_Up, Qt.Key.Key_Left) and n:
            self._set_focused((self._focused - 1) % n)
        elif key == Qt.Key.Key_Home and n:
            self._set_focused(0)
        elif key == Qt.Key.Key_End and n:
            self._set_focused(n - 1)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.set_current(self._focused)
        else:
            super().keyPressEvent(event)
            return
        event.accept()


class NavShell(QWidget):
    """Rail plus pages. The rail is not in the layout: a placeholder of the
    rail's *pinned* width sits there, and the rail floats over the left edge.
    So hovering (overlay) never moves the page, and pinning moves it once."""

    def __init__(self, settings: QSettings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.pages = QStackedWidget()
        self.placeholder = QWidget()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.placeholder)
        lay.addWidget(self.pages, 1)
        self.rail = NavRail(self)
        self.rail.current_changed.connect(self.pages.setCurrentIndex)
        self.rail.pinned_changed.connect(self._pinned)
        self.rail.raise_()
        self.rail.set_pinned(self.settings.value(SETTINGS_KEY, False, type=bool))
        self._pinned(self.rail.pinned, persist=False)

    def add_page(self, widget: QWidget, label: str) -> None:
        name, fallback = PAGE_ICONS.get(label, ("", ""))
        self.pages.addWidget(widget)
        self.rail.add_item(label, theme_icon(name, fallback))
        self.rail.raise_()

    def set_current(self, widget_or_index) -> None:
        index = (widget_or_index if isinstance(widget_or_index, int)
                 else self.pages.indexOf(widget_or_index))
        self.rail.set_current(index)
        self.pages.setCurrentIndex(index)

    def current_index(self) -> int:
        return self.pages.currentIndex()

    def _pinned(self, on: bool, persist: bool = True) -> None:
        self.placeholder.setFixedWidth(EXPANDED if on else COLLAPSED)
        if persist:
            self.settings.setValue(SETTINGS_KEY, on)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.rail.setGeometry(0, 0, self.rail.width(), self.height())
        self.rail.raise_()
