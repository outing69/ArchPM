"""Every context menu the app opens is deleted when it closes. A parented
QMenu outlives the Python reference that made it, so through 0.2.55 each
right-click on a tile, a column header or the process list left one behind
until the window closed."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import QPoint, QSettings, Qt
    from PySide6.QtWidgets import QApplication, QMenu, QTreeView, QWidget
except ImportError:                       # pragma: no cover
    QApplication = None


@unittest.skipUnless(QApplication, "PySide6 not installed")
class MenusGoWhenClosed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
            QSettings.setPath(fmt, QSettings.Scope.UserScope, cls.tmp.name)
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def opened(self, module, run):
        """The menus a callable opens: the module's QMenu is a subclass whose
        exec() records the menu and returns, so nothing is shown and the
        offscreen loop never waits for a click."""
        seen = []

        class Recording(QMenu):
            def exec(self, *_a, **_k):
                seen.append(self)
        with patch.object(module, "QMenu", Recording):
            run()
        self.assertTrue(seen, "no menu was opened")
        return seen

    def test_a_tile_menu(self):
        from archpm.ui import hints
        parent = QWidget()
        menu = hints._menu_for("tile.cpu", lambda _t: None, parent)
        self.assertIsNotNone(menu)
        self.assertTrue(menu.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose))

    def test_a_header_menu(self):
        from archpm.ui import hints
        tree = QTreeView()
        from PySide6.QtGui import QStandardItemModel
        model = QStandardItemModel(1, 2)
        tree.setModel(model)
        hints.attach_header(tree.header(), ["tile.cpu", "tile.mem"], lambda _t: None)
        opener = lambda: tree.header().customContextMenuRequested.emit(QPoint(1, 1))  # noqa: E731
        for menu in self.opened(hints, opener):
            self.assertTrue(menu.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose))

    def test_the_process_list_menu(self):
        from archpm.actions import UserBackend
        from archpm.model import ProcSample, Snapshot, SystemSample
        from archpm.ui.procview import ProcessView
        v = ProcessView(8, UserBackend())
        v.show()
        v.set_mode("flat")
        v.cb_all.setChecked(True)
        procs = [ProcSample(pid=5000, ppid=1, name="konsole", username="alex", owned=True,
                            cmdline="/usr/bin/konsole", argv=("/usr/bin/konsole",), program=True)]
        v.update_view(Snapshot(system=SystemSample(), procs=procs))
        from PySide6.QtCore import QItemSelectionModel

        from archpm.ui import procview
        idx = v.proxy.mapFromSource(v.model.index_for_pid(5000))
        flag = QItemSelectionModel.SelectionFlag
        v.table.selectionModel().setCurrentIndex(idx, flag.ClearAndSelect | flag.Rows)
        for menu in self.opened(procview, lambda: v._menu(QPoint(1, 1))):
            self.assertTrue(menu.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose))


if __name__ == "__main__":
    unittest.main()
