"""Colours and stylesheet.

Dark, with two fixed roles: **yellow** highlights (focus, active tab, headline
figures, warnings) and **blue** selects (selected rows, checked items). Never mix
those two -- that is what keeps the UI readable.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette

# -- base tones ----------------------------------------------------------
BG = "#0f1115"
SURFACE = "#161920"
SURFACE_ALT = "#1d212a"
SURFACE_HI = "#242935"
BORDER = "#282e3a"
BORDER_HI = "#39404f"
TEXT = "#e7eaf2"
MUTED = "#868fa4"
FAINT = "#5c6478"

# -- roles ---------------------------------------------------------------
ACCENT = "#f5c542"        # yellow: highlight
ACCENT_DIM = "#8a6d1c"
SELECT = "#3d7dff"        # blue: select
SELECT_DIM = "#1e3a6b"

# -- data series ---------------------------------------------------------
CPU = "#f5c542"
GPU = "#a78bfa"
MEM = "#4fd1c5"
NET = "#5aa2ff"
DISK = "#f08faf"
SWAP = "#e8925a"

OK = "#4ade80"
WARN = "#f5a524"
CRIT = "#ff5d5d"


def heat(pct: float) -> QColor:
    """Green → yellow → red, for utilisation and temperature."""
    pct = max(0.0, min(100.0, pct))
    if pct < 60:
        return QColor(OK)
    if pct < 85:
        return QColor(WARN)
    return QColor(CRIT)


def apply(app) -> None:
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(BG))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Base, QColor(SURFACE))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(SURFACE_ALT))
    pal.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Button, QColor(SURFACE_ALT))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(SELECT))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(SURFACE_HI))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(FAINT))
    pal.setColor(QPalette.ColorRole.Link, QColor(ACCENT))
    app.setPalette(pal)
    app.setStyleSheet(STYLE)


STYLE = f"""
QWidget {{ color: {TEXT}; font-size: 10pt; }}
QMainWindow, QDialog {{ background: {BG}; }}

/* tabs as segments, active one marked with yellow */
QTabWidget::pane {{ border: none; background: {BG}; }}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{
    background: transparent; color: {MUTED};
    padding: 9px 20px; margin: 0 2px; border: none;
    border-bottom: 2px solid transparent;
    font-weight: 600;
}}
QTabBar::tab:selected {{ color: {ACCENT}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:hover:!selected {{ color: {TEXT}; }}

/* tables: blue selects, yellow marks the sorted column */
QTableView {{
    background: {SURFACE}; alternate-background-color: {SURFACE_ALT};
    gridline-color: {BORDER}; border: 1px solid {BORDER}; border-radius: 10px;
    selection-background-color: {SELECT}; selection-color: #ffffff;
    outline: none;
}}
QTableView::item {{ padding: 3px 6px; border: none; }}
QTableView::item:hover {{ background: {SURFACE_HI}; }}
QTableView::item:selected {{ background: {SELECT}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: {SURFACE_ALT}; color: {MUTED}; border: none;
    border-bottom: 1px solid {BORDER}; padding: 7px 8px;
    font-size: 9pt; font-weight: 700;
}}
QHeaderView::section:hover {{ color: {TEXT}; background: {SURFACE_HI}; }}
QHeaderView::section:checked {{ color: {ACCENT}; }}
QHeaderView::down-arrow, QHeaderView::up-arrow {{ width: 9px; height: 9px; }}

QLineEdit, QComboBox, QSpinBox, QAbstractSpinBox {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 7px;
    padding: 6px 10px; selection-background-color: {SELECT}; selection-color: #ffffff;
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover {{ border-color: {BORDER_HI}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QAbstractSpinBox:focus {{
    border-color: {ACCENT};
}}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE_ALT}; border: 1px solid {BORDER}; border-radius: 8px;
    selection-background-color: {SELECT}; padding: 4px;
}}

QPushButton {{
    background: {SURFACE_ALT}; border: 1px solid {BORDER}; border-radius: 7px;
    padding: 7px 15px; font-weight: 600;
}}
QPushButton:hover {{ background: {SURFACE_HI}; border-color: {BORDER_HI}; }}
QPushButton:pressed {{ background: {SURFACE}; }}
QPushButton:disabled {{ color: {FAINT}; border-color: {SURFACE_ALT}; background: {SURFACE}; }}
QPushButton:focus {{ border-color: {ACCENT}; }}
QPushButton#accent {{
    background: {ACCENT}; color: #1a1405; border-color: {ACCENT};
}}
QPushButton#accent:hover {{ background: #ffd45e; border-color: #ffd45e; }}
QPushButton#accent:disabled {{ background: {ACCENT_DIM}; color: #2a2308; border-color: {ACCENT_DIM}; }}
QPushButton#danger:hover {{ background: {CRIT}; border-color: {CRIT}; color: #1f0708; }}

QCheckBox, QRadioButton {{ spacing: 8px; color: {MUTED}; }}
QCheckBox:hover, QRadioButton:hover {{ color: {TEXT}; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 15px; height: 15px;
    border: 1px solid {BORDER_HI}; border-radius: 4px; background: {SURFACE};
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
    background: {SURFACE_ALT}; border: 1px solid {BORDER}; border-radius: 9px; padding: 6px;
}}
QMenu::item {{ padding: 7px 24px 7px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: {SELECT}; color: #ffffff; }}
QMenu::item:disabled {{ color: {FAINT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 8px; }}

QGroupBox {{
    border: 1px solid {BORDER}; border-radius: 10px; margin-top: 14px;
    padding: 12px; background: {SURFACE};
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 12px; padding: 0 6px;
    color: {MUTED}; font-size: 8pt; font-weight: 700;
}}

QStatusBar {{ color: {MUTED}; border-top: 1px solid {BORDER}; }}
QStatusBar::item {{ border: none; }}
QToolTip {{
    background: {SURFACE_HI}; color: {TEXT}; border: 1px solid {BORDER_HI};
    padding: 5px 7px; border-radius: 6px;
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
