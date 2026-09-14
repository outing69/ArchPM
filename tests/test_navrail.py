"""The navigation rail: collapsed by default, overlay on hover, pinned by the
hamburger and remembered, reachable by keyboard. Offscreen; icons may be null
there, which is fine, the theme lookup is checked on the real platform."""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import QSettings, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLabel
except ImportError:                       # pragma: no cover
    QApplication = None

LABELS = ["Overview", "Processes", "Network", "Startup", "System", "Cleanup", "Help"]


@unittest.skipUnless(QApplication, "PySide6 not installed")
class Rail(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
            QSettings.setPath(fmt, QSettings.Scope.UserScope, cls.tmp.name)
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        from archpm.ui.navrail import NavShell
        self.settings = QSettings("archpm", "ArchPM")
        self.settings.remove("nav_pinned")
        self.shell = NavShell(self.settings)
        for label in LABELS:
            self.shell.add_page(QLabel(label), label)
        self.shell.resize(900, 600)
        self.shell.show()
        self.rail = self.shell.rail

    def test_collapsed_by_default_with_icon_only_items_and_tooltips(self):
        from archpm.ui.navrail import COLLAPSED
        self.assertFalse(self.rail.pinned)
        self.assertEqual(self.rail.width(), COLLAPSED)
        self.assertEqual(self.shell.placeholder.width(), COLLAPSED)
        self.assertEqual([b.text() for b in self.rail.items], LABELS)
        for b in self.rail.items:
            self.assertEqual(b.toolButtonStyle(), Qt.ToolButtonStyle.ToolButtonIconOnly)
            self.assertEqual(b.toolTip(), b.text())
        self.assertEqual(self.rail.menu.toolTip(), "Pin the menu open")

    def test_hover_expands_as_an_overlay_without_moving_the_page(self):
        from archpm.ui.navrail import COLLAPSED, EXPANDED
        page_x = self.shell.pages.geometry().x()
        self.rail.set_expanded(True)
        self.assertEqual(self.rail.width(), EXPANDED)
        self.assertEqual(self.shell.placeholder.width(), COLLAPSED)
        self.app.processEvents()
        self.assertEqual(self.shell.pages.geometry().x(), page_x, "the page did not reflow")
        for b in self.rail.items:
            self.assertEqual(b.toolButtonStyle(), Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            self.assertEqual(b.toolTip(), "", "label is visible, no tooltip needed")
        self.rail.set_expanded(False)
        self.assertEqual(self.rail.width(), COLLAPSED)

    def test_pinning_gives_the_rail_real_width_and_is_remembered(self):
        from archpm.ui.navrail import EXPANDED, NavShell
        self.rail.menu.click()
        self.assertTrue(self.rail.pinned)
        self.assertEqual(self.shell.placeholder.width(), EXPANDED)
        self.assertEqual(self.rail.width(), EXPANDED)
        self.assertEqual(self.rail.menu.toolTip(), "Unpin the menu")
        self.assertTrue(self.settings.value("nav_pinned", type=bool))
        self.rail.set_expanded(False)
        self.assertEqual(self.rail.width(), EXPANDED, "hover cannot collapse a pinned rail")
        again = NavShell(QSettings("archpm", "ArchPM"))
        self.assertTrue(again.rail.pinned, "restored on the next start")
        self.assertEqual(again.placeholder.width(), EXPANDED)
        self.rail.menu.click()
        self.assertFalse(self.settings.value("nav_pinned", type=bool))

    def test_clicking_an_item_switches_the_page_and_the_other_way_round(self):
        self.rail.items[2].click()
        self.assertEqual(self.shell.pages.currentIndex(), 2)
        self.shell.set_current(self.shell.pages.widget(5))
        self.assertEqual(self.rail.current(), 5)
        self.assertTrue(self.rail.items[5].isChecked())

    def test_keyboard_tab_reaches_it_and_arrows_plus_enter_select(self):
        self.assertEqual(self.rail.focusPolicy(), Qt.FocusPolicy.TabFocus)
        self.rail.setFocus()
        self.app.processEvents()
        QTest.keyClick(self.rail, Qt.Key.Key_Down)
        QTest.keyClick(self.rail, Qt.Key.Key_Down)
        self.assertEqual(self.shell.pages.currentIndex(), 0, "moving the cursor selects nothing yet")
        QTest.keyClick(self.rail, Qt.Key.Key_Return)
        self.assertEqual(self.shell.pages.currentIndex(), 2)
        QTest.keyClick(self.rail, Qt.Key.Key_Up)
        QTest.keyClick(self.rail, Qt.Key.Key_Space)
        self.assertEqual(self.shell.pages.currentIndex(), 1)
        QTest.keyClick(self.rail, Qt.Key.Key_End)
        QTest.keyClick(self.rail, Qt.Key.Key_Return)
        self.assertEqual(self.shell.pages.currentIndex(), len(LABELS) - 1)

    def test_the_rail_is_opaque_over_the_page_in_both_states(self):
        from archpm.ui import theme
        from archpm.ui.navrail import COLLAPSED, EXPANDED, NavShell
        shell = NavShell(QSettings("archpm", "ArchPM"))
        page = QLabel("page")
        page.setStyleSheet("background: #ff0000;")
        shell.add_page(page, "Overview")
        shell.add_page(QLabel("Help"), "Help")
        shell.move(400, 400)              # away from the offscreen cursor, so no hover
        shell.resize(800, 500)
        shell.show()
        self.app.processEvents()
        rail = shell.rail
        # Qt's stylesheet engine clears autoFillBackground on polish for a
        # widget whose stylesheet paints the background itself; the styled
        # background attribute is what makes that painting happen, and the
        # pixels below are the proof.
        self.assertTrue(rail.testAttribute(Qt.WidgetAttribute.WA_StyledBackground))
        self.assertIn(f"background: {theme.SURFACE}", rail.styleSheet())

        def pixel(x, y):
            return shell.grab().toImage().pixelColor(x, y).name()
        self.assertEqual(pixel(300, 250), "#ff0000", "the page itself is red")
        self.assertEqual(pixel(COLLAPSED - 6, 250), theme.SURFACE, "collapsed rail paints itself")
        rail.set_expanded(True)
        self.app.processEvents()
        for x in (COLLAPSED + 10, EXPANDED - 10):
            self.assertEqual(pixel(x, 250), theme.SURFACE, f"expanded rail is opaque at x={x}")
        self.assertEqual(pixel(EXPANDED + 10, 250), "#ff0000", "and the page shows next to it")

    def test_every_item_has_an_accessible_name(self):
        self.assertEqual([b.accessibleName() for b in self.rail.items], LABELS)
        self.assertEqual(self.rail.menu.accessibleName(), "Menu")
        self.assertEqual(self.rail.accessibleName(), "Navigation")

    def test_icon_falls_back_to_the_second_name(self):
        from archpm.ui.navrail import PAGE_ICONS, pick_icon_name
        self.assertEqual(pick_icon_name("missing", "present", has=lambda n: n == "present"), "present")
        self.assertEqual(pick_icon_name("present", "other", has=lambda n: n == "present"), "present")
        for label in LABELS:
            name, fallback = PAGE_ICONS[label]
            self.assertTrue(name and fallback and name != fallback, label)


if __name__ == "__main__":
    unittest.main()
