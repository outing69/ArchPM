"""Boxed lists, stage three of the GNOME look, second part: Startup,
Cleanup and System show grouped information as rows in a rounded box with a
line between them, a switch where a state is set and a check box where an
item is picked. Offscreen; skipped where PySide6 is missing."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import QSettings, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QCheckBox

    from archpm.ui import theme
except ImportError:                       # pragma: no cover
    QApplication = theme = None

from archpm.autostart import StartupEntry
from archpm.cleanup import CleanupItem
from archpm.failed import FailedReport, FailedUnit


def app_and_settings():
    tmp = tempfile.TemporaryDirectory()
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, tmp.name)
    app = QApplication.instance() or QApplication([])
    theme.apply(app, "dark")
    return app, tmp


def entry(name, kind="App", enabled=True, this_desktop=True):
    path = Path(f"/tmp/{name}.desktop")
    return StartupEntry(id=name.lower(), name=name, icon="", exec=f"/usr/bin/{name.lower()}",
                        path=path, system_path=None, user_path=path, enabled=enabled,
                        for_this_desktop=this_desktop, description=f"{name} does things",
                        kind=kind)


@unittest.skipUnless(QApplication, "PySide6 not installed")
class Widgets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app, cls.tmp = app_and_settings()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_a_switch_flips_on_click_and_space_and_says_so_only_then(self):
        from archpm.ui.widgets import Switch
        sw = Switch()
        sw.show()
        heard = []
        sw.toggled.connect(heard.append)
        sw.set_checked(True)
        self.assertTrue(sw.isChecked())
        self.assertEqual(heard, [], "the data setting it is not the user flipping it")
        QTest.mouseClick(sw, Qt.MouseButton.LeftButton)
        self.assertFalse(sw.isChecked())
        QTest.keyClick(sw, Qt.Key.Key_Space)
        self.assertTrue(sw.isChecked())
        self.assertEqual(heard, [False, True])
        self.assertEqual(sw.focusPolicy(), Qt.FocusPolicy.StrongFocus, "Tab reaches it")
        sw.close()

    def test_rows_in_a_box_with_a_line_between_and_the_end_rows_marked(self):
        from archpm.ui.widgets import BoxedList, ListRow
        group = BoxedList("Title", "A description.")
        self.assertFalse(group.box.isVisibleTo(group), "an empty group shows no box")
        rows = [group.add_row(ListRow(f"row {i}", "sub")) for i in range(3)]
        group.show()
        self.assertTrue(group.box.isVisibleTo(group))
        self.assertEqual([r.property("first") for r in rows], [True, False, False])
        self.assertEqual([r.property("last") for r in rows], [False, False, True])
        self.assertEqual(group.box.objectName(), "boxedlist")
        self.assertEqual(rows[1].objectName(), "listrow")
        self.assertGreaterEqual(rows[0].minimumHeight(), theme.LIST_ROW_H)
        group.clear()
        QTest.qWait(10)
        self.assertEqual(group.rows(), [])
        self.assertFalse(group.box.isVisibleTo(group))
        group.close()

    def test_the_stylesheet_draws_the_box_the_lines_and_the_hover(self):
        from tests.test_chrome import rules
        found = dict(rules(r"boxedlist|listrow"))
        self.assertIn("@RADIUS_CARD@px", found["#boxedlist"])
        self.assertIn("border: 1px solid @BORDER@", found["#boxedlist"])
        self.assertIn("border-top: 1px solid @BORDER@", found["#listrow"])
        self.assertIn("border-top: none", found['#listrow[first="true"]'])
        self.assertIn("@SURFACE_HI@", found['#listrow[activatable="true"]:hover'])

    def test_a_row_that_does_something_fires_on_click_and_keeps_its_title(self):
        from archpm.ui.widgets import TITLE_MIN, ListRow, Switch
        sw = Switch()
        row = ListRow("A long title that will be elided when the row is narrow",
                      "and a subtitle", suffix=[sw])
        heard = []
        row.activated.connect(lambda: heard.append(1))
        row.show()
        QTest.mouseClick(row, Qt.MouseButton.LeftButton, pos=row.rect().center())
        self.assertEqual(heard, [], "a plain row does nothing on a click")
        row.set_activatable(True)
        QTest.mouseClick(row, Qt.MouseButton.LeftButton, pos=row.rect().center())
        self.assertEqual(heard, [1])
        self.assertLess(row.minimumSizeHint().width(), 300, "the title elides")
        self.assertGreaterEqual(row.column.minimumWidth(), TITLE_MIN)
        row.close()

    def test_a_property_row_puts_the_name_small_over_the_value(self):
        from archpm.ui.widgets import BoxedList, ListRow
        group = BoxedList("Specs")
        row = group.add_row(ListRow("Kernel", "7.2.5", property=True, mono=True))
        group.show()
        QTest.qWait(10)
        self.assertLess(row.title.font().pointSizeF(), row.subtitle.font().pointSizeF())
        self.assertTrue(row.subtitle.wordWrap())
        self.assertEqual(row.subtitle.font().family().lower(), "monospace",
                         "the font is set through the stylesheet, so it survives the box")
        self.assertTrue(row.subtitle.textInteractionFlags()
                        & Qt.TextInteractionFlag.TextSelectableByMouse)
        group.close()

    def test_groups_stand_in_two_columns_when_wide_and_one_when_narrow(self):
        from archpm.ui.widgets import BoxedList, Columns, ListRow
        cols = Columns(theme.GROUP_GAP, column_min=300)
        groups = []
        for n in (3, 2, 2, 3):
            g = BoxedList(f"{n} rows")
            for i in range(n):
                g.add_row(ListRow(f"k{i}", "v", property=True))
            groups.append((g, n + 1))
        cols.set_groups(groups)
        cols.show()
        cols.resize(900, 600)
        QTest.qWait(10)
        self.assertEqual(cols.columns(), 2)
        left = cols._sides[0].layout()
        self.assertEqual([left.itemAt(i).widget() for i in range(left.count() - 1)],
                         [groups[0][0], groups[1][0]], "the order is kept, half the rows left")
        cols.resize(500, 600)
        QTest.qWait(10)
        self.assertEqual(cols.columns(), 1)
        self.assertLessEqual(cols.minimumSizeHint().width(),
                             max(g.minimumSizeHint().width() for g, _ in groups))
        cols.close()


@unittest.skipUnless(QApplication, "PySide6 not installed")
class Pages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app, cls.tmp = app_and_settings()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_startup_is_a_boxed_list_with_a_switch_per_entry(self):
        from archpm.ui.startup import StartupView
        from archpm.ui.widgets import Switch
        v = StartupView()
        v.auto = mock.Mock()
        v.auto.entries.return_value = [entry("Zed"), entry("Alpha", enabled=False),
                                       entry("Plasma", kind="Desktop"),
                                       entry("Gnomish", this_desktop=False)]
        v._fill_services = lambda: None
        v.reload()
        rows = v.list.rows()
        self.assertEqual([r.title.text() for r in rows],
                         ["Enabled (2)", "Zed", "Plasma", "Disabled (1)", "Alpha"],
                         "enabled first; apps before the desktop's parts; other desktops hidden")
        switches = [r.suffix[-1] for r in rows if r.suffix]
        self.assertTrue(all(isinstance(s, Switch) for s in switches))
        self.assertEqual([s.isChecked() for s in switches], [True, True, False])
        self.assertIn("Desktop · keep on", rows[2].suffix[1].text())
        rows = {r.title.text(): r for r in rows}
        switches = [rows["Alpha"].suffix[-1], rows["Zed"].suffix[-1]]
        # flipping a switch writes the entry and reports it
        said = []
        v.status.connect(said.append)
        switches[0].toggle()
        v.auto.set_enabled.assert_called_once()
        self.assertEqual(v.auto.set_enabled.call_args[0][1], True)
        self.assertEqual(said, ["Alpha will start at login"])
        # a refused desktop entry stays on
        v.list.finish_slide()
        v._confirm_off = lambda e: False
        plasma = {r.title.text(): r for r in v.list.rows()}["Plasma"].suffix[-1]
        plasma.toggle()
        self.assertTrue(plasma.isChecked())
        self.assertEqual(v.auto.set_enabled.call_count, 1)

    def test_switching_off_a_desktop_or_system_entry_asks_and_names_the_loss(self):
        from archpm.ui.startup import StartupView
        v = StartupView()
        v.auto = mock.Mock()
        plasma = entry("Plasma", kind="Desktop")
        plasma.exec = "/usr/bin/plasmashell"
        plasma.id = "org.kde.plasmashell.desktop"
        access = entry("Accessibility", kind="Desktop")
        access.id, access.exec = "kaccess.desktop", "kaccess"
        stranger = entry("Stranger", kind="System")
        stranger.id, stranger.exec = "stranger.desktop", "/opt/stranger/bin/stranger"
        app = entry("Zed")
        v.auto.entries.return_value = [app, stranger, plasma, access]
        v._fill_services = lambda: None
        v.reload()
        # the shared wording, the entry's own line, and what is known of a stranger
        self.assertEqual(v.loss_of(plasma), "the panel, the desktop and its widgets")
        self.assertEqual(v.loss_of(access),
                         "sticky keys, slow keys and the other accessibility features")
        self.assertEqual(v.loss_of(stranger), "what it does: Stranger does things")
        asked = []
        v._confirm_off = lambda e: asked.append(e.name) or False
        rows = {r.title.text(): r for r in v.list.rows()}
        for name in ("Stranger", "Plasma", "Accessibility"):
            rows[name].suffix[-1].toggle()          # off: asks, refused, stays on
            self.assertTrue(rows[name].suffix[-1].isChecked())
        self.assertEqual(asked, ["Stranger", "Plasma", "Accessibility"])
        v.auto.set_enabled.assert_not_called()
        rows["Zed"].suffix[-1].toggle()             # an app: no question
        self.assertEqual(asked, ["Stranger", "Plasma", "Accessibility"])
        self.assertEqual(v.auto.set_enabled.call_count, 1)
        # back on asks nothing, for any kind
        off = entry("Plasma", kind="Desktop", enabled=False)
        off.id, off.exec = plasma.id, plasma.exec
        v.auto.entries.return_value = [off]
        v.reload()
        {r.title.text(): r for r in v.list.rows()}["Plasma"].suffix[-1].toggle()
        self.assertEqual(asked, ["Stranger", "Plasma", "Accessibility"])
        self.assertEqual(v.auto.set_enabled.call_args[0][1], True)

    def test_an_entry_without_an_icon_shows_the_icon_of_its_kind(self):
        from archpm.ui import navrail
        from archpm.ui.startup import StartupView
        v = StartupView()
        v.auto = mock.Mock()
        plain = entry("Plain")
        over = entry("Over", kind="System")
        over.system_path = Path("/etc/xdg/autostart/over.desktop")
        v.auto.entries.return_value = [plain, over, entry("Desk", kind="Desktop")]
        v._fill_services = lambda: None
        v.reload()
        rows = v.list.rows()
        self.assertEqual([v._kind_key(e) for e in v.entries], ["App", "System", "Desktop"]
                         if not over.is_override else ["App", "override", "Desktop"])
        self.assertTrue(over.is_override)
        if navrail.icon_set()["name"] == "adwaita" or navrail.kind_icon("App").isNull():
            pass
        for r in rows:
            if r.prefix is None:
                continue                     # a group header
            pm = r.prefix.pixmap()
            self.assertFalse(pm.isNull(), "the kind's icon fills the slot")
        by_title = {r.title.text(): r for r in rows}
        self.assertEqual(by_title["Over"].prefix.toolTip(),
                         "A system entry with your own copy over it")
        for kind in navrail.KIND_ICONS:
            self.assertFalse(navrail.kind_icon(kind).isNull(), kind)

    def test_a_process_without_an_icon_shows_its_sections_icon(self):
        from archpm.model import ProcSample
        from archpm.ui import navrail
        from archpm.ui.proc_model import COL_NAME, ProcModel
        m = ProcModel(16)
        user = "/user.slice/user-1000.slice/user@1000.service"
        app = ProcSample(pid=10, name="game", cgroup=user + "/app.slice/app-steam-1.scope",
                         uid=1000)
        bg = ProcSample(pid=11, name="daemon", cgroup=user + "/background.slice/x.service",
                        uid=1000)
        sysd = ProcSample(pid=12, name="kthread", cgroup="/", uid=0)
        m.mode = "flat"
        m.update([app, bg, sysd])
        got = {}
        for row in range(m.rowCount()):
            idx = m.index(row, COL_NAME)
            got[m.data(idx, Qt.ItemDataRole.DisplayRole)] = m.data(
                idx, Qt.ItemDataRole.DecorationRole)
        for name, key in (("game", "apps"), ("daemon", "background"), ("kthread", "system")):
            self.assertIsNotNone(got[name], name)
            self.assertEqual(got[name].cacheKey(), navrail.kind_icon(key).cacheKey(), name)

    def _startup(self, names_enabled):
        from archpm.ui.startup import StartupView
        v = StartupView()
        v.auto = mock.Mock()
        v.auto.entries.return_value = [entry(n, enabled=on) for n, on in names_enabled]
        v._fill_services = lambda: None
        v.resize(900, 700)
        v.show()
        QTest.qWait(20)
        return v

    def titles(self, v):
        return [r.title.text() for r in v.list.rows()]

    def test_a_switched_off_row_slides_to_the_disabled_group_and_the_header_lights_up(self):
        v = self._startup([("Alpha", True), ("Beta", True), ("Gamma", False)])
        self.assertEqual(self.titles(v),
                         ["Enabled (2)", "Alpha", "Beta", "Disabled (1)", "Gamma"])
        area = v.findChild(__import__("PySide6.QtWidgets").QtWidgets.QScrollArea)
        before = area.verticalScrollBar().value()
        rows = {r.title.text(): r for r in v.list.rows()}
        rows["Alpha"].suffix[-1].toggle()
        self.assertTrue(v.list.sliding(), "the row is on its way")
        self.assertEqual(self.titles(v)[0], "Enabled (1)", "the counts change at once")
        self.assertTrue(v._headers[False].glowing(), "the Disabled header lights up")
        self.assertEqual(area.verticalScrollBar().value(), before, "the view is not scrolled")
        v.auto.entries.assert_called_once()            # no reload: the row moved
        v.list.finish_slide()
        self.assertEqual(self.titles(v),
                         ["Enabled (1)", "Beta", "Disabled (2)", "Alpha", "Gamma"])
        self.assertFalse(v.list.sliding())
        # and back on, the same way
        rows["Alpha"].suffix[-1].toggle()
        self.assertTrue(v._headers[True].glowing())
        v.list.finish_slide()
        self.assertEqual(self.titles(v),
                         ["Enabled (2)", "Alpha", "Beta", "Disabled (1)", "Gamma"])
        v.close()

    def test_one_slide_at_a_time_and_a_refused_row_stays(self):
        v = self._startup([("Alpha", True), ("Beta", True), ("Gamma", False)])
        rows = {r.title.text(): r for r in v.list.rows()}
        rows["Alpha"].suffix[-1].toggle()
        first = v.list._slide[0]
        rows["Beta"].suffix[-1].toggle()          # while Alpha still moves
        self.assertIsNot(v.list._slide[0], first, "the first is finished, the second runs")
        v.list.finish_slide()
        self.assertEqual(self.titles(v),
                         ["Enabled (0)", "Disabled (3)", "Alpha", "Beta", "Gamma"])
        # a desktop row the user does not confirm does not move
        v.auto.entries.return_value = [entry("Zed", kind="Desktop"), entry("Off", enabled=False)]
        v.reload()
        v._confirm_off = lambda e: False
        v.list.rows()[1].suffix[-1].toggle()
        self.assertFalse(v.list.sliding())
        self.assertEqual(self.titles(v), ["Enabled (1)", "Zed", "Disabled (1)", "Off"])
        v.auto.set_enabled.assert_called()         # from the first part only
        v.close()

    def test_a_slide_moves_the_row_between_two_placeholders(self):
        from archpm.ui.widgets import BoxedList, ListRow
        group = BoxedList("t")
        rows = [group.add_row(ListRow(f"r{i}")) for i in range(4)]
        group.resize(400, 300)
        group.show()
        QTest.qWait(20)
        y0 = rows[0].y()
        height = group.box.height()
        group.slide_row(rows[0], 3)
        anim = group._slide[0]
        anim.pause()
        anim.setCurrentTime(anim.duration() // 2)
        QTest.qWait(5)
        self.assertGreater(rows[0].y(), y0, "half way down")
        self.assertEqual(group.box.height(), height, "the box keeps its height")
        self.assertEqual(group._rows.count(), 5, "three rows and two placeholders")
        group.finish_slide()
        self.assertEqual([r.title.text() for r in group.rows()], ["r1", "r2", "r3", "r0"])
        self.assertTrue(group.rows()[-1].property("last"))
        group.close()

    def test_startup_shows_the_other_desktop_rows_dimmed_when_asked(self):
        from archpm.ui.startup import StartupView
        v = StartupView()
        v.auto = mock.Mock()
        v.auto.entries.return_value = [entry("Zed"), entry("Gnomish", this_desktop=False)]
        v._fill_services = lambda: None
        v.cb_others.setChecked(True)
        rows = [r for r in v.list.rows() if r.suffix]
        self.assertEqual(rows[-1].title.text(), "Gnomish")
        self.assertEqual(rows[-1].suffix[0].text(), "Other desktop")

    def test_cleanup_rows_have_a_check_box_and_the_row_itself_ticks_it(self):
        from archpm.root.client import RootClient
        from archpm.ui.cleanup import CleanupView
        v = CleanupView(RootClient())
        v.scan = lambda: None
        v.items = [CleanupItem(id="a", name="Alpha cache", description="rebuilt", size=1 << 20),
                   CleanupItem(id="b", name="Empty", description="nothing", size=0)]
        v._fill()
        rows = v.list.rows()
        self.assertEqual(len(rows), 2)
        self.assertIsInstance(rows[0].prefix, QCheckBox)
        self.assertTrue(rows[0].property("activatable"))
        self.assertFalse(rows[1].prefix.isEnabled(), "nothing to remove, nothing to tick")
        self.assertFalse(rows[1].property("activatable"))
        rows[0].activated.emit()
        self.assertEqual([i.id for i in v._selected()], ["a"])
        self.assertTrue(v.btn_clean.isEnabled())
        self.assertIn("1 selected", v.lbl_total.text())

    def test_system_shows_specs_as_property_rows_and_failed_units_as_rows(self):
        from archpm.ui.sysinfo import SystemView
        v = SystemView()
        v.reload = lambda: None
        v._loaded([("System", [("Hostname", "box"), ("Kernel", "7.2")]),
                   ("ArchPM", [("Version", "x"), ("Status file", "/run/user/1/s.json")])])
        groups = [g for g, _ in v.columns._groups]
        self.assertEqual([g.title.text() for g in groups], ["System", "ArchPM"])
        self.assertEqual([r.title.text() for r in groups[0].rows()], ["Hostname", "Kernel"])
        self.assertEqual(groups[1].rows()[1].subtitle.text(), "/run/user/1/s.json")
        v.set_failed(FailedReport(units=[], taken_at=0, took_ms=1))
        self.assertEqual(v.failed_list.rows()[0].title.text(), "No failed services found.")
        v.set_failed(FailedReport(units=[FailedUnit(unit="a.service", description="A",
                                                    log=["line 1"], since="Mon")],
                                  taken_at=0, took_ms=1))
        row = v.failed_list.rows()[0]
        self.assertEqual(row.title.text(), "A")
        self.assertIn("a.service", row.subtitle.text())
        self.assertIn("failed since Mon", row.subtitle.text())
        self.assertIs(v.failed_list._suffix, v.btn_failed)

    def test_a_root_row_with_nothing_to_remove_says_so_instead_of_promising_a_prompt(self):
        from archpm.root.client import RootClient
        from archpm.ui.cleanup import CleanupView
        v = CleanupView(RootClient())
        v.scan = lambda: None
        empty = CleanupItem(id="journal", name="System logs", description="", size=0,
                            needs_root=True, helper_item="journal")
        text, colour = v._note_for(empty)
        self.assertEqual((text, colour), ("root · nothing to remove", "MUTED"))
        some = CleanupItem(id="journal", name="System logs", description="", size=1 << 20,
                           needs_root=True, helper_item="journal")
        self.assertIn("asks for your password on Remove", v._note_for(some)[0])
        v.items = [empty, some]
        v._fill()
        rows = v.list.rows()
        self.assertFalse(rows[0].prefix.isEnabled(), "nothing to tick when there is nothing")
        self.assertEqual(rows[0].suffix[0].text(), "root · nothing to remove")
        if v.items[1].helper_item and rows[1].prefix.isEnabled():
            self.assertIn("password", rows[1].suffix[0].text(), "and this one keeps its promise")

    def test_the_groups_control_sits_right_after_its_title(self):
        from archpm.ui.sysinfo import SystemView
        v = SystemView()
        v.reload = lambda: None
        v.show()
        v.resize(1200, 700)
        QTest.qWait(20)
        head = v.failed_list.head.layout()
        self.assertIs(head.itemAt(1).widget(), v.btn_failed)
        title = v.failed_list.title
        self.assertLess(v.btn_failed.x() - (title.x() + title.width()), 20,
                        "next to the title, not at the far right under the page buttons")
        self.assertLess(v.btn_failed.x() + v.btn_failed.width(), v.failed_list.width() // 2)
        v.close()

    def test_a_pages_scrollbar_has_a_gutter_beside_the_page_and_does_not_fade(self):
        from PySide6.QtWidgets import QLabel, QStyle, QVBoxLayout, QWidget

        from archpm.ui import chrome
        chrome.install(self.app)
        tall = QWidget()
        lay = QVBoxLayout(tall)
        for i in range(60):
            lay.addWidget(QLabel(f"row {i}"))
        from archpm.ui.widgets import VScrollArea
        area = VScrollArea(tall)
        area.resize(400, 300)
        area.show()
        QTest.qWait(30)
        bar = area.verticalScrollBar()
        self.assertTrue(bar.isVisible())
        self.assertEqual(self.app.style().styleHint(QStyle.StyleHint.SH_ScrollBar_Transient,
                                                     None, bar), 0)
        from PySide6.QtCore import QPoint
        bar_left = bar.mapTo(area, QPoint(0, 0)).x()
        page_right = area.viewport().mapTo(area, QPoint(0, 0)).x() + area.viewport().width()
        self.assertGreaterEqual(bar_left, page_right, "beside the page, never over it")
        self.assertEqual(bar.width(), theme.SCROLL_W + 2 * chrome.GUTTER_PAD)
        self.assertIsNone(bar.graphicsEffect(), "no fade for a bar with room of its own")
        # a table's bar is still the overlay one
        from PySide6.QtWidgets import QTableWidget
        table = QTableWidget(80, 2)
        table.resize(300, 200)
        table.show()
        QTest.qWait(30)
        tbar = table.verticalScrollBar()
        self.assertEqual(self.app.style().styleHint(QStyle.StyleHint.SH_ScrollBar_Transient,
                                                     None, tbar), 1)
        self.assertLess(tbar.mapTo(table, QPoint(0, 0)).x(),
                        table.viewport().mapTo(table, QPoint(0, 0)).x() + table.viewport().width())
        table.close()
        area.close()

    def test_the_status_file_is_on_the_system_page_and_not_a_toast(self):
        import inspect

        from archpm import sysinfo
        from archpm.publisher import status_path
        from archpm.ui import app as app_module
        rows = dict(sysinfo.archpm_section()[1])
        self.assertEqual(rows["Status file"], str(status_path()))
        self.assertNotIn("status_path", inspect.getsource(app_module),
                         "the window says nothing about the file at start")


if __name__ == "__main__":
    unittest.main()
