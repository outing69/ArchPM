"""A vertical navigation rail on the left, instead of a tab bar.

Collapsed it is a narrow strip of icons with a hamburger button on top.
Hovering expands it to icon plus label as an overlay over the page, so the
page does not reflow while the mouse moves. The width change is one property
animation with an easing curve, and it drives a plain resize: a fixed-width
change would invalidate the shell's layout on every frame although the rail
is not in it. The rail declares itself opaque, so the page beneath is not
repainted for every frame either. The hamburger pins it open; then the rail
takes real width and the page shifts once. Tab reaches the rail,
Up/Down move between items, Enter or Space selects; every item has an
accessible name and, while collapsed, a tooltip with its label.

Icons come from the icon theme with a fallback name each, so a third-party
theme that lacks one name does not leave the rail blank.
"""
from __future__ import annotations

import os

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QPropertyAnimation,
    QSettings,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QIcon, QKeyEvent, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QStackedWidget,
    QStyle,
    QStyleOption,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import theme

COLLAPSED = 52      # px: icon only
EXPANDED = 200      # px: icon and label
SLIDE_MS = 160      # the expand and collapse animation
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
    "Snapshots": ("view-history", "document-open-recent"),
    "Help": ("help-contents", "system-help"),
}
MENU_ICON = ("application-menu", "open-menu-symbolic")
# The Adwaita set, all symbolic; used only when every one of the nine
# resolves under Adwaita (checked with QIcon.hasThemeIcon at start), else
# the whole rail stays on the Breeze names above. Adwaita has no
# utilities-system-monitor-symbolic; its gauge stands in for the Overview.
ADWAITA_ICONS = {
    "Overview": "power-profile-performance-symbolic",
    "Processes": "view-list-bullet-symbolic",
    "Network": "network-wired-symbolic",
    "Startup": "system-run-symbolic",
    "System": "computer-symbolic",
    "Cleanup": "edit-clear-all-symbolic",
    "Snapshots": "document-open-recent-symbolic",
    "Help": "help-about-symbolic",
    "Menu": "open-menu-symbolic",
}
# Icons for a kind of thing that has no icon of its own: the four kinds of
# a Startup entry, the three sections of the process list and the origins
# of a snapshot (pacman, a person, a timer) and the chevron of a pacman pair
# row, closed and open. (Adwaita symbolic name, Breeze name); both checked
# with QIcon.hasThemeIcon on the development machine. The Adwaita names count
# towards the all-or-nothing rule: one missing keeps the whole application on
# Breeze.
KIND_ICONS = {
    "App": ("application-x-executable-symbolic", "application-x-executable"),
    "System": ("package-x-generic-symbolic", "package-x-generic"),
    "Desktop": ("user-desktop-symbolic", "user-desktop"),
    "override": ("document-edit-symbolic", "document-edit"),
    "apps": ("application-x-executable-symbolic", "application-x-executable"),
    "background": ("system-run-symbolic", "system-run"),
    "system": ("computer-symbolic", "computer"),
    "pacman": ("package-x-generic-symbolic", "package-x-generic"),
    "person": ("avatar-default-symbolic", "user-identity"),
    "timer": ("alarm-symbolic", "chronometer"),
    "expand": ("pan-end-symbolic", "arrow-right"),          # a closed pacman pair
    "collapse": ("pan-down-symbolic", "arrow-down"),        # an open one
}
KIND_SIZE = QSize(16, 16)
ADWAITA = "Adwaita"
BREEZE = {"breeze", "breeze-dark"}
_icon_set: dict = {}     # "name": "adwaita" | "breeze", "missing": [...]
_kind_icons: dict = {}   # (kind, colour token, mode) -> QIcon


def pick_icon_name(name: str, fallback: str, has=None) -> str:
    """The first name the theme has, else the fallback name."""
    has = QIcon.hasThemeIcon if has is None else has
    return name if has(name) else fallback


def theme_icon(name: str, fallback: str) -> QIcon:
    """The theme's icon by name, or by the fallback name when the first is missing."""
    return QIcon.fromTheme(pick_icon_name(name, fallback))


def icon_dirs() -> list[str]:
    """The XDG icon directories, in lookup order."""
    data_dirs = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")
    dirs = [os.path.expanduser("~/.icons"), os.path.expanduser("~/.local/share/icons")]
    return dirs + [os.path.join(d, "icons") for d in data_dirs if d]


def _ensure_search_paths() -> None:
    """Without a platform theme (offscreen, some minimal sessions) Qt knows
    only its own resources; add the XDG icon directories. Qt drops them again
    whenever the theme name is set, so this is called before each lookup."""
    paths = list(QIcon.themeSearchPaths())
    extra = icon_dirs()
    if not any(p in paths for p in extra):
        QIcon.setThemeSearchPaths(extra + paths)


def adwaita_missing(has=None) -> list[str]:
    """The names of ADWAITA_ICONS and KIND_ICONS that Adwaita does not
    resolve; empty when the whole set is there. The theme name is put back
    afterwards."""
    has = QIcon.hasThemeIcon if has is None else has
    _ensure_search_paths()
    before = QIcon.themeName()
    QIcon.setThemeName(ADWAITA)
    try:
        names = list(ADWAITA_ICONS.values()) + [a for a, _ in KIND_ICONS.values()]
        return [name for name in dict.fromkeys(names) if not has(name)]
    finally:
        QIcon.setThemeName(before)


def icon_set() -> dict:
    """Decided once per process: {"name": "adwaita"|"breeze", "missing": [...]}."""
    if not _icon_set:
        missing = adwaita_missing()
        _icon_set.update({"name": "breeze" if missing else "adwaita", "missing": missing})
    return _icon_set


def adwaita_file(name: str) -> str:
    """The svg of an Adwaita symbolic icon, found by hand: QIcon.fromTheme
    resolves against the app's theme at paint time, and we do not switch
    the app's theme for nine icons."""
    for base in icon_dirs():
        root = os.path.join(base, ADWAITA)
        if not os.path.isdir(root):
            continue
        for sub in ("symbolic", "scalable"):
            for ctx in sorted(os.listdir(os.path.join(root, sub))) if os.path.isdir(
                    os.path.join(root, sub)) else []:
                path = os.path.join(root, sub, ctx, name + ".svg")
                if os.path.isfile(path):
                    return path
    return ""


def tinted(icon: QIcon, color: str, size: QSize) -> QIcon:
    """A symbolic icon painted in one colour: the shape from the file, the
    colour from the theme, so it reads on a dark and on a light rail."""
    pm = icon.pixmap(size)
    if pm.isNull():
        return icon
    out = QPixmap(pm.size())
    out.setDevicePixelRatio(pm.devicePixelRatio())
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.drawPixmap(0, 0, pm)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(out.rect(), QColor(color))
    p.end()
    return QIcon(out)


def page_icon(label: str, color: str) -> QIcon:
    """The rail's icon for a page in the current mode: the Adwaita symbolic
    file tinted with `color`, or the Breeze theme icon as the theme paints it."""
    if icon_set()["name"] == "adwaita":
        name = ADWAITA_ICONS.get(label, "")
        path = adwaita_file(name)
        if path:
            return tinted(QIcon(path), color, ICON)
    name, fallback = MENU_ICON if label == "Menu" else PAGE_ICONS.get(label, ("", ""))
    return theme_icon(name, fallback)


def kind_icon(kind: str, color: str = "MUTED") -> QIcon:
    """The icon for a kind of entry or a section of processes, for a row
    that has no icon of its own: the Adwaita symbolic file tinted in
    `color`, or the Breeze icon as the theme paints it. Cached per mode."""
    key = (kind, color, theme.mode())
    icon = _kind_icons.get(key)
    if icon is None:
        adwaita, breeze = KIND_ICONS.get(kind, ("", ""))
        icon = QIcon()
        if icon_set()["name"] == "adwaita":
            path = adwaita_file(adwaita)
            if path:
                icon = tinted(QIcon(path), theme.resolve(color), KIND_SIZE)
        if icon.isNull() and breeze:
            _ensure_search_paths()
            icon = QIcon.fromTheme(breeze)
        _kind_icons[key] = icon
    return icon


def match_breeze_to_mode(light: bool) -> None:
    """Plasma's Breeze has a light and a dark icon set; when the app's icons
    come from one of them, take the one that reads on the current mode."""
    if QIcon.themeName() in BREEZE:
        QIcon.setThemeName("breeze" if light else "breeze-dark")


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
        # Every pixel is painted by the stylesheet rule, so the backing store
        # need not paint the page underneath first: without this, each frame
        # of the animation repainted the page as well. Qt then also skips its
        # own styled-background pass, so paintEvent below draws the rule.
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self._apply_palette()
        theme.signals.changed.connect(self._retheme)
        self.items: list[QToolButton] = []
        self._current = 0
        self._focused = 0
        self._expanded = False
        self.pinned = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 6, 4, 6)
        lay.setSpacing(2)
        # The width is set by resize() from the animation, never by the
        # layout: explicit bounds keep the layout from raising the minimum
        # to the labels' width while they are showing.
        lay.setSizeConstraint(QVBoxLayout.SizeConstraint.SetNoConstraint)
        self.setMinimumWidth(COLLAPSED)
        self.setMaximumWidth(EXPANDED)
        # On the built-in size property: a Python-side Property for the width
        # alone leaves an uncollectable descriptor behind in PySide.
        self.anim = QPropertyAnimation(self, b"size", self)
        self.anim.setDuration(SLIDE_MS)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.finished.connect(self._slide_done)
        self.menu = QToolButton()
        self.menu.setCheckable(True)
        self.menu.setIcon(page_icon("Menu", theme.MUTED))
        self.menu.setIconSize(ICON)
        self.menu.setAccessibleName("Menu")
        self.menu.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.menu.setFixedHeight(theme.RAIL_ITEM_H)
        self.menu.toggled.connect(self.set_pinned)
        lay.addWidget(self.menu)
        lay.addSpacing(6)
        self._items_layout = QVBoxLayout()
        self._items_layout.setSpacing(2)
        lay.addLayout(self._items_layout)
        lay.addStretch(1)

        theme.style(self, """
            #navrail {{ background: {SURFACE}; border-right: 1px solid {BORDER}; }}
            #navrail QToolButton {{
                background: transparent; color: {MUTED}; border: none;
                border-left: 2px solid transparent; border-radius: {RADIUS_SMALL}px;
                padding: 0 10px; text-align: left; font-weight: 600;
            }}
            #navrail QToolButton:hover {{ color: {TEXT}; background: {SURFACE_ALT}; }}
            #navrail QToolButton:checked {{
                color: {ACCENT}; border-left: 2px solid {ACCENT};
            }}
            #navrail QToolButton[cursor="true"] {{ background: {SURFACE_HI}; }}
        """)
        self._apply_width()

    def _apply_palette(self) -> None:
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(theme.SURFACE))
        self.setPalette(pal)

    def _retheme(self, mode: str) -> None:
        """The mode changed: the opaque fill and the icons follow."""
        self._apply_palette()
        match_breeze_to_mode(mode == "light")
        self.menu.setIcon(page_icon("Menu", theme.MUTED))
        for b in self.items:
            b.setIcon(page_icon(b.text(), theme.MUTED))
        self.update()

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
        b.setFixedHeight(theme.RAIL_ITEM_H)
        # Ignored: the rail's width decides, so while it slides the label is
        # clipped at the rail's edge instead of the button overflowing it.
        b.setSizePolicy(b.sizePolicy().horizontalPolicy().Ignored, b.sizePolicy().verticalPolicy())
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
        """Slide to the width the state asks for. Expanding shows the labels
        from the first frame, so they appear from under the edge; collapsing
        keeps them until the slide is done. Hidden, the width is set at once."""
        wide = self.expanded
        self.menu.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.menu.setToolTip("Unpin the menu" if self.pinned else "Pin the menu open")
        target = EXPANDED if wide else COLLAPSED
        if wide:
            self._set_labels(True)
        self.anim.stop()
        if not self.isVisible():
            self.resize(target, self.height())
            self._slide_done()
            return
        self.anim.setStartValue(self.size())
        self.anim.setEndValue(QSize(target, self.height()))
        self.anim.start()

    def _slide_done(self) -> None:
        if not self.expanded:
            self._set_labels(False)

    def _set_labels(self, on: bool) -> None:
        style = (Qt.ToolButtonStyle.ToolButtonTextBesideIcon if on
                 else Qt.ToolButtonStyle.ToolButtonIconOnly)
        for b in self.items:
            b.setToolButtonStyle(style)
            b.setToolTip("" if on else b.text())

    def sliding(self) -> bool:
        return self.anim.state() == QAbstractAnimation.State.Running

    def paintEvent(self, event) -> None:
        opt = QStyleOption()
        opt.initFrom(self)
        painter = QPainter(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, opt, painter, self)

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
        # The content column: a header bar, when one is set, over the pages.
        self.column = QVBoxLayout()
        self.column.setContentsMargins(0, 0, 0, 0)
        self.column.setSpacing(0)
        self.column.addWidget(self.pages, 1)
        lay.addLayout(self.column, 1)
        self.rail = NavRail(self)
        self.rail.current_changed.connect(self.pages.setCurrentIndex)
        self.rail.pinned_changed.connect(self._pinned)
        self.rail.raise_()
        self.rail.set_pinned(self.settings.value(SETTINGS_KEY, False, type=bool))
        self._pinned(self.rail.pinned, persist=False)

    def set_header(self, widget: QWidget) -> None:
        """The content column's header bar, above the pages; the rail keeps
        the full height beside it, as the sidebar of a split layout."""
        self.column.insertWidget(0, widget)
        self.rail.raise_()

    def add_page(self, widget: QWidget, label: str) -> None:
        self.pages.addWidget(widget)
        self.rail.add_item(label, page_icon(label, theme.MUTED))
        self.rail.raise_()

    def label_of(self, index: int) -> str:
        return self.rail.items[index].text() if 0 <= index < len(self.rail.items) else ""

    def set_current(self, widget_or_index) -> None:
        """By index, or by a page: the page itself, or a view inside one
        (a page that scrolls is the scroll area, and the view its content)."""
        index = self.index_of(widget_or_index) if not isinstance(widget_or_index, int) \
            else widget_or_index
        if index < 0:
            return
        self.rail.set_current(index)
        self.pages.setCurrentIndex(index)

    def index_of(self, widget: QWidget) -> int:
        w = widget
        while w is not None:
            index = self.pages.indexOf(w)
            if index >= 0:
                return index
            w = w.parentWidget()
        return -1

    def current_index(self) -> int:
        return self.pages.currentIndex()

    def _pinned(self, on: bool, persist: bool = True) -> None:
        self.placeholder.setFixedWidth(EXPANDED if on else COLLAPSED)
        if persist:
            self.settings.setValue(SETTINGS_KEY, on)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.rail.setGeometry(0, 0, self.rail.width(), self.height())
        if self.rail.sliding():            # the slide ends at the new height too
            self.rail.anim.setEndValue(QSize(self.rail.anim.endValue().width(), self.height()))
        self.rail.raise_()
