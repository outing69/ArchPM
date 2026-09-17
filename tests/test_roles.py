"""A member of a browser is named for what it is, from what its own command
line says: a page, the graphics, a helper. A process the rules cannot place
keeps its plain name. Command lines as measured on Brave, Chrome and Firefox."""
from __future__ import annotations

import os
import unittest

from archpm.appinfo import ROLE_ABOUT, process_role

BRAVE = "/opt/brave-bin/brave"
FF = "/usr/lib/firefox/firefox"


class Roles(unittest.TestCase):
    def test_chromium_family_from_type(self):
        cases = {
            (BRAVE, "--type=renderer", "--crashpad-handler-pid=4564"): "page",
            (BRAVE, "--type=renderer", "--extension-process", "--lang=en"): "extension",
            (BRAVE, "--type=gpu-process", "--ozone-platform=wayland"): "graphics",
            (BRAVE, "--type=utility", "--utility-sub-type=network.mojom.NetworkService"): "network",
            (BRAVE, "--type=utility", "--utility-sub-type=audio.mojom.AudioService"): "audio",
            (BRAVE, "--type=utility", "--utility-sub-type=storage.mojom.StorageService"): "storage",
            (BRAVE, "--type=utility", "--utility-sub-type=something.new.Service"): "helper",
            (BRAVE, "--type=utility"): "helper",
            (BRAVE, "--type=zygote", "--no-zygote-sandbox"): "helper",
            (BRAVE, "--type=broker"): "helper",
            ("/opt/google/chrome/chrome", "--type=renderer"): "page",
            ("/home/a/Steam/steamwebhelper", "--type=zygote"): "helper",
            ("/usr/lib/qt6/QtWebEngineProcess", "--type=renderer", "--application-name=X"): "page",
            ("/usr/lib/electron/electron", "--type=renderer"): "page",
        }
        for argv, want in cases.items():
            with self.subTest(argv=argv):
                self.assertEqual(process_role(argv), want)

    def test_firefox_from_the_last_word(self):
        cases = {
            (FF, "-contentproc", "-isForBrowser", "-prefsHandle", "1", "tab"): "page",
            (FF, "-contentproc", "-parentBuildID", "2026", "gpu"): "graphics",
            (FF, "-contentproc", "-parentBuildID", "2026", "socket"): "network",
            (FF, "-contentproc", "-parentBuildID", "2026", "rdd"): "media",
            (FF, "-contentproc", "-parentBuildID", "2026", "utility"): "helper",
            (FF, "-contentproc", "-ipcHandle", "0", "forkserver"): "helper",
        }
        for argv, want in cases.items():
            with self.subTest(argv=argv):
                self.assertEqual(process_role(argv), want)

    def test_what_cannot_be_placed_keeps_its_name(self):
        for argv in ((BRAVE,), (BRAVE, "--type=something-new"), (FF, "-contentproc", "newkind"),
                     ("/usr/bin/zsh", "--type=renderer-lookalike"), ("sed", "-contentproc"), ()):
            with self.subTest(argv=argv):
                self.assertEqual(process_role(argv), "")

    def test_every_role_has_a_plain_explanation(self):
        for role in ("page", "extension", "graphics", "network", "audio", "storage", "media",
                     "printing", "helper"):
            self.assertIn(role, ROLE_ABOUT)
            self.assertNotIn("—", ROLE_ABOUT[role])
        self.assertIn("closes that page; the program stays", ROLE_ABOUT["page"])


@unittest.skipUnless(os.environ.get("DISPLAY") or True, "offscreen")
class InTheList(unittest.TestCase):
    def test_the_name_column_says_the_role_and_the_search_finds_it(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtCore import Qt
            from PySide6.QtWidgets import QApplication
        except ImportError:                       # pragma: no cover
            self.skipTest("PySide6 not installed")
        QApplication.instance() or QApplication([])
        from archpm.model import ProcSample
        from archpm.ui.proc_model import COL_NAME, ProcModel
        m = ProcModel(8)
        m.mode = "flat"
        procs = [ProcSample(pid=10, name="brave", app_name="Brave", role="page",
                            argv=(BRAVE, "--type=renderer"), cmdline=BRAVE + " --type=renderer"),
                 ProcSample(pid=11, name="brave", app_name="Brave", role="",
                            argv=(BRAVE,), cmdline=BRAVE)]
        m.update(procs)
        names = {m.data(m.index(r, COL_NAME)): m.data(m.index(r, COL_NAME),
                                                        Qt.ItemDataRole.ToolTipRole)
                 for r in range(m.rowCount())}
        self.assertIn("Brave · page", names)
        self.assertIn("Brave", names)
        self.assertIn("closes that page", names["Brave · page"])
        from archpm.ui.proc_model import ProcFilter
        f = ProcFilter()
        f.text = "page"
        self.assertTrue(f.matches_text(procs[0]))
        self.assertFalse(f.matches_text(procs[1]))


if __name__ == "__main__":
    unittest.main()
