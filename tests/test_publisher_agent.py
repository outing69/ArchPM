"""status.json: written only into a directory of our own, checked on the open
descriptor, and carrying nothing the widget would run. And the GUI must not
write it while the agent service does: the two carry different content (the
agent reads no PSS) and the widget would alternate between them."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from archpm import publisher
from archpm.model import ProcSample, Snapshot, SystemSample


def snapshot() -> Snapshot:
    sys_ = SystemSample(ts=1.0, cpu_percent=12.5, per_core=[10.0, 15.0], mem_used=1 << 30,
                        mem_total=4 << 30)
    proc = ProcSample(pid=42, name="game", cpu_percent=90.0, mem_rss=1 << 20,
                      steam_appid=9, gpu_sm=50.0, program=True)
    return Snapshot(system=sys_, procs=[proc])


class OwnedDirectory(unittest.TestCase):
    """open_owned_dir hands back a descriptor only for a directory that is ours."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_and_opens_a_private_directory(self):
        d = self.base / "archpm"
        fd = publisher.open_owned_dir(d)
        try:
            st = os.fstat(fd)
            self.assertTrue(stat.S_ISDIR(st.st_mode))
            self.assertEqual(stat.S_IMODE(st.st_mode), 0o700)
            self.assertEqual(st.st_uid, os.getuid())
        finally:
            os.close(fd)

    def test_refuses_a_directory_of_another_user(self):
        d = self.base / "archpm"
        d.mkdir()
        with self.assertRaises(publisher.PublishError) as cm:
            publisher.open_owned_dir(d, uid=os.getuid() + 1)
        self.assertIn("not by us", str(cm.exception))
        self.assertIn(str(d), str(cm.exception))

    def test_refuses_a_directory_others_can_write(self):
        d = self.base / "archpm"
        d.mkdir(mode=0o777)
        os.chmod(d, 0o777)   # mkdir applies the umask; this does not
        with self.assertRaises(publisher.PublishError) as cm:
            publisher.open_owned_dir(d)
        self.assertIn("writable by others", str(cm.exception))

    def test_refuses_a_symlink_even_to_our_own_directory(self):
        real = self.base / "real"
        real.mkdir(mode=0o700)
        link = self.base / "archpm"
        link.symlink_to(real)
        with self.assertRaises(publisher.PublishError) as cm:
            publisher.open_owned_dir(link)
        self.assertIn("symlink", str(cm.exception))

    def test_refuses_a_file_in_the_way(self):
        f = self.base / "archpm"
        f.write_text("")
        with self.assertRaises(publisher.PublishError):
            publisher.open_owned_dir(f)


class Publish(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_writes_through_the_directory_and_leaves_no_temp_file(self):
        target = self.base / "archpm" / "status.json"
        self.assertEqual(publisher.publish(snapshot(), target), target)
        data = json.loads(target.read_text())
        self.assertEqual(data["cpu"], 12.5)
        self.assertEqual(sorted(os.listdir(target.parent)), ["status.json"])
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

    def test_the_file_carries_nothing_to_run(self):
        data = publisher.to_payload(snapshot())
        self.assertNotIn("launch", data)
        self.assertIn("game", data)
        self.assertNotIn("pids", data["game"])
        self.assertEqual(data["game"]["name"], "game")

    def test_refuses_instead_of_writing_into_a_foreign_directory(self):
        d = self.base / "archpm"
        d.mkdir(mode=0o700)
        os.chmod(d, 0o777)
        with self.assertRaises(publisher.PublishError):
            publisher.publish(snapshot(), d / "status.json")
        self.assertEqual(os.listdir(d), [])

    def test_without_a_runtime_directory_the_cache_directory_is_used_directly(self):
        env = {"XDG_CACHE_HOME": str(self.base / "cache")}
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("XDG_RUNTIME_DIR", None)
            self.assertIsNone(publisher.runtime_dir())
            self.assertEqual(publisher.status_path(),
                             self.base / "cache" / "archpm" / "status.json")
            self.assertEqual(publisher.status_path(), publisher.cache_link())
            target = publisher.publish(snapshot())
            self.assertFalse(target.is_symlink(), "no link from the file to itself")
            self.assertIn("cpu", json.loads(target.read_text()))
            self.assertNotEqual(publisher.status_dir(), Path(tempfile.gettempdir()) / "archpm")

    def test_with_a_runtime_directory_the_cache_holds_a_link_to_it(self):
        env = {"XDG_RUNTIME_DIR": str(self.base / "run"),
               "XDG_CACHE_HOME": str(self.base / "cache")}
        (self.base / "run").mkdir(mode=0o700)
        with mock.patch.dict(os.environ, env, clear=False):
            target = publisher.publish(snapshot())
            self.assertEqual(target, self.base / "run" / "archpm" / "status.json")
            link = publisher.cache_link()
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.readlink(), target)
            self.assertIn("cpu", json.loads(link.read_text()))


class AgentServiceActive(unittest.TestCase):
    def test_active_when_systemctl_says_so(self):
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            return SimpleNamespace(returncode=0)
        self.assertTrue(publisher.agent_service_active(run))
        self.assertEqual(calls[0][:4], ["systemctl", "--user", "is-active", "--quiet"])
        self.assertEqual(calls[0][4], publisher.AGENT_UNIT)

    def test_inactive_failed_or_missing_means_not_active(self):
        self.assertFalse(publisher.agent_service_active(
            lambda *a, **k: SimpleNamespace(returncode=3)))

        def missing(*a, **k):
            raise FileNotFoundError("systemctl")
        self.assertFalse(publisher.agent_service_active(missing))

        def slow(*a, **k):
            raise subprocess.TimeoutExpired("systemctl", 3)
        self.assertFalse(publisher.agent_service_active(slow))

    def test_on_this_machine_it_matches_systemctl(self):
        expected = subprocess.run(["systemctl", "--user", "is-active", "--quiet", "archpm-agent"],
                                  capture_output=True, check=False).returncode == 0
        self.assertEqual(publisher.agent_service_active(), expected)


if __name__ == "__main__":
    unittest.main()
