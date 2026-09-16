"""Hand-drawn meters and graphs. No extra dependencies, yet 60fps-worthy."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
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
    QLabel,
    QLayout,
    QScrollArea,
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
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setOpenExternalLinks(False)
        self.linkActivated.connect(lambda _: self.activated.emit())
        self.set_plain("", "MUTED")

    def set_plain(self, text: str, color: str) -> None:
        self._link = False
        self._text = text
        theme.text(self, color)
        self.setText(text)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.update()

    def set_link(self, text: str, color: str) -> None:
        self._link = True
        self._text, self._color = text, color
        self.setStyleSheet("")
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


class VScrollArea(QScrollArea):
    """A page that scrolls up and down and never sideways: its minimum width
    is the page's own, so the window cannot be made narrower than the page,
    while the height is free and gains a scrollbar when the window is short."""

    def __init__(self, widget: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.viewport().setAutoFillBackground(False)
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
