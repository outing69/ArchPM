"""Tests for archpm.cleanup on a fixture tree: what is found, how big it is,
and above all what deletion refuses to touch."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from archpm import cleanup
from archpm.appinfo import SteamIndex


def write(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


class Parsing(unittest.TestCase):
    def test_paccache_dry_run(self):
        text = "==> finished dry run: 3503 candidates (disk space saved: 27.91 GiB)\n"
        count, size = cleanup.parse_paccache_dry_run(text)
        self.assertEqual(count, 3503)
        self.assertAlmostEqual(size / (1 << 30), 27.91, places=2)
        self.assertEqual(cleanup.parse_paccache_dry_run("nothing here"), (0, 0))
        self.assertEqual(cleanup.parse_paccache_dry_run(
            "==> no candidate packages found for pruning\n"), (0, 0))

    def test_journal_usage(self):
        text = "Archived and active journals take up 47.1M in the file system.\n"
        self.assertAlmostEqual(cleanup.parse_journal_usage(text) / (1 << 20), 47.1, places=1)
        self.assertEqual(cleanup.parse_journal_usage("1.2G"), 0)
        self.assertAlmostEqual(cleanup.parse_journal_usage("take up 1.2G in the")
                               / (1 << 30), 1.2, places=1)


class Scanning(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.cache = root / "cache"
        write(self.cache / "BraveSoftware" / "a" / "b.bin", 3 << 20)
        write(self.cache / "thumbnails" / "t.png", 2 << 20)
        write(self.cache / "tiny" / "x", 10)
        write(self.cache / "tiny2" / "y", 20)
        write(self.cache / "archpm" / "status.json", 5)
        os.symlink(self.cache / "thumbnails", self.cache / "link-to-thumbs")
        self.lib = root / "SteamLibrary"
        write(self.lib / "steamapps" / "shadercache" / "1091500" / "fozpipelinesv6" / "p", 4 << 20)
        write(self.lib / "steamapps" / "shadercache" / "notanid" / "p", 4 << 20)
        write(self.lib / "steamapps" / "appmanifest_1091500.acf",
              len('"name" "Cyberpunk 2077"\n"installdir" "x"\n'))
        (self.lib / "steamapps" / "appmanifest_1091500.acf").write_text(
            '"AppState"\n{\n"appid" "1091500"\n"name" "Cyberpunk 2077"\n"installdir" "x"\n}\n')
        self.outside = root / "outside"
        write(self.outside / "keep.txt", 100)
        self.runner_calls = []

        def runner(*argv):
            self.runner_calls.append(argv)
            if argv[0] == "paccache":
                return "==> finished dry run: 10 candidates (disk space saved: 1.50 GiB)\n"
            if argv[0] == "journalctl":
                return "Archived and active journals take up 250.0M in the file system.\n"
            return ""
        steam = SteamIndex(roots=[self.lib], icon_dir=root / "icons")
        self.cleaner = cleanup.Cleaner(self.cache, steam, runner=runner)

    def tearDown(self):
        self.tmp.cleanup()

    def by_id(self):
        return {i.id: i for i in self.cleaner.scan()}

    def test_finds_caches_with_friendly_names_and_sizes(self):
        items = self.by_id()
        self.assertEqual(items["cache:BraveSoftware"].name, "Brave cache")
        self.assertEqual(items["cache:BraveSoftware"].size, 3 << 20)
        self.assertIn("Close Brave first", items["cache:BraveSoftware"].description)
        self.assertEqual(items["cache:thumbnails"].name, "Thumbnails")
        self.assertEqual(items["cache:small"].size, 30)
        self.assertEqual(len(items["cache:small"].paths), 2)
        self.assertNotIn("cache:archpm", items, "our own status folder is never listed")
        self.assertNotIn("cache:link-to-thumbs", items, "symlinks are never listed")

    def test_finds_shader_caches_named_after_the_game(self):
        items = self.by_id()
        shader = [i for i in items.values() if i.id.startswith("shader:")]
        self.assertEqual(len(shader), 1, "only numeric app-id folders count")
        self.assertEqual(shader[0].name, "Shader cache: Cyberpunk 2077")
        self.assertEqual(shader[0].size, 4 << 20)

    def test_root_items_are_estimates_and_use_fixed_helper_commands(self):
        items = self.by_id()
        if items["pacman"].helper_command:  # paccache is installed on this machine
            self.assertAlmostEqual(items["pacman"].size / (1 << 30), 1.5, places=2)
            self.assertEqual(items["pacman"].helper_command, "paccache-clean")
            self.assertTrue(items["pacman"].needs_root)
        j = items["journal"]
        self.assertTrue(j.needs_root)
        self.assertEqual(j.helper_command, "journal-vacuum")
        self.assertEqual(j.size, 150 << 20, "what is above the 100 MB we keep")
        self.assertFalse(j.paths, "root items have no paths for us to touch")

    def test_order_is_user_items_by_size_then_root(self):
        ids = [i.id for i in self.cleaner.scan()]
        self.assertTrue(ids.index("cache:BraveSoftware") < ids.index("cache:thumbnails"))
        self.assertTrue(all(ids.index(u) < ids.index("journal")
                            for u in ids if u.startswith("cache:")))


class RunningOwner(unittest.TestCase):
    def test_matches_caches_and_shader_caches_to_running_programs(self):
        from archpm.model import ProcSample
        procs = [ProcSample(pid=1, name="brave", app_name="Brave", cmdline="brave"),
                 ProcSample(pid=2, name="pycharm", app_name="PyCharm Community Edition",
                            cmdline="pycharm"),
                 ProcSample(pid=3, name="Titan", app_name="DOOM: The Dark Ages",
                            steam_appid=3017860, cmdline="Titan"),
                 ProcSample(pid=4, name="spotify", cmdline="spotify"),
                 ProcSample(pid=5, name="irq/84-nvidia"),                       # kernel thread
                 ProcSample(pid=6, name="protonvpn-app", app_name="Proton VPN",
                            cmdline="protonvpn-app")]
        brave = cleanup.CleanupItem("cache:BraveSoftware", "Brave cache", "", 1)
        jet = cleanup.CleanupItem("cache:JetBrains", "JetBrains cache", "", 1)
        doom = cleanup.CleanupItem("shader:/lib:3017860", "Shader cache: DOOM", "", 1)
        other = cleanup.CleanupItem("shader:/lib:1", "Shader cache: X", "", 1)
        spot = cleanup.CleanupItem("cache:spotify", "Spotify cache", "", 1)
        thumbs = cleanup.CleanupItem("cache:thumbnails", "Thumbnails", "", 1)
        small = cleanup.CleanupItem("cache:small", "Other", "", 1)
        self.assertEqual(cleanup.running_owner(brave, procs), "Brave")
        self.assertEqual(cleanup.running_owner(jet, procs), "PyCharm Community Edition")
        self.assertEqual(cleanup.running_owner(doom, procs), "DOOM: The Dark Ages")
        self.assertEqual(cleanup.running_owner(other, procs), "")
        self.assertEqual(cleanup.running_owner(spot, procs), "spotify")
        self.assertEqual(cleanup.running_owner(thumbs, procs), "")
        self.assertEqual(cleanup.running_owner(small, procs), "")
        nvidia = cleanup.CleanupItem("cache:nvidia", "NVIDIA shader cache", "", 1)
        proton = cleanup.CleanupItem("cache:Proton", "Proton cache", "", 1)
        self.assertEqual(cleanup.running_owner(nvidia, procs), "", "kernel thread is no owner")
        self.assertEqual(cleanup.running_owner(proton, procs), "", "Proton VPN is not Proton")


class Deleting(Scanning):
    def test_empties_the_folder_but_keeps_it(self):
        item = self.by_id()["cache:BraveSoftware"]
        freed, errors = self.cleaner.empty(item)
        self.assertEqual(errors, [])
        self.assertEqual(freed, 3 << 20)
        self.assertTrue((self.cache / "BraveSoftware").is_dir())
        self.assertEqual(list((self.cache / "BraveSoftware").iterdir()), [])

    def test_refuses_paths_outside_the_discovered_roots(self):
        self.cleaner.scan()
        rogue = cleanup.CleanupItem("x", "x", "x", 1, paths=[self.outside])
        freed, errors = self.cleaner.empty(rogue)
        self.assertEqual(freed, 0)
        self.assertEqual(len(errors), 1)
        self.assertTrue((self.outside / "keep.txt").exists())

    def test_refuses_a_symlink_even_inside_a_root(self):
        self.cleaner.scan()
        os.symlink(self.outside, self.cache / "evil")
        item = cleanup.CleanupItem("x", "x", "x", 1, paths=[self.cache / "evil"])
        freed, errors = self.cleaner.empty(item)
        self.assertEqual(freed, 0)
        self.assertTrue((self.outside / "keep.txt").exists(), "symlink target untouched")
        self.assertEqual(len(errors), 1)

    def test_root_items_are_never_deleted_here(self):
        with self.assertRaises(ValueError):
            self.cleaner.empty(self.by_id()["journal"])

    def test_shader_cache_deletion_stays_inside_shadercache(self):
        items = self.by_id()
        shader = next(i for i in items.values() if i.id.startswith("shader:"))
        freed, errors = self.cleaner.empty(shader)
        self.assertEqual(errors, [])
        self.assertEqual(freed, 4 << 20)
        self.assertTrue((self.lib / "steamapps" / "appmanifest_1091500.acf").exists())


if __name__ == "__main__":
    unittest.main()
