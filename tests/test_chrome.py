"""The window's chrome, stage three of the GNOME look: a header bar in
place of the status bar, a toast for the transient messages, flat header
controls, a blue focus ring, overlay scrollbars, and a window that can be
made narrow. Offscreen."""
from __future__ import annotations

import os
import re
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import QPoint, QSettings, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import (
        QApplication,
        QLabel,
        QLineEdit,
        QPushButton,
        QScrollArea,
        QStatusBar,
        QVBoxLayout,
        QWidget,
    )
except ImportError:                       # pragma: no cover
    QApplication = None

from archpm.ui import theme

NARROW = 640   # the window may be made this narrow; see test_the_window_can_be_narrow


def rules(pattern: str) -> list[tuple[str, str]]:
    """(selector, body) for every rule of the template whose selector matches;
    the {TOKEN} placeholders are folded so the braces of the rules stand alone."""
    flat = re.sub(r"/\*.*?\*/", "", theme.STYLE_TEMPLATE, flags=re.S)
    flat = re.sub(r"\{([A-Z_]+)\}", r"@\1@", flat).replace("{{", "{").replace("}}", "}")
    return [(sel.strip(), body) for sel, body in re.findall(r"([^{}]*)\{([^}]*)\}", flat)
            if re.search(pattern, sel)]


def app_and_settings():
    tmp = tempfile.TemporaryDirectory()
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, tmp.name)
    app = QApplication.instance() or QApplication([])
    return app, tmp


@unittest.skipUnless(QApplication, "PySide6 not installed")
class Window(unittest.TestCase):
    """One MainWindow for the class: it starts a sampler thread."""

    @classmethod
    def setUpClass(cls):
        cls.app, cls.tmp = app_and_settings()
        from archpm.ui import chrome
        chrome.install(cls.app)
        theme.apply(cls.app, "dark")
        from archpm.ui.app import MainWindow
        cls.win = MainWindow()
        cls.win.resize(1200, 700)
        cls.win.show()
        QTest.qWait(50)

    @classmethod
    def tearDownClass(cls):
        cls.win.shutdown()
        cls.win.close()
        cls.tmp.cleanup()

    def test_no_status_bar_and_a_header_bar_above_the_pages(self):
        self.assertIsNone(self.win.findChild(QStatusBar))
        header = self.win.header
        self.assertEqual(header.height(), theme.HEADER_H)
        self.assertEqual(header.objectName(), "headerbar")
        # above the pages, to the right of the rail's placeholder
        self.assertEqual(header.y(), 0)
        self.assertEqual(header.x(), self.win.shell.placeholder.width())
        self.assertEqual(self.win.shell.pages.y(), theme.HEADER_H)
        for control in (self.win.combo_theme, self.win.combo):
            self.assertIs(control.parentWidget().parentWidget(), header)

    def test_the_title_is_the_page_and_sits_at_the_centre(self):
        self.win.shell.set_current(0)
        QTest.qWait(10)
        self.assertEqual(self.win.header.title.text(), "Overview")
        self.assertTrue(self.win.header.centred())
        self.win.shell.set_current(self.win.procs)
        QTest.qWait(10)
        self.assertEqual(self.win.header.title.text(), "Processes")
        self.win.shell.set_current(0)

    def test_transient_messages_are_a_toast_that_fades(self):
        toast = self.win.toast
        self.win._flash("Root actions enabled", 600)
        QTest.qWait(250)                  # the fade-in is done
        self.assertTrue(toast.isVisible())
        self.assertEqual(toast.showing(), "Root actions enabled")
        shell = self.win.shell
        self.assertLess(toast.geometry().bottom(), shell.height())
        content = shell.width() - shell.placeholder.width()
        self.assertAlmostEqual(toast.geometry().center().x(),
                               shell.placeholder.width() + content // 2, delta=2)
        # painted, and still on top after a page switch
        self.assertEqual(self.win.grab().toImage().pixelColor(
            toast.geometry().topLeft() + QPoint(12, toast.height() // 2)).name(), theme.OSD)
        self.win.shell.set_current(self.win.procs)
        QTest.qWait(20)
        self.assertEqual(self.win.grab().toImage().pixelColor(
            toast.geometry().topLeft() + QPoint(12, toast.height() // 2)).name(), theme.OSD)
        self.win.shell.set_current(0)
        QTest.qWait(900)
        self.assertFalse(toast.isVisible())
        self.assertEqual(toast.showing(), "")

    def test_a_new_message_replaces_the_one_showing(self):
        self.win._flash("first", 2000)
        QTest.qWait(30)
        self.win._flash("second", 100)
        QTest.qWait(30)
        self.assertEqual(self.win.toast.showing(), "second")
        QTest.qWait(600)
        self.assertFalse(self.win.toast.isVisible())

    def test_every_page_status_goes_to_the_toast(self):
        self.win.procs.status.emit("Terminate: 1 process(es)")
        QTest.qWait(30)
        self.assertEqual(self.win.toast.showing(), "Terminate: 1 process(es)")
        self.win.toast.dismiss()
        QTest.qWait(400)

    def test_the_window_can_be_narrow(self):
        """The floor was 1163 px: the Processes toolbar and the Help page's
        head on one row each. Now every page is usable at NARROW, and the
        Overview never scrolls sideways."""
        self.assertLessEqual(self.win.minimumSizeHint().width(), NARROW)
        self.assertLess(self.win.minimumSizeHint().height(), 700)
        overview = self.win.shell.pages.widget(0)
        self.assertIsInstance(overview, QScrollArea)
        self.assertEqual(overview.horizontalScrollBarPolicy(),
                         Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.assertGreaterEqual(overview.minimumSizeHint().width(),
                                self.win.dashboard.minimumSizeHint().width())

    def test_narrow_the_toolbars_wrap_and_the_tiles_make_two_rows(self):
        self.win.resize(NARROW, 700)
        QTest.qWait(50)
        self.assertLessEqual(self.win.width(), NARROW)
        self.assertEqual(self.win.dashboard.tiles.columns(), 3)
        self.win.shell.set_current(self.win.procs)
        QTest.qWait(30)
        bar = self.win.procs.search.parentWidget().layout().itemAt(0).layout()
        self.assertGreaterEqual(bar.rows(), 2)
        self.assertEqual(self.win.procs.search.x(), theme.PAGE_MARGIN, "the row starts left")
        self.win.resize(1200, 700)
        QTest.qWait(50)
        self.assertEqual(bar.rows(), 1)
        self.win.shell.set_current(0)      # a hidden page is laid out when shown again
        QTest.qWait(50)
        self.assertEqual(self.win.dashboard.tiles.columns(), 6)

    def test_overlay_scrollbars_take_no_width(self):
        """A scroll area with a vertical scrollbar keeps its full width for
        the viewport; the bar lies over the content and fades when idle."""
        from archpm.ui import chrome
        area = QScrollArea()
        inner = QWidget()
        lay = QVBoxLayout(inner)
        for i in range(60):
            lay.addWidget(QLabel(f"line {i}"))
        area.setWidget(inner)
        area.resize(300, 200)
        area.show()
        QTest.qWait(30)
        bar = area.verticalScrollBar()
        self.assertTrue(bar.isVisible())
        self.assertEqual(area.viewport().width(), area.width() - 2 * area.frameWidth())
        self.assertGreaterEqual(bar.mapTo(area, bar.rect().topLeft()).x(),
                                area.width() - bar.width() - 4)
        fade = chrome.install(self.app)
        self.assertEqual(fade.opacity(bar), 1.0)
        QTest.qWait(chrome.SCROLL_IDLE_MS + chrome.SCROLL_FADE_MS + 100)
        self.assertEqual(fade.opacity(bar), chrome.SCROLL_RESTING)
        bar.setValue(bar.value() + 10)
        self.assertEqual(fade.opacity(bar), 1.0)
        area.close()


@unittest.skipUnless(QApplication, "PySide6 not installed")
class Focus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app, cls.tmp = app_and_settings()
        theme.apply(cls.app, "dark")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_focus_is_a_2px_ring_in_the_second_blue_everywhere(self):
        """No :focus rule paints the accent; each one draws FOCUS_W of FOCUS."""
        focus = rules(":focus")
        self.assertGreaterEqual(len(focus), 5)
        for selector, body in focus:
            with self.subTest(selector=selector):
                self.assertNotIn("ACCENT", body)
                self.assertIn("@FOCUS_W@px solid @FOCUS@", body)
        self.assertEqual(theme.FOCUS_W, 2)
        for table in (theme.DARK, theme.LIGHT):
            self.assertNotEqual(table["FOCUS"], table["SELECT"], "not the selection colour")

    def test_a_focused_control_keeps_its_size(self):
        host = QWidget()
        lay = QVBoxLayout(host)
        e, b = QLineEdit(), QPushButton("Refresh")
        lay.addWidget(e)
        lay.addWidget(b)
        host.show()
        QTest.qWait(10)
        for w in (e, b):
            with self.subTest(widget=type(w).__name__):
                before = w.sizeHint()
                w.setFocus()
                QTest.qWait(10)
                self.assertTrue(w.hasFocus())
                self.assertEqual(w.sizeHint(), before)
        host.close()

    def test_the_text_link_ring_is_the_focus_blue(self):
        from archpm.ui.widgets import TextLink
        link = TextLink()
        link.set_link("2 services failed", "WARN")
        link.resize(160, 24)
        link.show()
        link.setFocus()
        QTest.qWait(20)
        img = link.grab().toImage()
        edge = {img.pixelColor(x, 1).name() for x in range(8, 150)}
        self.assertIn(theme.FOCUS, edge)
        link.close()

    def test_header_controls_are_flat_until_hovered(self):
        header = rules("#headerbar")
        rest = next(v for k, v in header if "QComboBox" in k and ":" not in k)
        self.assertIn("background: transparent", rest)
        self.assertIn("border: 1px solid transparent", rest)
        hover = next(v for k, v in header if "QComboBox:hover" in k)
        self.assertIn("border-color: @BORDER_HI@", hover)

    def test_no_stylesheet_box_on_scrollbars(self):
        """A scrollbar with a stylesheet box is never transient to Qt."""
        self.assertEqual(rules("QScrollBar"), [])


@unittest.skipUnless(QApplication, "PySide6 not installed")
class Flow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app, cls.tmp = app_and_settings()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def make(self, width: int):
        from archpm.ui.widgets import FlowLayout
        host = QWidget()
        flow = FlowLayout(host, spacing=10)
        self.title = QLabel("What starts when you log in")
        flow.addWidget(self.title)
        flow.addStretch()
        self.buttons = [QPushButton(t) for t in ("Show entries for other desktops", "Refresh")]
        for b in self.buttons:
            flow.addWidget(b)
        host.resize(width, 200)
        host.show()
        QTest.qWait(10)
        return host, flow

    def test_one_row_with_the_controls_on_the_right_when_it_fits(self):
        host, flow = self.make(700)
        self.assertEqual(flow.rows(), 1)
        self.assertEqual(self.buttons[-1].geometry().right(), 699)
        self.assertEqual(self.title.x(), 0)
        host.close()

    def test_wraps_when_it_does_not_and_the_minimum_is_the_widest_item(self):
        host, flow = self.make(320)
        self.assertGreaterEqual(flow.rows(), 2)
        self.assertEqual(self.buttons[0].x(), 0)
        self.assertGreater(self.buttons[0].y(), self.title.y())
        widest = max(w.minimumSizeHint().width() for w in [self.title] + self.buttons)
        self.assertEqual(flow.minimumSize().width(), widest)
        self.assertGreater(flow.heightForWidth(320), flow.heightForWidth(700))
        host.close()


@unittest.skipUnless(QApplication, "PySide6 not installed")
class Tiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app, cls.tmp = app_and_settings()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_six_across_or_two_rows_of_three(self):
        from archpm.ui.widgets import StatTile, TileRow
        tiles = [StatTile(f"tile {i}") for i in range(6)]
        row = TileRow(tiles, 12)
        row.resize(1000, 100)
        row.show()
        QTest.qWait(10)
        self.assertEqual(row.columns(), 6)
        self.assertEqual(len({t.y() for t in tiles}), 1)
        row.resize(row.minimumSizeHint().width(), 200)
        QTest.qWait(10)
        self.assertEqual(row.columns(), 3)
        self.assertEqual(len({t.y() for t in tiles}), 2)
        widths = {t.width() for t in tiles}
        self.assertLessEqual(max(widths) - min(widths), 1, "equal widths")
        self.assertEqual(row.width(), row.minimumSizeHint().width())
        row.close()
