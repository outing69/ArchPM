"""Colours and stylesheet, in two modes.

Every colour is a token with a dark and a light value; no hex lives outside
this module. Two fixed roles in both modes: **yellow** (amber in light)
highlights (focus, active page, headline figures, warnings) and **blue**
selects (selected rows, checked items). Never mix those two -- that is what
keeps the UI readable.

The tokens are module names (theme.MUTED, ...) so a paint routine reads the
current value every time. A stylesheet baked at construction cannot, so it
goes through style(), which remembers the widget and its template and writes
it again when the mode changes. Series and card colours are passed as token
names ("CPU") and resolved at paint through resolve().

The mode follows the system by default: QStyleHints.colorScheme() where the
platform reports it, else the XDG desktop portal's color-scheme over D-Bus,
else dark. The preference (system, light, dark) lives in the app's settings.
"""
from __future__ import annotations

import weakref

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QPalette

DARK = {
    # base tones
    "BG": "#0f1115", "SURFACE": "#161920", "SURFACE_ALT": "#1d212a", "SURFACE_HI": "#242935",
    "BORDER": "#282e3a", "BORDER_HI": "#39404f",
    "TEXT": "#e7eaf2", "MUTED": "#868fa4", "FAINT": "#606a7e", "LABEL": "#aab3c8",
    # roles
    "ACCENT": "#f5c542", "ACCENT_DIM": "#8a6d1c", "ACCENT_HOVER": "#ffd45e",
    "ON_ACCENT": "#1a1405", "ON_ACCENT_DIM": "#2a2308",
    "SELECT": "#3d7dff", "SELECT_DIM": "#1e3a6b", "ON_SELECT": "#ffffff",
    "ON_CRIT": "#1f0708",
    # data series
    "CPU": "#f5c542", "GPU": "#a78bfa", "MEM": "#4fd1c5", "NET": "#5aa2ff",
    "DISK": "#f08faf", "SWAP": "#e8925a",
    "OK": "#4ade80", "WARN": "#f5a524", "CRIT": "#ff5d5d",
}
# Light is a new choice per token, not an inversion: the dark set is tuned
# for glow on near-black, and a yellow that reads on #161920 vanishes on
# white. Yellow becomes amber, the pastels become their saturated cousins,
# and every text tone is checked against the light surface (see tests).
LIGHT = {
    "BG": "#f6f5f4", "SURFACE": "#ffffff", "SURFACE_ALT": "#f1f0ee", "SURFACE_HI": "#e6e5e2",
    "BORDER": "#d5d3cf", "BORDER_HI": "#b9b6b1",
    "TEXT": "#1e1e1e", "MUTED": "#5f6672", "FAINT": "#8a919c", "LABEL": "#4a5160",
    "ACCENT": "#a16207", "ACCENT_DIM": "#e2c886", "ACCENT_HOVER": "#8a5306",
    "ON_ACCENT": "#ffffff", "ON_ACCENT_DIM": "#5a4a1a",
    "SELECT": "#2f6fe0", "SELECT_DIM": "#cfe0ff", "ON_SELECT": "#ffffff",
    "ON_CRIT": "#ffffff",
    "CPU": "#a16207", "GPU": "#7c3aed", "MEM": "#0f766e", "NET": "#2563eb",
    "DISK": "#be185d", "SWAP": "#c2410c",
    "OK": "#15803d", "WARN": "#b45309", "CRIT": "#c81e1e",
}
TOKENS = tuple(DARK)
# Shape and type, the same in both modes, in Adwaita's proportions: 12 px
# cards and popovers, 9 px controls, 34 px buttons and fields with 16 px of
# horizontal padding, air in multiples of 6. One type scale: title, body,
# small. The font family is never named; the system's own font wins, from
# QFontDatabase (Noto Sans and Noto Sans Mono on the development machine).
# Data tables stay dense on purpose: a process list is a data view, so its
# row height follows readability, not Adwaita's row spacing.
SHAPE = {
    "RADIUS_CARD": 12, "RADIUS_CONTROL": 9, "RADIUS_SMALL": 6, "RADIUS_TAG": 5,
    "BUTTON_H": 34, "BUTTON_PAD_X": 16, "FIELD_PAD_X": 10,
    "PAGE_MARGIN": 18, "CARD_GAP": 12, "CARD_PAD": 18, "CARD_PAD_Y": 14, "TILE_PAD": 12,
    "ROW_H": 26, "RAIL_ITEM_H": 44,
    "FONT_TITLE": 12, "FONT_BODY": 10, "FONT_SMALL": 8.5,
}
SHAPE_TOKENS = tuple(SHAPE)
MODES = ("dark", "light")
PREFERENCES = ("system", "light", "dark")
SETTINGS_KEY = "theme"

BG = DARK["BG"]
SURFACE = DARK["SURFACE"]
SURFACE_ALT = DARK["SURFACE_ALT"]
SURFACE_HI = DARK["SURFACE_HI"]
BORDER = DARK["BORDER"]
BORDER_HI = DARK["BORDER_HI"]
TEXT = DARK["TEXT"]
MUTED = DARK["MUTED"]
FAINT = DARK["FAINT"]
LABEL = DARK["LABEL"]
ACCENT = DARK["ACCENT"]
ACCENT_DIM = DARK["ACCENT_DIM"]
ACCENT_HOVER = DARK["ACCENT_HOVER"]
ON_ACCENT = DARK["ON_ACCENT"]
ON_ACCENT_DIM = DARK["ON_ACCENT_DIM"]
SELECT = DARK["SELECT"]
SELECT_DIM = DARK["SELECT_DIM"]
ON_SELECT = DARK["ON_SELECT"]
ON_CRIT = DARK["ON_CRIT"]
CPU = DARK["CPU"]
GPU = DARK["GPU"]
MEM = DARK["MEM"]
NET = DARK["NET"]
DISK = DARK["DISK"]
SWAP = DARK["SWAP"]
OK = DARK["OK"]
WARN = DARK["WARN"]
CRIT = DARK["CRIT"]


RADIUS_CARD = SHAPE["RADIUS_CARD"]
RADIUS_CONTROL = SHAPE["RADIUS_CONTROL"]
RADIUS_SMALL = SHAPE["RADIUS_SMALL"]
RADIUS_TAG = SHAPE["RADIUS_TAG"]
BUTTON_H = SHAPE["BUTTON_H"]
BUTTON_PAD_X = SHAPE["BUTTON_PAD_X"]
FIELD_PAD_X = SHAPE["FIELD_PAD_X"]
PAGE_MARGIN = SHAPE["PAGE_MARGIN"]
CARD_GAP = SHAPE["CARD_GAP"]
CARD_PAD = SHAPE["CARD_PAD"]
CARD_PAD_Y = SHAPE["CARD_PAD_Y"]
TILE_PAD = SHAPE["TILE_PAD"]
ROW_H = SHAPE["ROW_H"]
RAIL_ITEM_H = SHAPE["RAIL_ITEM_H"]
FONT_TITLE = SHAPE["FONT_TITLE"]
FONT_BODY = SHAPE["FONT_BODY"]
FONT_SMALL = SHAPE["FONT_SMALL"]


class _State:
    mode = "dark"
    preference = "system"


_state = _State()


class _Signals(QObject):
    changed = Signal(str)   # the new mode


signals = _Signals()
_styled: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def current() -> dict:
    """Every token the stylesheet template can name: the mode's colours and
    the shape, plus the button's inner height (the border takes the rest)."""
    out = {t: globals()[t] for t in TOKENS}
    out.update(SHAPE)
    out["BUTTON_INNER"] = SHAPE["BUTTON_H"] - 2
    return out


def page_margins() -> tuple[int, int, int, int]:
    """A page's outer margins: a little less at the top, under the window's title."""
    return PAGE_MARGIN, PAGE_MARGIN - 4, PAGE_MARGIN, PAGE_MARGIN


def font(role: str = "body", bold: bool = False, mono: bool = False):
    """The system's own font at one of the three sizes of the scale."""
    from PySide6.QtGui import QFontDatabase
    kind = QFontDatabase.SystemFont.FixedFont if mono else QFontDatabase.SystemFont.GeneralFont
    f = QFontDatabase.systemFont(kind)
    f.setPointSizeF(float({"title": FONT_TITLE, "body": FONT_BODY, "small": FONT_SMALL}[role]))
    f.setBold(bold)
    return f


def resolve(value: str) -> str:
    """A token name gives its current value; anything else passes through."""
    return globals()[value] if value in DARK else value


def color(value: str) -> QColor:
    return QColor(resolve(value))


def text(widget, token: str) -> None:
    """The common case: a label in one token's colour, kept current."""
    style(widget, f"color: {{{token}}};")


def style(widget, template: str) -> None:
    """Set a stylesheet with {TOKEN} placeholders, and set it again on every
    mode change for as long as the widget lives."""
    _styled[widget] = template
    widget.setStyleSheet(template.format(**current()))


def _restyle() -> None:
    import shiboken6
    tokens = current()
    for widget, template in list(_styled.items()):
        if shiboken6.isValid(widget):
            widget.setStyleSheet(template.format(**tokens))


def heat(pct: float) -> QColor:
    """Green → yellow → red, for utilisation and temperature."""
    pct = max(0.0, min(100.0, pct))
    if pct < 60:
        return QColor(OK)
    if pct < 85:
        return QColor(WARN)
    return QColor(CRIT)


def palette(t: dict[str, str]) -> QPalette:
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(t["BG"]))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(t["TEXT"]))
    pal.setColor(QPalette.ColorRole.Base, QColor(t["SURFACE"]))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(t["SURFACE_ALT"]))
    pal.setColor(QPalette.ColorRole.Text, QColor(t["TEXT"]))
    pal.setColor(QPalette.ColorRole.Button, QColor(t["SURFACE_ALT"]))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(t["TEXT"]))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(t["SELECT"]))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(t["ON_SELECT"]))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(t["SURFACE_HI"]))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(t["TEXT"]))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(t["FAINT"]))
    pal.setColor(QPalette.ColorRole.Link, QColor(t["ACCENT"]))
    return pal


def apply(app, new_mode: str = "dark") -> None:
    """Bind the tokens of a mode and put palette and stylesheet on the app."""
    if new_mode not in MODES:
        raise ValueError(new_mode)
    _state.mode = new_mode
    globals().update(LIGHT if new_mode == "light" else DARK)
    app.setPalette(palette(current()))
    app.setStyleSheet(STYLE_TEMPLATE.format(**current()))


def set_mode(app, new_mode: str) -> None:
    """Switch live: tokens, palette, app stylesheet, every registered
    stylesheet, then a repaint of everything and the changed signal."""
    if new_mode == _state.mode:
        return
    apply(app, new_mode)
    _restyle()
    from PySide6.QtWidgets import QApplication
    for w in QApplication.allWidgets():
        w.update()
    signals.changed.emit(new_mode)


# -- the system's preference --------------------------------------------------
def scheme_from_hints(app) -> str | None:
    """QStyleHints.colorScheme(), Qt 6.5+; None when the platform does not say."""
    hints = getattr(app, "styleHints", lambda: None)()
    if hints is None or not hasattr(hints, "colorScheme"):
        return None
    value = hints.colorScheme()
    if value == Qt.ColorScheme.Dark:
        return "dark"
    if value == Qt.ColorScheme.Light:
        return "light"
    return None


def scheme_from_portal() -> str | None:
    """org.freedesktop.appearance color-scheme from the desktop portal:
    1 = dark, 2 = light, 0 = no preference. None when the portal is not there."""
    try:
        from PySide6.QtDBus import QDBusConnection, QDBusInterface
    except ImportError:
        return None
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return None
    iface = QDBusInterface("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
                           "org.freedesktop.portal.Settings", bus)
    if not iface.isValid():
        return None
    reply = iface.call("ReadOne", "org.freedesktop.appearance", "color-scheme")
    args = reply.arguments()
    if not args:
        return None
    value = args[0]
    # a variant in a variant: unwrap what PySide hands back
    while hasattr(value, "variant"):
        value = value.variant()
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return {1: "dark", 2: "light"}.get(value)


def system_scheme(app) -> str:
    """What the desktop asks for; dark when nothing answers."""
    return scheme_from_hints(app) or scheme_from_portal() or "dark"


def wanted(app, pref: str) -> str:
    return system_scheme(app) if pref == "system" else pref


def set_preference(app, pref: str, settings=None) -> None:
    """Store the preference and apply the mode it means, without a restart."""
    if pref not in PREFERENCES:
        raise ValueError(pref)
    _state.preference = pref
    if settings is not None:
        settings.setValue(SETTINGS_KEY, pref)
    set_mode(app, wanted(app, pref))


def start(app, settings=None) -> None:
    """At startup: read the preference, apply the mode, and follow the
    system's scheme from then on while the preference is "system"."""
    pref = settings.value(SETTINGS_KEY, "system", type=str) if settings is not None else "system"
    _state.preference = pref if pref in PREFERENCES else "system"
    apply(app, wanted(app, _state.preference))
    hints = getattr(app, "styleHints", lambda: None)()
    if hints is not None and hasattr(hints, "colorSchemeChanged"):
        hints.colorSchemeChanged.connect(
            lambda _s: _state.preference == "system" and set_mode(app, system_scheme(app)))


def mode() -> str:
    return _state.mode


def preference() -> str:
    return _state.preference


STYLE_TEMPLATE = """
QWidget {{ color: {TEXT}; font-size: {FONT_BODY}pt; }}
QMainWindow, QDialog {{ background: {BG}; }}

/* tables: blue selects, yellow marks the sorted column */
QTableView {{
    background: {SURFACE}; alternate-background-color: {SURFACE_ALT};
    gridline-color: {BORDER}; border: 1px solid {BORDER}; border-radius: {RADIUS_CARD}px;
    selection-background-color: {SELECT}; selection-color: {ON_SELECT};
    outline: none;
}}
QTableView::item {{ padding: 3px 6px; border: none; }}
QTableView::item:hover {{ background: {SURFACE_HI}; }}
QTableView::item:selected {{ background: {SELECT}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: {SURFACE_ALT}; color: {MUTED}; border: none;
    border-bottom: 1px solid {BORDER}; padding: 7px 8px;
    font-size: {FONT_SMALL}pt; font-weight: 700;
}}
QHeaderView::section:hover {{ color: {TEXT}; background: {SURFACE_HI}; }}
QHeaderView::section:checked {{ color: {ACCENT}; }}
QHeaderView::down-arrow, QHeaderView::up-arrow {{ width: 9px; height: 9px; }}

QLineEdit, QComboBox, QSpinBox, QAbstractSpinBox {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: {RADIUS_CONTROL}px;
    padding: 0 {FIELD_PAD_X}px; min-height: {BUTTON_INNER}px;
    selection-background-color: {SELECT};
    selection-color: {ON_SELECT};
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover {{ border-color: {BORDER_HI}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QAbstractSpinBox:focus {{
    border-color: {ACCENT};
}}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE_ALT}; border: 1px solid {BORDER}; border-radius: {RADIUS_CONTROL}px;
    selection-background-color: {SELECT}; padding: 4px;
}}

QPushButton {{
    background: {SURFACE_ALT}; border: 1px solid {BORDER}; border-radius: {RADIUS_CONTROL}px;
    padding: 0 {BUTTON_PAD_X}px; min-height: {BUTTON_INNER}px; font-weight: 600;
}}
QPushButton:hover {{ background: {SURFACE_HI}; border-color: {BORDER_HI}; }}
QPushButton:pressed {{ background: {SURFACE}; }}
QPushButton:disabled {{ color: {FAINT}; border-color: {SURFACE_ALT}; background: {SURFACE}; }}
QPushButton:focus {{ border-color: {ACCENT}; }}
QPushButton#accent {{
    background: {ACCENT}; color: {ON_ACCENT}; border-color: {ACCENT};
}}
QPushButton#accent:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton#accent:disabled {{
    background: {ACCENT_DIM}; color: {ON_ACCENT_DIM}; border-color: {ACCENT_DIM};
}}
QPushButton#danger:hover {{ background: {CRIT}; border-color: {CRIT}; color: {ON_CRIT}; }}
/* the one button that ends something: red at rest, solid red on hover */
QPushButton#kill {{ color: {CRIT}; border-color: {CRIT}; background: {SURFACE}; }}
QPushButton#kill:hover {{ background: {CRIT}; border-color: {CRIT}; color: {ON_CRIT}; }}
QPushButton#kill:disabled {{ color: {FAINT}; border-color: {BORDER}; }}

QCheckBox, QRadioButton {{ spacing: 8px; color: {MUTED}; }}
QCheckBox:hover, QRadioButton:hover {{ color: {TEXT}; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 15px; height: 15px;
    border: 1px solid {BORDER_HI}; border-radius: {RADIUS_TAG}px; background: {SURFACE};
}}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {SELECT}; border-color: {SELECT};
}}

QSlider::groove:horizontal {{
    height: 5px; background: {SURFACE_HI}; border-radius: 3px;
}}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
QSlider::handle:horizontal {{
    background: {TEXT}; width: 15px; height: 15px; margin: -5px 0; border-radius: 8px;
}}
QSlider::handle:horizontal:hover {{ background: {ACCENT}; }}

QMenu {{
    background: {SURFACE_ALT}; border: 1px solid {BORDER};
    border-radius: {RADIUS_CARD}px; padding: 6px;
}}
QMenu::item {{ padding: 7px 24px 7px 14px; border-radius: {RADIUS_SMALL}px; }}
QMenu::item:selected {{ background: {SELECT}; color: {ON_SELECT}; }}
QMenu::item:disabled {{ color: {FAINT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 8px; }}

QGroupBox {{
    border: 1px solid {BORDER}; border-radius: {RADIUS_CARD}px; margin-top: 14px;
    padding: {CARD_PAD_Y}px; background: {SURFACE};
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 12px; padding: 0 6px;
    color: {MUTED}; font-size: {FONT_SMALL}pt; font-weight: 700;
}}

QStatusBar {{ color: {MUTED}; border-top: 1px solid {BORDER}; }}
QStatusBar::item {{ border: none; }}
QToolTip {{
    background: {SURFACE_HI}; color: {TEXT}; border: 1px solid {BORDER_HI};
    padding: 5px 7px; border-radius: {RADIUS_CONTROL}px;
}}

QScrollBar:vertical {{ background: transparent; width: 11px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BORDER_HI}; border-radius: 5px; min-height: 34px; }}
QScrollBar::handle:vertical:hover {{ background: {MUTED}; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; }}
QScrollBar::handle:horizontal {{ background: {BORDER_HI}; border-radius: 5px; min-width: 34px; }}
QScrollBar::handle:horizontal:hover {{ background: {MUTED}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QScrollArea {{ border: none; background: transparent; }}
"""
