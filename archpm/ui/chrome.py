"""The window's chrome in GNOME's shape: a header bar, a toast, overlay
scrollbars.

The header bar sits above the pages, to the right of the navigation rail,
as the content pane's own header in a split layout: the title in the
middle, the window's few controls on the right, the desktop's own title
bar and window buttons above it. Its controls are flat: no border or fill
until hovered. The toast is one line over the content, bottom centre, that
fades by itself. A table's scrollbar lies over the content's edge instead
of taking a column of its own, and fades when nothing moves. A page's
scrollbar (a VScrollArea, marked "gutter") is the exception: it stands
beside the page on a thin track, so it never covers a row or a card.
"""
from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QProxyStyle,
    QScrollBar,
    QStyle,
    QStyleFactory,
    QStyleOptionSlider,
    QWidget,
)

from . import theme
from .widgets import ElidedLabel

TOAST_MS = 4000        # the default stay; a caller with more to say asks for longer
TOAST_IN_MS = 150
TOAST_OUT_MS = 300
TOAST_MARGIN = 24      # from the bottom edge of the content
SCROLL_IDLE_MS = 1200  # a scrollbar stays this long after the last movement
SCROLL_FADE_MS = 250
SCROLL_RESTING = 0.0


class HeaderBar(QWidget):
    """Title in the middle, controls on the right. The title is centred on
    the whole bar, as in Adwaita, while it fits beside the controls; in a
    narrow window it is centred in what is left and elides. Placed by hand:
    a layout would count the centring room as width the window must have."""

    PAD = 12     # to the bar's edges
    GAP = 6      # between the title's room and the controls

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("headerbar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(theme.HEADER_H)
        self.title = ElidedLabel(parent=self)
        self.title.setFont(theme.font("title", bold=True))
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setAccessibleName("Page title")
        self.controls = QWidget(self)
        self._controls = QHBoxLayout(self.controls)
        self._controls.setContentsMargins(0, 0, 0, 0)
        self._controls.setSpacing(6)

    def add_control(self, widget: QWidget) -> None:
        self._controls.addWidget(widget)
        self._place()

    def add_gap(self, px: int = 12) -> None:
        self._controls.addSpacing(px)

    def set_title(self, text: str) -> None:
        self.title.setText(text)
        self._place()

    def minimumSizeHint(self) -> QSize:
        return QSize(self.controls.minimumSizeHint().width() + 2 * self.PAD, theme.HEADER_H)

    def sizeHint(self) -> QSize:
        return QSize(self.controls.sizeHint().width() + 2 * self.PAD, theme.HEADER_H)

    def centred(self) -> bool:
        """Whether the title sits at the centre of the whole bar; for tests."""
        return self.title.geometry().left() == 0

    def _place(self) -> None:
        w, h = self.width(), self.height() - 1           # the last row is the border
        hint = self.controls.sizeHint()
        self.controls.setGeometry(w - self.PAD - hint.width(), (h - hint.height()) // 2,
                                  hint.width(), hint.height())
        text_w = self.title.fontMetrics().horizontalAdvance(self.title.text())
        side = hint.width() + self.PAD + self.GAP       # what the controls take, mirrored
        if text_w + 2 * side <= w:
            self.title.setGeometry(0, 0, w, h)
        else:
            self.title.setGeometry(self.PAD, 0, max(w - side - self.PAD, 0), h)
        self.title.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place()


class Toast(QLabel):
    """One short notice over the content: bottom centre of its parent,
    fades in, stays for the message's time, fades out. A new message
    replaces the one showing; a click dismisses it."""

    def __init__(self, parent: QWidget, left=lambda: 0) -> None:
        """`left()` says where the content starts inside the parent, so the
        toast is centred on the content and not on a rail beside it."""
        super().__init__(parent)
        self._left = left
        self.setObjectName("toast")
        self.setAccessibleName("Notification")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._fx = QGraphicsOpacityEffect(self)
        self._fx.setOpacity(0.0)
        self.setGraphicsEffect(self._fx)
        self._anim = QPropertyAnimation(self._fx, b"opacity", self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._settled)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        parent.installEventFilter(self)
        self.hide()

    def show_message(self, text: str, msec: int = TOAST_MS) -> None:
        self.setWordWrap(False)
        self.setText(text)
        self._place()
        self.show()
        self.raise_()
        self._fade(1.0, TOAST_IN_MS)
        self._timer.start(msec)

    def dismiss(self) -> None:
        self._timer.stop()
        if self.isVisible():
            self._fade(0.0, TOAST_OUT_MS)

    def showing(self) -> str:
        """The text on screen, "" when none."""
        return self.text() if self.isVisible() and self._fx.opacity() > 0 else ""

    def _fade(self, to: float, msec: int) -> None:
        self._anim.stop()
        self._anim.setDuration(msec)
        self._anim.setStartValue(self._fx.opacity())
        self._anim.setEndValue(to)
        self._anim.start()

    def _settled(self) -> None:
        if self._fx.opacity() == 0.0:
            self.hide()

    def _place(self) -> None:
        parent = self.parentWidget()
        left = self._left()
        room = parent.width() - left
        width = min(self.sizeHint().width(), room - 2 * TOAST_MARGIN)
        if width < self.sizeHint().width():
            self.setWordWrap(True)
        height = self.heightForWidth(width) if self.wordWrap() else self.sizeHint().height()
        self.setGeometry(left + (room - width) // 2, parent.height() - height - TOAST_MARGIN,
                         width, height)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize and self.isVisible():
            self._place()
        return False

    def mousePressEvent(self, event) -> None:
        self.dismiss()
        event.accept()


# -- overlay scrollbars ---------------------------------------------------------
SC = QStyle.SubControl
SCROLL_EDGE = 2       # from the content's edge to the handle
GUTTER_PAD = 4        # a gutter bar: this much air on each side of its handle
SLIDER_MIN = 34


def in_gutter(widget) -> bool:
    """A scrollbar that asked for a column of its own (a page's bar)."""
    return widget is not None and bool(widget.property("gutter"))


class OverlayScrollStyle(QProxyStyle):
    """Tells every scroll area that its scrollbars are transient, so Qt lays
    them over the viewport instead of beside it, and draws them itself: a
    round handle in the theme's colours, no track, no arrows, on Breeze and
    Fusion alike. The stylesheet must not give QScrollBar a box of its own,
    since a scrollbar with one is never transient to Qt. A bar marked
    "gutter" is not transient: Qt gives it a column beside the viewport,
    and it is drawn on a track, the handle centred with air on both sides."""

    def styleHint(self, hint, option=None, widget=None, return_data=None):
        if hint == QStyle.StyleHint.SH_ScrollBar_Transient:
            return 0 if in_gutter(widget) else 1
        return super().styleHint(hint, option, widget, return_data)

    def pixelMetric(self, metric, option=None, widget=None):
        if metric == QStyle.PixelMetric.PM_ScrollBarExtent and in_gutter(widget):
            return theme.SCROLL_W + 2 * GUTTER_PAD
        if metric in (QStyle.PixelMetric.PM_ScrollBarExtent,
                      QStyle.PixelMetric.PM_ScrollView_ScrollBarOverlap):
            return theme.SCROLL_W + 2 * SCROLL_EDGE
        if metric == QStyle.PixelMetric.PM_ScrollBarSliderMin:
            return SLIDER_MIN
        return super().pixelMetric(metric, option, widget)

    def subControlRect(self, control, option, sub, widget=None):
        if control != QStyle.ComplexControl.CC_ScrollBar or not isinstance(option,
                                                                            QStyleOptionSlider):
            return super().subControlRect(control, option, sub, widget)
        r = option.rect
        horizontal = option.orientation == Qt.Orientation.Horizontal
        if sub == SC.SC_ScrollBarGroove:
            return QRect(r)
        if sub not in (SC.SC_ScrollBarSlider, SC.SC_ScrollBarAddPage, SC.SC_ScrollBarSubPage):
            return QRect()    # no arrows, no first/last buttons
        length = r.width() if horizontal else r.height()
        span = option.maximum - option.minimum
        if span > 0:
            handle = max(SLIDER_MIN, length * option.pageStep // (span + option.pageStep))
            handle = min(handle, length)
            pos = QStyle.sliderPositionFromValue(option.minimum, option.maximum,
                                                 option.sliderPosition, length - handle,
                                                 option.upsideDown)
        else:
            handle, pos = length, 0
        if horizontal:
            slider = QRect(r.x() + pos, r.y(), handle, r.height())
            before = QRect(r.x(), r.y(), pos, r.height())
            after = QRect(r.x() + pos + handle, r.y(), length - pos - handle, r.height())
        else:
            slider = QRect(r.x(), r.y() + pos, r.width(), handle)
            before = QRect(r.x(), r.y(), r.width(), pos)
            after = QRect(r.x(), r.y() + pos + handle, r.width(), length - pos - handle)
        return {SC.SC_ScrollBarSlider: slider, SC.SC_ScrollBarSubPage: before,
                SC.SC_ScrollBarAddPage: after}[sub]

    def drawComplexControl(self, control, option, painter, widget=None):
        if control != QStyle.ComplexControl.CC_ScrollBar or not isinstance(option,
                                                                            QStyleOptionSlider):
            return super().drawComplexControl(control, option, painter, widget)
        if option.maximum <= option.minimum:
            return
        slider = QRectF(self.subControlRect(control, option, SC.SC_ScrollBarSlider, widget))
        active = bool(option.state & QStyle.StateFlag.State_MouseOver) or bool(
            option.state & QStyle.StateFlag.State_Sunken)
        thick = theme.SCROLL_W + (2 if active else 0)
        horizontal = option.orientation == Qt.Orientation.Horizontal
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        if in_gutter(widget):
            # the track, the bar's whole length, and the handle centred on it
            groove = QRectF(option.rect)
            if horizontal:
                track = QRectF(groove.x() + SCROLL_EDGE, groove.center().y() - thick / 2,
                               groove.width() - 2 * SCROLL_EDGE, thick)
                handle = QRectF(slider.x() + SCROLL_EDGE, track.y(),
                                slider.width() - 2 * SCROLL_EDGE, thick)
            else:
                track = QRectF(groove.center().x() - thick / 2, groove.y() + SCROLL_EDGE,
                               thick, groove.height() - 2 * SCROLL_EDGE)
                handle = QRectF(track.x(), slider.y() + SCROLL_EDGE,
                                thick, slider.height() - 2 * SCROLL_EDGE)
            painter.setBrush(theme.color("BORDER"))
            painter.drawRoundedRect(track, thick / 2, thick / 2)
        elif horizontal:
            handle = QRectF(slider.x() + SCROLL_EDGE, slider.bottom() - SCROLL_EDGE - thick,
                            slider.width() - 2 * SCROLL_EDGE, thick)
        else:
            handle = QRectF(slider.right() - SCROLL_EDGE - thick, slider.y() + SCROLL_EDGE,
                            thick, slider.height() - 2 * SCROLL_EDGE)
        painter.setBrush(theme.color("TEXT" if active else "MUTED"))
        painter.drawRoundedRect(handle, thick / 2, thick / 2)
        painter.restore()


class ScrollFade(QObject):
    """Every overlay scrollbar fades out when nothing has moved for a moment
    and comes back on a wheel turn, a scroll, or the pointer entering its
    area; the pointer on the bar itself keeps it there. A gutter bar does
    not fade: it has a column of its own and nothing to get out of the way of."""

    def __init__(self, app) -> None:
        super().__init__(app)
        self._bars: dict[QScrollBar, tuple] = {}
        app.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        t = event.type()
        if isinstance(obj, QScrollBar):
            if t in (QEvent.Type.Show, QEvent.Type.Polish):
                self._attach(obj)
                self._wake(obj)
            elif t in (QEvent.Type.Enter, QEvent.Type.HoverEnter, QEvent.Type.HoverMove,
                       QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove):
                self._wake(obj, hold=True)
            elif t in (QEvent.Type.Leave, QEvent.Type.HoverLeave,
                       QEvent.Type.MouseButtonRelease):
                self._wake(obj)
        elif t in (QEvent.Type.Wheel, QEvent.Type.Enter) and isinstance(obj, QWidget):
            area = self._area_of(obj)
            if area is not None:
                for bar in (area.verticalScrollBar(), area.horizontalScrollBar()):
                    if bar.isVisible():
                        self._attach(bar)
                        self._wake(bar)
        return False

    @staticmethod
    def _area_of(widget: QWidget) -> QAbstractScrollArea | None:
        w = widget
        while w is not None:
            if isinstance(w, QAbstractScrollArea):
                return w
            w = w.parentWidget()
        return None

    def _attach(self, bar: QScrollBar) -> None:
        if bar in self._bars or in_gutter(bar):   # a gutter bar stays: it has the room
            return
        fx = QGraphicsOpacityEffect(bar)
        fx.setOpacity(1.0)
        bar.setGraphicsEffect(fx)
        anim = QPropertyAnimation(fx, b"opacity", bar)
        anim.setDuration(SCROLL_FADE_MS)
        timer = QTimer(bar)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda b=bar: self._rest(b))
        bar.valueChanged.connect(lambda _v, b=bar: self._wake(b))
        bar.destroyed.connect(lambda _o=None, b=bar: self._bars.pop(b, None))
        self._bars[bar] = (fx, anim, timer)

    def _wake(self, bar: QScrollBar, hold: bool = False) -> None:
        entry = self._bars.get(bar)
        if entry is None:
            return
        fx, anim, timer = entry
        anim.stop()
        fx.setOpacity(1.0)
        if hold:
            timer.stop()
        else:
            timer.start(SCROLL_IDLE_MS)

    def _rest(self, bar: QScrollBar) -> None:
        entry = self._bars.get(bar)
        if entry is None or bar.underMouse():
            return
        fx, anim, _timer = entry
        anim.stop()
        anim.setStartValue(fx.opacity())
        anim.setEndValue(SCROLL_RESTING)
        anim.start()

    def opacity(self, bar: QScrollBar) -> float:
        entry = self._bars.get(bar)
        return entry[0].opacity() if entry else 1.0


_installed: dict = {}    # the application's ScrollFade, once there is one


def install(app) -> ScrollFade:
    """Overlay scrollbars for the whole application. Called once, before the
    stylesheet goes on: the proxy wraps a fresh copy of the platform's style,
    and the stylesheet style wraps the proxy in turn."""
    if "fade" not in _installed:
        base = QStyleFactory.create(app.style().objectName())
        app.setStyle(OverlayScrollStyle(base) if base is not None else OverlayScrollStyle())
        _installed["fade"] = ScrollFade(app)
    return _installed["fade"]
