"""Hand-drawn meters and graphs. No extra dependencies, yet 60fps-worthy."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QScrollArea,
    QScrollBar,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from . import theme


def mono(role: str = "body", bold: bool = False) -> QFont:
    """The system's fixed font at a size of the scale: title, body or small."""
    return theme.font(role, bold=bold, mono=True)


_ICONS: dict[str, QIcon] = {}


def app_icon(key: str) -> QIcon:
    """Icon for a theme name or file path as produced by archpm.appinfo; cached.
    A null QIcon means "no icon", which callers must respect: no fallback."""
    if not key:
        return QIcon()
    icon = _ICONS.get(key)
    if icon is None:
        icon = QIcon(key) if key.startswith("/") else QIcon.fromTheme(key)
        _ICONS[key] = icon
    return icon


def human_bytes(n: float, suffix: str = "B") -> str:
    for unit in ("", "K", "M", "G", "T"):
        if abs(n) < 1024.0:
            return f"{n:.0f} {unit}{suffix}" if unit == "" else f"{n:.1f} {unit}{suffix}"
        n /= 1024.0
    return f"{n:.1f} P{suffix}"


class Card(QFrame):
    """Panel with a title; the standard container on the dashboard."""

    def __init__(self, title: str = "", parent: QWidget | None = None,
                 color: str | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        theme.style(self, "#card {{ background: {SURFACE}; border: 1px solid {BORDER};"
                          " border-radius: {RADIUS_CARD}px; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.CARD_PAD, theme.CARD_PAD_Y, theme.CARD_PAD, theme.CARD_PAD_Y)
        lay.setSpacing(8)
        if title:
            lbl = QLabel(title.upper())
            f = theme.font("small", bold=True)
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.1)
            lbl.setFont(f)
            # The title takes the colour of the data it frames (CPU yellow, GPU
            # purple, ...) so the reader links the two at a glance.
            theme.text(lbl, color or "LABEL")
            lay.addWidget(lbl)
        self.body = lay


@dataclass
class Series:
    name: str
    color: str
    values: deque = field(default_factory=lambda: deque(maxlen=180))


class Graph(QWidget):
    """Line/area graph with a fixed or auto-scaling y-axis."""

    def __init__(
        self,
        series: list[tuple[str, str]],
        maximum: float | None = 100.0,
        unit: str = "%",
        history: int = 180,
        fill: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.series = [Series(n, c, deque(maxlen=history)) for n, c in series]
        self.maximum = maximum
        self.unit = unit
        self.fill = fill
        self._formatter = None
        self.setMinimumHeight(96)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_formatter(self, fn) -> None:
        self._formatter = fn

    def set_history(self, *histories) -> None:
        """Replace every series at once with an existing history (newest last)."""
        for s, values in zip(self.series, histories, strict=False):
            s.values = deque((float(v) for v in values), maxlen=s.values.maxlen)
        self.update()

    def push(self, *values: float) -> None:
        for s, v in zip(self.series, values, strict=False):
            if not s.values:
                # First sample: fill the history, otherwise there is a tiny
                # dash in the right corner for minutes.
                s.values.extend([float(v)] * (s.values.maxlen or 1))
            else:
                s.values.append(float(v))
        self.update()

    def _scale(self) -> float:
        if self.maximum is not None:
            return self.maximum
        peak = max((max(s.values) for s in self.series if s.values), default=1.0)
        return max(peak * 1.15, 1.0)

    def _fmt(self, v: float) -> str:
        if self._formatter:
            return self._formatter(v)
        return f"{v:.0f}{self.unit}"

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        top = 18.0  # room for the legend
        plot = QRectF(rect.left(), rect.top() + top, rect.width(), rect.height() - top)
        scale = self._scale()

        # grid lines
        grid = QPen(QColor(theme.BORDER))
        grid.setWidthF(1.0)
        p.setPen(grid)
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            y = plot.bottom() - frac * plot.height()
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))

        for s in self.series:
            if len(s.values) < 2:
                continue
            n = s.values.maxlen or len(s.values)
            step = plot.width() / max(n - 1, 1)
            x0 = plot.right() - (len(s.values) - 1) * step
            pts = [
                QPointF(x0 + i * step, plot.bottom() - min(v / scale, 1.0) * plot.height())
                for i, v in enumerate(s.values)
            ]
            path = QPainterPath(pts[0])
            for pt in pts[1:]:
                path.lineTo(pt)
            col = theme.color(s.color)
            if self.fill:
                area = QPainterPath(path)
                area.lineTo(pts[-1].x(), plot.bottom())
                area.lineTo(pts[0].x(), plot.bottom())
                area.closeSubpath()
                grad = QLinearGradient(0, plot.top(), 0, plot.bottom())
                c1 = QColor(col); c1.setAlpha(110)
                c2 = QColor(col); c2.setAlpha(8)
                grad.setColorAt(0.0, c1)
                grad.setColorAt(1.0, c2)
                p.fillPath(area, QBrush(grad))
            pen = QPen(col)
            pen.setWidthF(1.8)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.drawPath(path)

        # scale top right: without it you cannot tell for network and disk
        # whether that peak is 2 KB/s or 200 MB/s.
        p.setFont(mono("small"))
        p.setPen(QColor(theme.FAINT))
        p.drawText(
            QRectF(rect.right() - 110, rect.top(), 108, top),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            self._fmt(scale),
        )

        # legend with current values
        p.setFont(mono("body", bold=True))
        x = rect.left() + 2
        for s in self.series:
            cur = s.values[-1] if s.values else 0.0
            text = f"{s.name} {self._fmt(cur)}" if s.name else self._fmt(cur)
            p.setPen(theme.color(s.color))
            if x > rect.right() - 130:
                break
            p.drawText(QRectF(x, rect.top(), 240, top), Qt.AlignmentFlag.AlignVCenter, text)
            x += p.fontMetrics().horizontalAdvance(text) + 16
        p.end()


class CoreGrid(QWidget):
    """One bar per logical core -- shows immediately whether a game only grabs 2 threads.

    Above MAX_BARS cores the bars would be too narrow to read, so cores are
    grouped into equal runs and each bar shows the group's average; the label
    then reads "0-1" instead of "0".
    """

    MAX_BARS = 64

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.values: list[float] = []
        self.group = 1
        self.setMinimumHeight(74)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def set_values(self, values: list[float]) -> None:
        n = len(values)
        if n > self.MAX_BARS:
            per = -(-n // self.MAX_BARS)  # ceil
            chunks = [values[i:i + per] for i in range(0, n, per)]
            self.values = [sum(c) / len(c) for c in chunks]
            if self.group != per:
                self.setToolTip(f"{n} logical cores shown as {len(self.values)} bars, "
                                f"each the average of {per}")
            self.group = per
        else:
            self.values = values
            self.group = 1
        self.update()

    def paintEvent(self, _event) -> None:
        if not self.values:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        n = len(self.values)
        gap = 4.0
        w = (self.width() - gap * (n - 1)) / n
        label_h = 13.0
        h = self.height() - label_h
        p.setFont(mono("small"))
        for i, v in enumerate(self.values):
            x = i * (w + gap)
            track = QRectF(x, 0, w, h)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.SURFACE_ALT))
            p.drawRoundedRect(track, 3, 3)
            fh = max(2.0, h * min(v, 100.0) / 100.0)
            col = theme.heat(v)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(x, h - fh, w, fh), 3, 3)
            if w < 14:
                continue  # label would overlap its neighbours; the bar alone still reads
            p.setPen(QColor(theme.MUTED))
            label = str(i) if self.group == 1 else f"{i * self.group}-{(i + 1) * self.group - 1}"
            p.drawText(QRectF(x, h, w, label_h), Qt.AlignmentFlag.AlignCenter, label)
        p.end()


class Ring(QWidget):
    """Ring gauge for a single percentage with a value in the centre."""

    def __init__(self, label: str, color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.label = label
        self.color = color
        self.value = 0.0
        self.caption = ""
        self.setMinimumSize(104, 104)

    def set_value(self, value: float, caption: str = "") -> None:
        self.value = max(0.0, min(100.0, value))
        self.caption = caption
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height())
        pad = 7.0
        rect = QRectF((self.width() - side) / 2 + pad, (self.height() - side) / 2 + pad,
                      side - 2 * pad, side - 2 * pad)
        pen = QPen(QColor(theme.SURFACE_ALT))
        pen.setWidthF(8.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, 225 * 16, -270 * 16)
        pen.setColor(theme.color(self.color))
        p.setPen(pen)
        p.drawArc(rect, 225 * 16, int(-270 * 16 * self.value / 100.0))

        p.setPen(QColor(theme.TEXT))
        p.setFont(mono("title", bold=True))
        p.drawText(rect.adjusted(0, -6, 0, -6), Qt.AlignmentFlag.AlignCenter, f"{self.value:.0f}%")
        p.setPen(QColor(theme.MUTED))
        p.setFont(mono("small"))
        p.drawText(rect.adjusted(0, 20, 0, 20), Qt.AlignmentFlag.AlignCenter,
                   self.caption or self.label)
        p.end()


class StatTile(QFrame):
    """Compact figure tile: value large, context small."""

    def __init__(self, title: str, color: str = "TEXT", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        theme.style(self, "QFrame {{ background: {SURFACE}; border: 1px solid {BORDER};"
                          " border-radius: {RADIUS_CARD}px; }} QLabel {{ border: none; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.TILE_PAD, theme.TILE_PAD - 2,
                               theme.TILE_PAD, theme.TILE_PAD - 2)
        lay.setSpacing(1)
        self._title = QLabel(title.upper())
        self._title.setFont(theme.font("small", bold=True))
        theme.text(self._title, color if color != "TEXT" else "LABEL")
        self._value = QLabel("--")
        self._value.setFont(mono("title", bold=True))
        theme.text(self._value, color)
        self._sub = QLabel("")
        self._sub.setFont(mono("small"))
        theme.style(self._sub, "color: {MUTED};")
        lay.addWidget(self._title)
        lay.addWidget(self._value)
        lay.addWidget(self._sub)

    def set(self, value: str, sub: str = "", color: str | None = None) -> None:
        self._value.setText(value)
        self._sub.setText(sub)
        if color:
            # per tick: a token name, a hex, or a QColor from heat()
            value = color.name() if isinstance(color, QColor) else theme.resolve(color)
            self._value.setStyleSheet(f"color: {value};")


class ElidedLabel(QLabel):
    """A one-line label that can be squeezed: it asks for its text's width
    but accepts any, and elides with an ellipsis instead of holding the
    window open. For a value that may be long in a column that may be
    narrow, and for the header bar's title."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self._width_hint = 0

    def set_width_hint(self, width: int) -> None:
        """Ask for this width instead of the text's: labels in a column of
        rows then line up, whatever each one says."""
        self._width_hint = width
        self.updateGeometry()

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(max(hint.width(), self._width_hint), hint.height())

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setFont(self.font())
        p.setPen(self.palette().color(self.foregroundRole()))
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight,
                                             self.width())
        p.drawText(self.rect(), int(self.alignment()), text)
        p.end()


class TextLink(QLabel):
    """A line of text that is a link when it has somewhere to go, and plain
    text otherwise. As a link it shows a pointer, underlines on hover, takes
    focus with Tab, paints a focus outline and fires on Enter or Space. As
    plain text it does none of that, so a state with nothing to do stays
    quiet text and never looks like a button."""

    activated = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = ""
        self._color = "ACCENT"
        self._link = False
        self._hover = False
        self._css = ""       # font rules, kept through link and plain (see set_css)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setOpenExternalLinks(False)
        self.linkActivated.connect(lambda _: self.activated.emit())
        self.set_plain("", "MUTED")

    def set_css(self, css: str) -> None:
        """Font rules as stylesheet text, e.g. "font-size: {FONT_TITLE}pt;
        font-weight: 700;". A font set with setFont() is lost when the
        stylesheet changes with the state; this one is written each time."""
        self._css = css
        if self._link:
            self.set_link(self._text, self._color)
        else:
            self.set_plain(self._text, self._color)

    def set_plain(self, text: str, color: str) -> None:
        self._link = False
        self._text, self._color = text, color
        theme.style(self, f"color: {{{color}}}; " + self._css)
        self.setText(text)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.update()

    def set_link(self, text: str, color: str) -> None:
        self._link = True
        self._text, self._color = text, color
        theme.style(self, self._css)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse
                                     | Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
        self._render()

    def _render(self) -> None:
        deco = "underline" if (self._hover or self.hasFocus()) else "none"
        self.setText(f'<a href="#go" style="color: {theme.resolve(self._color)}; '
                     f'text-decoration: {deco};">'
                     f"{self._text}</a>")

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        if self._link:
            self._hover = True
            self._render()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        if self._link:
            self._hover = False
            self._render()

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        if self._link:
            self._render()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        if self._link:
            self._render()

    def keyPressEvent(self, event) -> None:
        if self._link and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._link and self.hasFocus():
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(theme.color("FOCUS"), theme.FOCUS_W))
            inset = theme.FOCUS_W / 2
            p.drawRoundedRect(QRectF(self.rect()).adjusted(inset, inset, -inset, -inset),
                              theme.RADIUS_SMALL, theme.RADIUS_SMALL)
            p.end()


class GutterScrollBar(QScrollBar):
    """A scrollbar that asks for a column of its own; see chrome.in_gutter."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Vertical, parent)
        self.setProperty("gutter", True)


class VScrollArea(QScrollArea):
    """A page that scrolls up and down and never sideways: its minimum width
    is the page's own, so the window cannot be made narrower than the page,
    while the height is free and gains a scrollbar when the window is short.
    That scrollbar has a gutter beside the page, not a place over it."""

    def __init__(self, widget: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.viewport().setAutoFillBackground(False)
        # A page's bar stands beside the page in a gutter of its own, on a
        # track, and never over a row or a card; see chrome.OverlayScrollStyle.
        # Marked before it is ever polished, so the fade never takes it.
        self.setVerticalScrollBar(GutterScrollBar())
        self.setWidget(widget)
        # A scroll area does not pass its page's size hints up. When the
        # page lays itself out again, the window's minimum must follow.
        widget.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.widget() and event.type() == QEvent.Type.LayoutRequest:
            self.updateGeometry()
        return super().eventFilter(obj, event)

    def minimumSizeHint(self) -> QSize:
        base = super().minimumSizeHint()
        inner = self.widget().minimumSizeHint().width() if self.widget() else 0
        return QSize(max(base.width(), inner + 2 * self.frameWidth()), base.height())


def scrolling(widget: QWidget) -> VScrollArea:
    """A page in a frameless, transparent scroll area: it lays itself out at
    its natural size and gains a scrollbar only when the window is shorter,
    instead of forcing the window to grow to fit."""
    return VScrollArea(widget)


class FlowLayout(QLayout):
    """A row of controls that wraps to a second row when the width runs out,
    instead of setting the window's minimum width to the whole row.

    On one row it reads like a QHBoxLayout: a stretch takes the leftover
    width, and so does a widget that expands sideways (a search field), so a
    toolbar that fits looks as it did. When it does not fit, the items after
    the break start the next row at the left. A label that wraps its words
    counts at its one-line width, since Qt's own hint for it is a narrow
    column; when even the row is too narrow for that line it takes a row of
    its own and wraps there. The minimum width is the widest single item."""

    def __init__(self, parent=None, spacing: int = 12) -> None:
        super().__init__(parent)
        self._items: list = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def __del__(self) -> None:
        while self.count():
            self.takeAt(0)

    def addItem(self, item) -> None:
        self._items.append(item)

    def addStretch(self, stretch: int = 1) -> None:
        self.addItem(QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._arrange(QRect(0, 0, width, 0), test=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._arrange(rect, test=False)

    def sizeHint(self) -> QSize:
        """One row: every item at its hint, side by side."""
        m = self.contentsMargins()
        w = h = 0
        for item in self._items:
            hint = item.sizeHint()
            w += hint.width() + (self.spacing() if w else 0)
            h = max(h, hint.height())
        return QSize(w + m.left() + m.right(), h + m.top() + m.bottom())

    def minimumSize(self) -> QSize:
        m = self.contentsMargins()
        w = h = 0
        for item in self._items:
            ms = item.minimumSize()
            w = max(w, ms.width())
            h = max(h, ms.height())
        return QSize(w + m.left() + m.right(), h + m.top() + m.bottom())

    def rows(self) -> int:
        """How many rows the current geometry uses; for tests."""
        return self._arrange(self.geometry(), test=True, count_rows=True)

    @staticmethod
    def _one_line(item, width: int) -> int:
        """The width an item wants: its hint, or for one that reflows (a
        wrapping label) the narrowest width at which it is still as low as
        it can be, found by bisection on heightForWidth; more than `width`
        means it does not fit on one line of this row."""
        hint = item.sizeHint().width()
        if not item.hasHeightForWidth():
            return hint
        lowest = item.heightForWidth(1 << 14)
        if item.heightForWidth(width) > lowest:
            return width + 1
        lo, hi = max(item.minimumSize().width(), 1), width
        while lo < hi:
            mid = (lo + hi) // 2
            if item.heightForWidth(mid) > lowest:
                lo = mid + 1
            else:
                hi = mid
        return lo

    @staticmethod
    def _expands(item) -> bool:
        if item.spacerItem() is not None:
            return bool(item.expandingDirections() & Qt.Orientation.Horizontal)
        w = item.widget()
        return w is not None and bool(w.sizePolicy().expandingDirections()
                                      & Qt.Orientation.Horizontal)

    def _arrange(self, rect: QRect, test: bool, count_rows: bool = False) -> int:
        m = self.contentsMargins()
        left, top = rect.x() + m.left(), rect.y() + m.top()
        width = rect.width() - m.left() - m.right()
        gap = self.spacing()
        rows: list[list] = [[]]
        wants: dict = {}
        used = 0
        for item in self._items:
            if item.widget() is not None and item.widget().isHidden():
                continue
            w = self._one_line(item, width)
            if w > width:                 # a wrapping label on a row of its own
                if rows[-1]:
                    rows.append([])
                rows[-1].append(item)
                rows.append([])
                used = 0
                wants[id(item)] = width
                continue
            if rows[-1] and used + gap + w > width:
                rows.append([])
                used = 0
            rows[-1].append(item)
            wants[id(item)] = w
            used += w + (gap if len(rows[-1]) > 1 else 0)
        y = top
        for row in rows:
            if not row:
                continue
            widths = [wants[id(item)] for item in row]
            spare = width - sum(widths) - gap * (len(row) - 1)
            takers = [item for item in row if self._expands(item)]
            extra = max(spare, 0) // len(takers) if takers else 0
            widths = [w + (extra if item in takers else 0)
                      for item, w in zip(row, widths, strict=True)]
            heights = [item.heightForWidth(w) if item.hasHeightForWidth()
                       else item.sizeHint().height()
                       for item, w in zip(row, widths, strict=True)]
            row_h = max(heights)
            x = left
            for item, w, h in zip(row, widths, heights, strict=True):
                if not test:
                    item.setGeometry(QRect(QPoint(x, y + (row_h - h) // 2), QSize(w, h)))
                x += w + gap
            y += row_h + gap
        if count_rows:
            return sum(1 for r in rows if r)
        return y - gap - top + m.top() + m.bottom() if any(rows) else 0


class TileRow(QWidget):
    """Equal tiles side by side, on two rows of half as many when the width
    no longer fits them all on one; the minimum width is the two-row one."""

    def __init__(self, tiles: list[QWidget], gap: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tiles = list(tiles)
        self.gap = gap
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(gap)
        # The grid must not put its one-row minimum on the widget: the
        # minimum is the two-row one, from minimumSizeHint below.
        self.grid.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self._cols = 0
        self._place(len(self.tiles))

    def _tile_min(self) -> int:
        return max((t.minimumSizeHint().width() for t in self.tiles), default=0)

    def _width_for(self, cols: int) -> int:
        return cols * self._tile_min() + (cols - 1) * self.gap

    def _place(self, cols: int) -> None:
        if cols == self._cols:
            return
        while self.grid.count():
            self.grid.takeAt(0)
        for i, t in enumerate(self.tiles):
            self.grid.addWidget(t, i // cols, i % cols)
        for c in range(len(self.tiles)):
            self.grid.setColumnStretch(c, 1 if c < cols else 0)
        self._cols = cols

    def columns(self) -> int:
        return self._cols

    def minimumSizeHint(self) -> QSize:
        half = (len(self.tiles) + 1) // 2
        return QSize(self._width_for(half), self.grid.minimumSize().height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        n = len(self.tiles)
        self._place(n if event.size().width() >= self._width_for(n) else (n + 1) // 2)


class Switch(QWidget):
    """An on/off switch: a pill with a knob that slides to the right when
    on. It is the control for a state that holds (starts at login: yes or
    no), where a check box would read as picking an item. On, it is the
    selection blue, as a ticked box is; off, a grey track. Space or Enter
    flips it, and the focus ring goes round the track."""

    toggled = Signal(bool)   # only from the user, never from set_checked()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._on = False
        self._pos = 0.0          # the knob: 0 = left (off), 1 = right (on)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(120)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._slide)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        ring = theme.FOCUS_W + 1
        self.setFixedSize(theme.SWITCH_W + 2 * ring, theme.SWITCH_H + 2 * ring)

    def isChecked(self) -> bool:
        return self._on

    def set_checked(self, on: bool) -> None:
        """The state from the data, shown at once and without a signal."""
        self._on = bool(on)
        self._anim.stop()
        self._pos = 1.0 if self._on else 0.0
        self.update()

    def toggle(self) -> None:
        """The user flipped it: slide the knob and say so."""
        self._on = not self._on
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if self._on else 0.0)
        self._anim.start()
        self.toggled.emit(self._on)

    def _slide(self, value) -> None:
        self._pos = float(value)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        inside = self.rect().contains(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and inside:
            self.toggle()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.toggle()
            event.accept()
            return
        super().keyPressEvent(event)

    @staticmethod
    def _mix(a: QColor, b: QColor, t: float) -> QColor:
        return QColor(round(a.red() + (b.red() - a.red()) * t),
                      round(a.green() + (b.green() - a.green()) * t),
                      round(a.blue() + (b.blue() - a.blue()) * t))

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        ring = theme.FOCUS_W + 1
        track = QRectF(ring, ring, theme.SWITCH_W, theme.SWITCH_H)
        r = theme.SWITCH_H / 2
        t = self._pos
        if not self.isEnabled():
            fill, knob = QColor(theme.SURFACE_ALT), QColor(theme.FAINT)
            border = QColor(theme.BORDER)
        else:
            fill = self._mix(QColor(theme.SURFACE_HI), QColor(theme.SELECT), t)
            knob = self._mix(QColor(theme.TEXT), QColor(theme.ON_SELECT), t)
            border = self._mix(QColor(theme.BORDER_HI), QColor(theme.SELECT), t)
        p.setPen(QPen(border, 1.0))
        p.setBrush(fill)
        p.drawRoundedRect(track.adjusted(0.5, 0.5, -0.5, -0.5), r, r)
        d = theme.SWITCH_H - 6
        x = track.left() + 3 + t * (theme.SWITCH_W - 6 - d)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(knob)
        p.drawEllipse(QRectF(x, track.top() + 3, d, d))
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(theme.color("FOCUS"), theme.FOCUS_W))
            inset = theme.FOCUS_W / 2
            outer = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
            p.drawRoundedRect(outer, outer.height() / 2, outer.height() / 2)
        p.end()


TITLE_MIN = 96      # px: the least a row's title column keeps
FLASH_MS = 700      # a header lighting up where a row landed
SLIDE_MS = 260      # a row sliding to its new place
# stylesheet fonts for a boxed list's labels; see ListRow
SMALL = "font-size: {FONT_SMALL}pt;"
SMALL_MUTED = "color: {MUTED}; " + SMALL
MONO = " font-family: monospace;"


class ListRow(QFrame):
    """One row of a boxed list: a title with a subtitle under it, an
    optional widget in front (an icon, a check box) and any number after
    (a status, a switch). The title column takes the width and elides; the
    widgets after it keep theirs. A property row is the other way round,
    for a spec sheet: the name small and dim on top, the value in full
    underneath, wrapping and selectable. A row that does something on a
    click is activatable: it lights on hover and fires `activated`.

    Fonts in here come from stylesheets, never from setFont(): a widget put
    into the box has its font resolved again from the stylesheet cascade,
    and a font set on it before that is lost."""

    activated = Signal()

    def __init__(self, title: str = "", subtitle: str = "",
                 prefix: QWidget | None = None, suffix: list[QWidget] | tuple = (),
                 property: bool = False, mono: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("listrow")
        self.setProperty("first", False)
        self.setProperty("last", False)
        self.setProperty("activatable", False)
        self.setProperty("moving", False)
        self.setMinimumHeight(theme.LIST_ROW_H)
        self._glow = 0.0
        self._flash: QVariantAnimation | None = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(theme.LIST_PAD_X, theme.LIST_PAD_Y,
                               theme.LIST_PAD_X, theme.LIST_PAD_Y)
        lay.setSpacing(12)
        self.prefix = prefix
        if prefix is not None:
            lay.addWidget(prefix, 0, Qt.AlignmentFlag.AlignVCenter)
        self.column = QWidget()
        self.column.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.column.setMinimumWidth(TITLE_MIN)   # the title never vanishes
        col = QVBoxLayout(self.column)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(1)
        self._collapsible: list[tuple[QWidget, int]] = []
        if property:
            self.title = QLabel(title)
            theme.style(self.title, SMALL_MUTED)
            self.subtitle = QLabel(subtitle)
            self.subtitle.setWordWrap(True)
            self.subtitle.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            theme.style(self.subtitle, "color: {TEXT};" + (MONO if mono else ""))
        else:
            self.title = ElidedLabel(title)
            self.subtitle = ElidedLabel(subtitle)
            theme.style(self.subtitle, SMALL_MUTED)
        col.addWidget(self.title)
        col.addWidget(self.subtitle)
        self.subtitle.setVisible(bool(subtitle))
        lay.addWidget(self.column, 1, Qt.AlignmentFlag.AlignVCenter)
        self.suffix = list(suffix)
        for w in self.suffix:
            lay.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_subtitle(self, text: str) -> None:
        self.subtitle.setText(text)
        self.subtitle.setVisible(bool(text))

    def add_body(self, widget: QWidget) -> None:
        """More under the subtitle: a log, a note."""
        self.column.layout().addWidget(widget)

    def set_collapsible(self, widget: QWidget, min_width: int) -> None:
        """A suffix widget that goes when the row is narrower than
        `min_width`, so the title keeps its room; what it said is in the
        tooltip or the note above the list."""
        self._collapsible.append((widget, min_width))
        widget.setVisible(self.width() >= min_width)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        for widget, min_width in self._collapsible:
            widget.setVisible(event.size().width() >= min_width)

    def set_activatable(self, on: bool) -> None:
        self.setProperty("activatable", bool(on))
        self.setCursor(Qt.CursorShape.PointingHandCursor if on else Qt.CursorShape.ArrowCursor)
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, event) -> None:
        if (self.property("activatable") and event.button() == Qt.MouseButton.LeftButton
                and self.rect().contains(event.position().toPoint())):
            self.activated.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def dim(self, token: str = "FAINT") -> None:
        """The whole row in one quiet colour: an entry for another desktop,
        an item that cannot be removed."""
        for w in (self.title, self.subtitle, *self.suffix):
            if isinstance(w, QLabel):
                theme.text(w, token)

    def make_header(self) -> None:
        """A group header inside the list, in the process list's shape: the
        group's name in bold with its count, a row that is not an entry."""
        theme.style(self.title, "font-weight: 700;")
        self.setProperty("header", True)
        self.setMinimumHeight(theme.LIST_ROW_H - 8)
        self.layout().setContentsMargins(theme.LIST_PAD_X, theme.LIST_PAD_Y - 4,
                                         theme.LIST_PAD_X, theme.LIST_PAD_Y - 4)

    def set_count(self, label: str, count: int) -> None:
        self.title.setText(f"{label} ({count})")

    def flash(self, msec: int = FLASH_MS) -> None:
        """Light up briefly in the highlight colour, so the eye finds the
        row: where a moved row landed, even when the row itself left the
        screen."""
        if self._flash is None:
            self._flash = QVariantAnimation(self)
            self._flash.setEasingCurve(QEasingCurve.Type.InOutQuad)
            self._flash.valueChanged.connect(self._glow_to)
        self._flash.stop()
        self._flash.setDuration(msec)
        self._flash.setKeyValueAt(0.0, 0.0)
        self._flash.setKeyValueAt(0.3, 1.0)
        self._flash.setKeyValueAt(1.0, 0.0)
        self._flash.start()

    def _glow_to(self, value) -> None:
        self._glow = float(value)
        self.update()

    def glowing(self) -> bool:
        """Lit, or about to be: the flash is running."""
        return self._glow > 0.0 or (self._flash is not None
                                    and self._flash.state() == QVariantAnimation.State.Running)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._glow <= 0.0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        colour = theme.color("ACCENT")
        colour.setAlphaF(0.28 * self._glow)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(colour)
        r = theme.RADIUS_CARD - 1
        p.drawRoundedRect(QRectF(self.rect()), r, r)
        p.end()


class BoxedList(QWidget):
    """A group in GNOME's shape: a title, a description under it, room for
    one control at the head's right, and a box of rows with a line between
    each. The head is hidden when it has nothing, the box when it is empty."""

    def __init__(self, title: str = "", description: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.head = QWidget()
        head = QHBoxLayout(self.head)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(12)
        self.title = QLabel(title)
        theme.style(self.title, "font-weight: 700;")
        head.addWidget(self.title)
        head.addStretch(1)
        self._suffix: QWidget | None = None
        lay.addWidget(self.head)
        self.description = QLabel(description)
        self.description.setWordWrap(True)
        self.description.setTextFormat(Qt.TextFormat.RichText)
        theme.text(self.description, "MUTED")
        lay.addWidget(self.description)
        self.box = QFrame()
        self.box.setObjectName("boxedlist")
        self._rows = QVBoxLayout(self.box)
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(0)
        lay.addWidget(self.box)
        self._slide: tuple | None = None
        self._show_head()
        self.box.hide()

    def _show_head(self) -> None:
        self.title.setVisible(bool(self.title.text()))
        self.head.setVisible(bool(self.title.text()) or self._suffix is not None)
        self.description.setVisible(bool(self.description.text()))

    def set_title(self, text: str) -> None:
        self.title.setText(text)
        self._show_head()

    def set_description(self, text: str) -> None:
        self.description.setText(text)
        self._show_head()

    def set_suffix(self, widget: QWidget) -> None:
        """The one control of the group, on the title's line right after it,
        so it reads as the group's and not as one more page button."""
        self._suffix = widget
        self.head.layout().insertWidget(1, widget, 0, Qt.AlignmentFlag.AlignVCenter)
        self._show_head()

    def rows(self) -> list[ListRow]:
        """The rows in order; a placeholder of a slide in progress is not one."""
        out = []
        for i in range(self._rows.count()):
            w = self._rows.itemAt(i).widget()
            if isinstance(w, ListRow):
                out.append(w)
        return out

    @staticmethod
    def _mark(row: ListRow, first: bool, last: bool) -> None:
        if row.property("first") == first and row.property("last") == last:
            return
        row.setProperty("first", first)
        row.setProperty("last", last)
        row.style().unpolish(row)
        row.style().polish(row)

    def _remark(self) -> None:
        rows = self.rows()
        for i, row in enumerate(rows):
            if isinstance(row, ListRow):
                self._mark(row, i == 0, i == len(rows) - 1)

    def add_row(self, row: ListRow) -> ListRow:
        rows = self.rows()
        if rows:
            self._mark(rows[-1], len(rows) == 1, False)
        self._rows.addWidget(row)
        self._mark(row, not rows, True)
        self.box.show()
        return row

    def clear(self) -> None:
        self.finish_slide()
        while self._rows.count():
            item = self._rows.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.box.hide()

    # -- a row on the move -----------------------------------------------------
    # The rows are widgets in one column, not items of a model, so a row
    # can really travel: it is lifted out of the layout, a placeholder of
    # its height stays where it was and another of no height goes where it
    # will be, the two trade their heights while the row moves between
    # them, and the row is put back at the end. The box keeps its height
    # throughout; the viewport clips the row when it travels past the edge.
    def slide_row(self, row: ListRow, index: int, msec: int = SLIDE_MS) -> None:
        """Move `row` to `index` of the final order, animated. A slide that
        is still running is finished first: one at a time."""
        self.finish_slide()
        old = self._rows.indexOf(row)
        if old < 0:
            return
        if msec <= 0 or not self.isVisible():
            self._rows.removeWidget(row)
            self._rows.insertWidget(index, row)
            self._remark()
            return
        h = row.height()
        start = row.geometry()
        self._rows.removeWidget(row)
        gone = QWidget(self.box)
        gone.setFixedHeight(h)
        self._rows.insertWidget(old, gone)
        coming = QWidget(self.box)
        coming.setFixedHeight(0)
        self._rows.insertWidget(index + (1 if index > old else 0), coming)
        for ph in (gone, coming):
            ph.show()      # now, not at the next event: the layout skips a hidden item
        self._set_moving(row, True)
        row.raise_()
        anim = QVariantAnimation(self)
        anim.setDuration(msec)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._slide = (anim, row, index, gone, coming, h, start)
        anim.valueChanged.connect(self._slide_step)
        anim.finished.connect(self.finish_slide)
        anim.start()

    def _slide_step(self, value) -> None:
        if self._slide is None:
            return
        _anim, row, _index, gone, coming, h, start = self._slide
        t = float(value)
        gone.setFixedHeight(round(h * (1.0 - t)))
        coming.setFixedHeight(round(h * t))
        # lay the column out now, not at the next event, so the target is
        # this frame's and the row never lags a frame behind the gap
        self._rows.invalidate()
        self._rows.activate()
        target = coming.geometry()
        y = start.y() + (target.y() - start.y()) * t
        row.setGeometry(start.x(), round(y), start.width(), h)

    def finish_slide(self) -> None:
        """Put a moving row in its place at once; nothing when none moves."""
        if self._slide is None:
            return
        anim, row, index, gone, coming, _h, _start = self._slide
        self._slide = None
        anim.stop()
        anim.deleteLater()
        for ph in (gone, coming):
            self._rows.removeWidget(ph)
            ph.hide()
            ph.deleteLater()
        self._set_moving(row, False)
        self._rows.insertWidget(index, row)
        self._remark()

    @staticmethod
    def _set_moving(row: ListRow, on: bool) -> None:
        row.setProperty("moving", on)
        row.style().unpolish(row)
        row.style().polish(row)

    def sliding(self) -> bool:
        return self._slide is not None


class Columns(QWidget):
    """Groups one under the other, or in two columns side by side when the
    width allows, the order kept: the first half of the rows on the left,
    the rest on the right. A spec sheet in one column at full width would
    hug the left edge and leave the right of the window empty."""

    def __init__(self, gap: int, column_min: int = 360, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.gap = gap
        self.column_min = column_min
        self._groups: list[tuple[QWidget, int]] = []
        self._cols = 0
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(gap)
        lay.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self._sides: list[QWidget] = []
        for _ in range(2):
            side = QWidget()
            col = QVBoxLayout(side)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(gap)
            col.addStretch(1)
            lay.addWidget(side, 1, Qt.AlignmentFlag.AlignTop)
            self._sides.append(side)
        self._sides[1].hide()

    def set_groups(self, groups: list[tuple[QWidget, int]]) -> None:
        """(widget, weight) per group; the weight is its number of rows."""
        for w, _ in self._groups:
            w.hide()
            w.deleteLater()
        self._groups = list(groups)
        self._cols = 0
        self._place(self._columns_for(self.width()))

    def _columns_for(self, width: int) -> int:
        return 2 if width >= 2 * self.column_min + self.gap else 1

    def columns(self) -> int:
        return self._cols

    def _place(self, cols: int) -> None:
        if cols == self._cols:
            return
        for side in self._sides:
            col = side.layout()
            while col.count() > 1:      # keep the trailing stretch
                col.takeAt(0)
        total = sum(weight for _, weight in self._groups)
        done = 0
        for w, weight in self._groups:
            right = cols == 2 and done >= (total + 1) // 2
            col = self._sides[1 if right else 0].layout()
            col.insertWidget(col.count() - 1, w)
            done += weight
        self._sides[1].setVisible(cols == 2)
        self._cols = cols

    def minimumSizeHint(self) -> QSize:
        wide = max((w.minimumSizeHint().width() for w, _ in self._groups), default=0)
        return QSize(wide, super().minimumSizeHint().height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place(self._columns_for(event.size().width()))
