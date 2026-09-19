"""Priority, disk priority and affinity on a group row reach its members.

A group row (a browser and its helpers, say) has a negative pid that no
kernel call can take. The view expands it into the processes shown under it;
and whatever goes wrong inside an action is shown, never swallowed.
Needs PySide6 and runs offscreen; skipped where PySide6 is missing.
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import QItemSelectionModel, QSettings
    from PySide6.QtWidgets import QApplication
except ImportError:                       # pragma: no cover
    QApplication = None

from archpm.actions import ActionError, UserBackend
from archpm.model import ProcSample, Snapshot, SystemSample

UNIT = "app-brave\\x2dbrowser@89185f01fb3e42e38b610935c88efd87.service"
CGROUP = f"/user.slice/user-1000.slice/user@1000.service/app.slice/{UNIT}"


def proc(pid, ppid, name, cgroup=""):
    return ProcSample(pid=pid, ppid=ppid, name=name, username="alex", owned=True,
                      cmdline=f"/usr/bin/{name}", argv=(f"/usr/bin/{name}",), program=True,
                      cgroup=cgroup, app_name="Brave" if cgroup else "")


PROCS = [
    proc(1, 0, "systemd"),
    proc(1000, 1, "systemd"),
    proc(4558, 1000, "brave", CGROUP),
    proc(4573, 4558, "brave", CGROUP),
    proc(4574, 4558, "brave", CGROUP),
    proc(5000, 1000, "konsole"),
]


class Recorder(UserBackend):
    """Records instead of touching anything."""

    def __init__(self):
        super().__init__()
        self.calls = []

    def set_nice(self, pid, value):
        self.calls.append(("nice", pid, value))

    def set_ionice(self, pid, klass, value=4):
        self.calls.append(("ionice", pid, klass, value))

    def set_affinity(self, pid, cores):
        self.calls.append(("affinity", pid, tuple(cores)))


@unittest.skipUnless(QApplication, "PySide6 not installed")
class GroupRowActions(unittest.TestCase):
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
        from archpm.ui.procview import ProcessView
        self.backend = Recorder()
        self.view = ProcessView(8, self.backend)
        self.view.show()
        self.view.set_mode("grouped")
        self.view.cb_all.setChecked(True)
        self.view.update_view(Snapshot(system=SystemSample(), procs=PROCS))
        self.messages = []
        self.view.status.connect(self.messages.append)

    def group_pid(self) -> int:
        groups = [pid for pid, n in self.view.model._nodes.items()
                  if pid < 0 and n.proc.display_name == "Brave"]
        self.assertEqual(len(groups), 1, "the three brave processes form one group row")
        return groups[0]

    def select(self, pid: int) -> None:
        idx = self.view.proxy.mapFromSource(self.view.model.index_for_pid(pid))
        self.assertTrue(idx.isValid(), f"pid {pid} not visible")
        flag = QItemSelectionModel.SelectionFlag
        flags = flag.ClearAndSelect | flag.Rows
        self.view.table.selectionModel().select(idx, flags)

    def test_priority_on_the_group_row_reaches_every_member(self):
        self.select(self.group_pid())
        self.view._set_nice(10)
        self.assertEqual(sorted(self.backend.calls),
                         [("nice", 4558, 10), ("nice", 4573, 10), ("nice", 4574, 10)])
        self.assertEqual(self.messages, ["Priority changed for 3 processes"])

    def test_disk_priority_on_the_group_row_reaches_every_member(self):
        self.select(self.group_pid())
        self.view._set_ionice(3, 0)
        self.assertEqual({c[1] for c in self.backend.calls}, {4558, 4573, 4574})

    def test_a_single_process_is_still_just_that_process(self):
        self.select(5000)
        self.view._set_nice(0)
        self.assertEqual(self.backend.calls, [("nice", 5000, 0)])

    def test_selected_real_has_no_duplicates_when_group_and_member_are_both_selected(self):
        self.select(self.group_pid())
        idx = self.view.proxy.mapFromSource(self.view.model.index_for_pid(4573))
        self.view.table.expandAll()
        self.view.table.selectionModel().select(
            idx, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        self.assertEqual(sorted(p.pid for p in self.view._selected_real()), [4558, 4573, 4574])

    def test_a_fault_inside_an_action_is_shown_not_swallowed(self):
        from archpm.ui import procview
        shown = []
        original = procview.QMessageBox.exec
        procview.QMessageBox.exec = lambda box: shown.append(box.detailedText()) or 0
        try:
            self.view._run(lambda p: (_ for _ in ()).throw(ValueError("pid must be positive")),
                           [PROCS[-1]], "nice 0")
            self.view._run(lambda p: (_ for _ in ()).throw(ActionError("refused")),
                           [PROCS[-1]], "nice 0")
        finally:
            procview.QMessageBox.exec = original
        self.assertEqual(len(shown), 2)
        self.assertIn("ValueError: pid must be positive", shown[0])
        self.assertIn("refused", shown[1])
        self.assertEqual(self.messages, [])

    def test_nothing_selected_says_so(self):
        self.view.table.clearSelection()
        self.view._set_nice(0)
        self.assertEqual(self.messages, ["Nothing selected"])


@unittest.skipUnless(QApplication, "PySide6 not installed")
class WatchAfterTerminate(unittest.TestCase):
    """The "still running, force it?" watch waits for what was asked to
    quit. A Terminate the backend refused asked nothing, so there is
    nothing to wait for and no Force kill to offer; through 0.2.53 the
    watch was set regardless and offered a Force kill that failed the
    same way."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
            QSettings.setPath(fmt, QSettings.Scope.UserScope, cls.tmp.name)
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def view(self, backend):
        from unittest.mock import patch

        from PySide6.QtWidgets import QMessageBox

        from archpm.ui.procview import ProcessView
        v = ProcessView(8, backend)
        v.show()
        v.set_mode("flat")
        v.cb_all.setChecked(True)
        v.update_view(Snapshot(system=SystemSample(), procs=PROCS))
        v._confirm = lambda verdict: True
        patcher = patch.object(QMessageBox, "exec", lambda self_: 0)   # the failure box
        patcher.start()
        self.addCleanup(patcher.stop)
        idx = v.proxy.mapFromSource(v.model.index_for_pid(5000))
        flag = QItemSelectionModel.SelectionFlag
        v.table.selectionModel().select(idx, flag.ClearAndSelect | flag.Rows)
        return v

    def test_a_refused_terminate_sets_no_watch(self):
        import signal

        class Refusing(UserBackend):
            def send_signal(self, pid, sig):
                raise ActionError(f"No permission to send {sig.name} to {pid}.")
        v = self.view(Refusing())
        v._signal_selected(signal.SIGTERM)
        self.assertEqual(v._watches, [])

    def test_a_delivered_terminate_sets_one(self):
        import signal

        class Accepting(UserBackend):
            def send_signal(self, pid, sig):
                pass
        v = self.view(Accepting())
        v._signal_selected(signal.SIGTERM)
        self.assertEqual([sorted(w["pids"]) for w in v._watches], [[5000]])


if __name__ == "__main__":
    unittest.main()
