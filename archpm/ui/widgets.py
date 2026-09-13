"""Hand-drawn meters and graphs. No extra dependencies, yet 60fps-worthy."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontDatabase, QLinearGradient, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget

from . import theme


def mono(size: float = 9, bold: bool = False) -> QFont:
    f = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    f.setPointSizeF(float(size))
    f.setBold(bold)
    return f


def human_bytes(n: float, suffix: str = "B") -> str:
    for unit in ("", "K", "M", "G", "T"):
        if abs(n) < 1024.0:
            return f"{n:.0f} {unit}{suffix}" if unit == "" else f"{n:.1f} {unit}{suffix}"
        n /= 1024.0
    return f"{n:.1f} P{suffix}"


class Card(QFrame):
    """Panel with a title; the standard container on the dashboard."""

    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setStyleSheet(
            f"#card {{ background: {theme.SURFACE}; border: 1px solid {theme.BORDER};"
            f" border-radius: 10px; }}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 11, 14, 12)
        lay.setSpacing(8)
        if title:
            lbl = QLabel(title.upper())
            f = lbl.font()
            f.setPointSize(8)
            f.setBold(True)
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.1)
            lbl.setFont(f)
            lbl.setStyleSheet(f"color: {theme.MUTED};")
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

    def push(self, *values: float) -> None:
        for s, v in zip(self.series, values):
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
            col = QColor(s.color)
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
        p.setFont(mono(8))
        p.setPen(QColor(theme.FAINT))
        p.drawText(
            QRectF(rect.right() - 110, rect.top(), 108, top),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            self._fmt(scale),
        )

        # legend with current values
        p.setFont(mono(9, bold=True))
        x = rect.left() + 2
        for s in self.series:
            cur = s.values[-1] if s.values else 0.0
            text = f"{s.name} {self._fmt(cur)}" if s.name else self._fmt(cur)
            p.setPen(QColor(s.color))
            if x > rect.right() - 130:
                break
            p.drawText(QRectF(x, rect.top(), 240, top), Qt.AlignmentFlag.AlignVCenter, text)
            x += p.fontMetrics().horizontalAdvance(text) + 16
        p.end()


class CoreGrid(QWidget):
    """One bar per logical core -- shows immediately whether a game only grabs 2 threads."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.values: list[float] = []
        self.setMinimumHeight(74)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def set_values(self, values: list[float]) -> None:
        self.values = values
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
        p.setFont(mono(7))
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
            p.setPen(QColor(theme.MUTED))
            p.drawText(
                QRectF(x, h, w, label_h),
                Qt.AlignmentFlag.AlignCenter,
                str(i),
            )
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
        pen.setColor(QColor(self.color))
        p.setPen(pen)
        p.drawArc(rect, 225 * 16, int(-270 * 16 * self.value / 100.0))

        p.setPen(QColor(theme.TEXT))
        p.setFont(mono(13, bold=True))
        p.drawText(rect.adjusted(0, -6, 0, -6), Qt.AlignmentFlag.AlignCenter, f"{self.value:.0f}%")
        p.setPen(QColor(theme.MUTED))
        p.setFont(mono(7))
        p.drawText(rect.adjusted(0, 20, 0, 20), Qt.AlignmentFlag.AlignCenter,
                   self.caption or self.label)
        p.end()


class StatTile(QFrame):
    """Compact figure tile: value large, context small."""

    def __init__(self, title: str, color: str = theme.TEXT, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame {{ background: {theme.SURFACE}; border: 1px solid {theme.BORDER};"
            f" border-radius: 9px; }} QLabel {{ border: none; }}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 10)
        lay.setSpacing(1)
        self._title = QLabel(title.upper())
        tf = self._title.font()
        tf.setPointSize(8)
        tf.setBold(True)
        self._title.setFont(tf)
        self._title.setStyleSheet(f"color: {theme.MUTED};")
        self._value = QLabel("--")
        self._value.setFont(mono(15, bold=True))
        self._value.setStyleSheet(f"color: {color};")
        self._sub = QLabel("")
        self._sub.setFont(mono(8))
        self._sub.setStyleSheet(f"color: {theme.MUTED};")
        lay.addWidget(self._title)
        lay.addWidget(self._value)
        lay.addWidget(self._sub)

    def set(self, value: str, sub: str = "", color: str | None = None) -> None:
        self._value.setText(value)
        self._sub.setText(sub)
        if color:
            self._value.setStyleSheet(f"color: {color};")
