"""Three sections with every process shown: Apps, Background processes,
System processes, placed by cgroup, by owner only when the cgroup could not
be read. Grouped and Flat get them; Tree keeps its hierarchy. Section rows
keep their order under any sort, hide when empty, cannot be selected, and
remember whether they were closed."""
from __future__ import annotations

import os
import tempfile
import unittest

from archpm import sections
from archpm.model import ProcSample, Snapshot, SystemSample
from archpm.root import helper

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import QSettings, Qt
    from PySide6.QtWidgets import QApplication
except ImportError:                       # pragma: no cover
    QApplication = None

USER = "/user.slice/user-1000.slice/user@1000.service"
BRAVE = f"{USER}/app.slice/app-brave\\x2dbrowser@1.service"
KWALLET = f"{USER}/app.slice/dbus-:1.2-org.kde.kwalletd6@0.service"


class Placement(unittest.TestCase):
    def test_by_cgroup(self):
        cases = {
            f"{USER}/app.slice/app-org.chromium.Chromium-4558.scope": sections.APPS,
            BRAVE: sections.APPS,
            f"{USER}/app.slice/app-steam@1.service/child": sections.APPS,
            f"{USER}/app.slice/archpm-agent.service": sections.BACKGROUND,
            f"{USER}/session.slice/plasma-kwin_wayland.service": sections.BACKGROUND,
            f"{USER}/init.scope": sections.BACKGROUND,
            KWALLET: sections.BACKGROUND,
            "/user.slice/user-1000.slice/session-2.scope": sections.BACKGROUND,
            "/system.slice/sddm.service": sections.SYSTEM,
            "/system.slice/system-getty.slice/getty@tty1.service": sections.SYSTEM,
            "/init.scope": sections.SYSTEM,
            "/": sections.SYSTEM,          # a kernel thread
        }
        for cgroup, want in cases.items():
            with self.subTest(cgroup=cgroup):
                self.assertEqual(sections.section_of(cgroup, 1000), (want, False))

    def test_fallback_by_owner_only_without_a_cgroup(self):
        self.assertEqual(sections.section_of("", 0), (sections.SYSTEM, True))
        self.assertEqual(sections.section_of("", 999), (sections.SYSTEM, True))
        self.assertEqual(sections.section_of("", 1000), (sections.BACKGROUND, True))
        self.assertEqual(sections.section_of("", -1), (sections.BACKGROUND, True))
        self.assertEqual(sections.section_of("", 500, uid_floor=500), (sections.BACKGROUND, True))

    def test_an_app_name_is_not_a_category(self):
        for _, label, _ in sections.SECTIONS:
            self.assertNotIn("ategor", label)


class CgroupLine(unittest.TestCase):
    def test_split_at_the_second_colon_keeps_a_dbus_unit_whole(self):
        self.assertEqual(sections.cgroup_path("0::" + KWALLET + "\n"), KWALLET)
        self.assertEqual(sections.cgroup_path("0::/\n"), "/")
        self.assertEqual(sections.cgroup_path(""), "")
        self.assertEqual(sections.cgroup_path("1:name=systemd:/x\n0::/y\n"), "/y")

    def test_the_helper_reads_it_the_same_way(self):
        self.assertIn("dbus-:1.2-org.kde.kwalletd6@0.service", helper.units_in("0::" + KWALLET))
        self.assertIn("user@1000.service", helper.units_in("0::" + KWALLET))
        self.assertEqual(helper.units_in("0::/\n"), set())


def proc(pid, name, cgroup, uid=1000, ppid=1, cpu=0.0):
    return ProcSample(pid=pid, ppid=ppid, name=name, cgroup=cgroup, uid=uid, username="u",
                      owned=uid == 1000, cmdline=f"/usr/bin/{name}", argv=(f"/usr/bin/{name}",),
                      cpu_percent=cpu, program=True)


PROCS = [
    proc(1, "systemd", "/init.scope", uid=0),
    proc(2, "kthreadd", "/", uid=0),
    proc(892, "sddm", "/system.slice/sddm.service", uid=0, cpu=1.0),
    proc(4558, "brave", BRAVE, cpu=30.0),
    proc(4573, "brave", BRAVE, ppid=4558, cpu=5.0),
    proc(8905, "python3", f"{USER}/app.slice/archpm-agent.service", cpu=2.0),
    proc(7000, "kwalletd6", KWALLET),
    proc(9999, "mystery", "", uid=0),         # cgroup unreadable: placed by owner
]


@unittest.skipUnless(QApplication, "PySide6 not installed")
class ModelRows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
            QSettings.setPath(fmt, QSettings.Scope.UserScope, cls.tmp.name)
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def view(self, mode, show_all=True):
        from archpm.actions import UserBackend
        from archpm.ui.procview import ProcessView
        v = ProcessView(8, UserBackend())
        v.show()
        v.cb_all.setChecked(show_all)
        v.set_mode(mode)
        v.update_view(Snapshot(system=SystemSample(), procs=PROCS))
        return v

    def roots(self, v):
        return [v.proxy.index(r, 1).data() for r in range(v.proxy.rowCount())]

    def under(self, v, key):
        idx = v.proxy.mapFromSource(v.model.index_for_pid(sections.SECTION_PID[key]))
        return sorted(v.proxy.index(r, 1, idx).data() for r in range(v.proxy.rowCount(idx)))

    def test_flat_has_three_sections_with_counts(self):
        v = self.view("flat")
        # pid 1 sits in /init.scope, which is the system's; the two brave
        # processes are the app; the agent and kwalletd6 are the session's rest
        self.assertEqual(self.roots(v), ["Apps (2)", "Background processes (2)",
                                         "System processes (4)"])
        self.assertEqual(self.under(v, "apps"), ["brave", "brave"])
        self.assertEqual(self.under(v, "background"), ["kwalletd6", "python3"])
        self.assertEqual(self.under(v, "system"), ["kthreadd", "mystery", "sddm", "systemd"])
        self.assertEqual(v.model.fallbacks, 1, "mystery: owner uid 0, no cgroup")

    def test_grouped_puts_the_group_row_under_apps_and_counts_rows_not_processes(self):
        v = self.view("grouped")
        self.assertEqual(self.roots(v)[0], "Apps (1)", "one program, whatever its processes")
        self.assertEqual(self.under(v, "apps"), ["brave (2)"], "closed: the name with its count")
        gid = next(pid for pid, n in v.model._nodes.items()
                   if pid < 0 and not sections.is_section(pid) and n.proc.members)
        v.table.expand(v.proxy.mapFromSource(v.model.index_for_pid(gid)))
        self.assertEqual(self.under(v, "apps"), ["brave"], "open: the rows are visible")
        v.table.collapse(v.proxy.mapFromSource(v.model.index_for_pid(gid)))
        self.assertEqual(self.under(v, "apps"), ["brave (2)"])
        tip = v.proxy.mapFromSource(v.model.index_for_pid(sections.SECTION_PID["apps"])).data(
            Qt.ItemDataRole.ToolTipRole)
        self.assertIn("1 rows here, 2 processes in all", tip)

    def test_tree_keeps_its_hierarchy(self):
        v = self.view("tree")
        self.assertFalse(any(name.endswith(")") and "processes" in name for name in self.roots(v)))
        self.assertEqual(v.model.section_counts(), {})

    def test_off_means_exactly_as_before(self):
        v = self.view("flat", show_all=False)
        self.assertEqual(v.model.section_counts(), {})
        self.assertNotIn("Apps (2)", self.roots(v))

    def test_order_is_fixed_under_any_sort(self):
        from archpm.ui.proc_model import COL_CPU
        v = self.view("flat")
        v.table.sortByColumn(COL_CPU, Qt.SortOrder.DescendingOrder)
        self.assertEqual([r.split(" (")[0] for r in self.roots(v)],
                         ["Apps", "Background processes", "System processes"])
        v.table.sortByColumn(COL_CPU, Qt.SortOrder.AscendingOrder)
        self.assertEqual([r.split(" (")[0] for r in self.roots(v)],
                         ["Apps", "Background processes", "System processes"])

    def test_an_empty_section_is_hidden(self):
        v = self.view("flat")
        v.cb_gpu.setChecked(True)   # nothing here uses the GPU: every section empties
        self.assertEqual(v.proxy.rowCount(), 0)

    def test_a_section_row_cannot_be_selected(self):
        v = self.view("flat")
        idx = v.model.index_for_pid(sections.SECTION_PID["apps"])
        self.assertFalse(v.model.flags(idx) & Qt.ItemFlag.ItemIsSelectable)
        self.assertEqual(v._selected(), [])

    def test_closed_sections_are_remembered(self):
        v = self.view("flat")
        idx = v.proxy.mapFromSource(v.model.index_for_pid(sections.SECTION_PID["system"]))
        self.assertTrue(v.table.isExpanded(idx), "open by default")
        v.table.collapse(idx)
        self.assertEqual(v.settings.value("collapsed_sections", "", type=str), "system")
        v.update_view(Snapshot(system=SystemSample(), procs=PROCS))
        self.assertFalse(v.table.isExpanded(idx), "stays closed on the next tick")
        w = self.view("flat")
        idx = w.proxy.mapFromSource(w.model.index_for_pid(sections.SECTION_PID["system"]))
        self.assertFalse(w.table.isExpanded(idx), "and in a new view")
        w.table.expand(idx)
        self.assertEqual(w.settings.value("collapsed_sections", "", type=str), "")


if __name__ == "__main__":
    unittest.main()
