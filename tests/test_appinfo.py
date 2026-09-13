"""Tests for archpm.appinfo against fixture files: desktop entries, Steam's
libraryfolders.vdf and appmanifest_*.acf, and the game-binary rule."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from archpm import appinfo

BRAVE = """\
[Desktop Entry]
Version=1.0
Name=Brave Web Browser
Exec=brave %U
Icon=brave-desktop
Type=Application
Actions=new-window;

[Desktop Action new-window]
Name=New Window
Exec=brave --new-window
"""
ARCHPM = """\
[Desktop Entry]
Type=Application
Name=ArchPM
Exec=/usr/bin/python3 -m archpm
Icon=utilities-system-monitor
"""
ENVAPP = """\
[Desktop Entry]
Type=Application
Name=Env App
Exec=env QT_QPA_PLATFORM=xcb /opt/envapp/bin/envapp --flag %F
Icon=envapp
"""
HIDDEN_KONSOLE = """\
[Desktop Entry]
Type=Application
Name=Konsole (hidden variant)
Exec=konsole --profile x
Icon=utilities-terminal
NoDisplay=true
"""
KONSOLE = """\
[Desktop Entry]
Type=Application
Name=Konsole
Exec=konsole
Icon=utilities-terminal
"""
BARE_PYTHON = """\
[Desktop Entry]
Type=Application
Name=Should Never Match
Exec=python3
Icon=nope
"""
NOT_AN_APP = """\
[Desktop Entry]
Type=Link
Name=Some link
URL=https://example.org
"""

LIBRARYFOLDERS = """\
"libraryfolders"
{
\t"0"
\t{
\t\t"path"\t\t"/home/alex/.local/share/Steam"
\t\t"label"\t\t""
\t}
\t"1"
\t{
\t\t"path"\t\t"/mnt/games/SteamLibrary"
\t}
}
"""
APPMANIFEST = """\
"AppState"
{
\t"appid"\t\t"1091500"
\t"universe"\t\t"1"
\t"name"\t\t"Cyberpunk 2077"
\t"installdir"\t\t"Cyberpunk 2077"
}
"""


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class DesktopParsing(unittest.TestCase):
    def test_only_the_main_group_is_read(self):
        entry = appinfo.parse_desktop_entry(BRAVE)
        self.assertEqual(entry["Exec"], "brave %U")
        self.assertEqual(entry["Name"], "Brave Web Browser")

    def test_exec_tokens_drop_field_codes_env_and_paths(self):
        self.assertEqual(appinfo.exec_tokens("brave %U"), ("brave",))
        self.assertEqual(appinfo.exec_tokens("/usr/bin/python3 -m archpm"),
                         ("python3", "-m", "archpm"))
        self.assertEqual(appinfo.exec_tokens("env A=1 B=2 /opt/x/bin/x --flag %F"), ("x", "--flag"))
        self.assertEqual(appinfo.exec_tokens('"/opt/My App/app" %u'), ("app",))
        self.assertEqual(appinfo.exec_tokens('unbalanced "quote'), ())


class DesktopMatching(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.user = root / "user"
        self.system = root / "system"
        write(self.user / "archpm.desktop", ARCHPM)
        write(self.user / "konsole-hidden.desktop", HIDDEN_KONSOLE)
        write(self.system / "brave-browser.desktop", BRAVE)
        write(self.system / "envapp.desktop", ENVAPP)
        write(self.system / "org.kde.konsole.desktop", KONSOLE)
        write(self.system / "bare.desktop", BARE_PYTHON)
        write(self.system / "link.desktop", NOT_AN_APP)
        self.index = appinfo.DesktopIndex([self.user, self.system])

    def tearDown(self):
        self.tmp.cleanup()

    def test_matches_by_basename_of_argv0(self):
        info = self.index.match(["/opt/brave-bin/brave", "--type=renderer", "--x"])
        self.assertEqual((info.name, info.icon), ("Brave Web Browser", "brave-desktop"))

    def test_interpreter_entry_needs_its_arguments(self):
        self.assertEqual(self.index.match(["/usr/bin/python3", "-m", "archpm"]).name, "ArchPM")
        self.assertFalse(self.index.match(["/usr/bin/python3", "-m", "http.server"]))
        self.assertFalse(self.index.match(["python3"]), "bare interpreter entry must be ignored")

    def test_env_prefix_is_skipped(self):
        info = self.index.match(["/opt/envapp/bin/envapp", "--flag", "f"])
        self.assertEqual(info.name, "Env App")

    def test_visible_entry_wins_over_hidden_one_with_same_command(self):
        self.assertEqual(self.index.match(["konsole"]).name, "Konsole")
        # the hidden one still matches when its longer prefix fits
        self.assertEqual(self.index.match(["konsole", "--profile", "x"]).name,
                         "Konsole (hidden variant)")

    def test_non_applications_and_unknown_commands_give_nothing(self):
        self.assertFalse(self.index.match(["kwin_wayland"]))
        self.assertFalse(self.index.match([]))


class SteamParsing(unittest.TestCase):
    def test_library_paths(self):
        self.assertEqual(appinfo.parse_library_folders(LIBRARYFOLDERS),
                         ["/home/alex/.local/share/Steam", "/mnt/games/SteamLibrary"])

    def test_appmanifest_name(self):
        self.assertEqual(appinfo.parse_appmanifest_name(APPMANIFEST), "Cyberpunk 2077")
        self.assertEqual(appinfo.parse_appmanifest_name("garbage"), "")

    def test_game_binary_rule(self):
        self.assertTrue(appinfo.is_game_binary("Z:\\games\\Cyberpunk2077.exe", "Cyberpunk2077.exe"))
        native = "/mnt/games/SteamLibrary/steamapps/common/cs2/cs2"
        self.assertTrue(appinfo.is_game_binary(native, "cs2"))
        self.assertFalse(appinfo.is_game_binary("/usr/bin/wineserver", "wineserver"))
        reaper = "/home/alex/.local/share/Steam/ubuntu12_32/reaper"
        self.assertFalse(appinfo.is_game_binary(reaper, "reaper"))


class SteamIndexOnFixtures(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.steam_root = root / "Steam"
        self.lib2 = root / "SteamLibrary"
        write(self.steam_root / "steamapps" / "libraryfolders.vdf",
              LIBRARYFOLDERS.replace("/mnt/games/SteamLibrary", str(self.lib2)))
        write(self.lib2 / "steamapps" / "appmanifest_1091500.acf", APPMANIFEST)
        icons = root / "icons"
        write(icons / "32x32" / "apps" / "steam_icon_1091500.png", "not really a png")
        write(icons / "256x256" / "apps" / "steam_icon_1091500.png", "not really a png")
        self.steam = appinfo.SteamIndex(roots=[self.steam_root], icon_dir=icons)

    def tearDown(self):
        self.tmp.cleanup()

    def test_name_is_found_in_a_secondary_library(self):
        self.assertEqual(self.steam.name(1091500), "Cyberpunk 2077")
        self.assertEqual(self.steam.name(4242), "")

    def test_icon_prefers_a_mid_size(self):
        self.assertTrue(self.steam.icon(1091500).endswith("32x32/apps/steam_icon_1091500.png"))
        self.assertEqual(self.steam.icon(4242), "")


class Resolver(unittest.TestCase):
    """Wires the two indexes together with the Steam appid lookup stubbed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        write(root / "apps" / "brave.desktop", BRAVE)
        desktop = appinfo.DesktopIndex([root / "apps"])
        write(root / "Steam" / "steamapps" / "appmanifest_1091500.acf", APPMANIFEST)
        write(root / "icons" / "48x48" / "apps" / "steam_icon_1091500.png", "png")
        steam = appinfo.SteamIndex(roots=[root / "Steam"], icon_dir=root / "icons")
        self.appids = {}
        steam.appid_of = lambda pid: self.appids.get(pid, 0)
        self.resolver = appinfo.AppResolver(desktop, steam)

    def tearDown(self):
        self.tmp.cleanup()

    def test_game_binary_gets_the_game_name_and_icon(self):
        self.appids[100] = 1091500
        info = self.resolver.lookup(100, "Cyberpunk2077.exe", ["Z:\\g\\Cyberpunk2077.exe"],
                                    owned=True)
        self.assertEqual(info.name, "Cyberpunk 2077")
        self.assertTrue(info.icon.endswith("steam_icon_1091500.png"))
        self.assertEqual(info.steam_appid, 1091500)

    def test_helper_process_keeps_its_name_but_shares_the_icon(self):
        self.appids[101] = 1091500
        info = self.resolver.lookup(101, "wineserver", ["/usr/bin/wineserver"], owned=True)
        self.assertEqual(info.name, "")
        self.assertTrue(info.icon.endswith("steam_icon_1091500.png"))

    def test_unowned_process_never_reads_environ(self):
        self.appids[102] = 1091500
        info = self.resolver.lookup(102, "Game.exe", ["Game.exe"], owned=False)
        self.assertFalse(info)

    def test_desktop_match_without_steam(self):
        info = self.resolver.lookup(103, "brave", ["/opt/brave/brave", "--x"], owned=True)
        self.assertEqual(info.name, "Brave Web Browser")

    def test_cache_is_per_pid_and_invalidated_when_the_name_changes(self):
        self.resolver.lookup(104, "brave", ["/opt/brave/brave"], owned=True)
        self.assertEqual(self.resolver.lookup(104, "brave", ["something-else"], owned=True).name,
                         "Brave Web Browser", "same pid+name: cached answer")
        self.assertFalse(self.resolver.lookup(104, "other", ["something-else"], owned=True),
                         "name changed (exec): recomputed")


if __name__ == "__main__":
    unittest.main()
