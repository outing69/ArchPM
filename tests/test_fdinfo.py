"""Per-process GPU usage from DRM fdinfo, against a fake /proc tree.

The field sets are the real ones: amdgpu as captured on the development
machine, i915 and xe as documented in Documentation/gpu/drm-usage-stats.rst.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from archpm import fdinfo
from archpm.gpu import GpuMonitor

AMDGPU = """\
pos:\t0
flags:\t02100002
mnt_id:\t26
ino:\t1234
drm-driver:\tamdgpu
drm-client-id:\t185
drm-pdev:\t0000:11:00.0
drm-total-vram:\t60060 KiB
drm-shared-vram:\t0
drm-resident-vram:\t60060 KiB
drm-purgeable-vram:\t0
drm-total-gtt:\t2 MiB
drm-resident-gtt:\t2 MiB
drm-memory-vram:\t60060 KiB
drm-memory-gtt: \t2048 KiB
drm-memory-cpu: \t0 KiB
drm-engine-compute:\t{compute} ns
drm-engine-enc:\t{enc} ns
"""

I915 = """\
drm-driver:\ti915
drm-client-id:\t7
drm-pdev:\t0000:00:02.0
drm-total-local0:\t256 MiB
drm-resident-local0:\t128 MiB
drm-total-system0:\t64 MiB
drm-engine-render:\t{render} ns
drm-engine-copy:\t0 ns
drm-engine-video:\t0 ns
drm-engine-capacity-video:\t2
"""

XE = """\
drm-driver:\txe
drm-client-id:\t9
drm-pdev:\t0000:03:00.0
drm-resident-vram0:\t512 MiB
drm-cycles-rcs:\t{cycles}
drm-total-cycles-rcs:\t{total}
drm-maxfreq-rcs:\t2100 MHz
"""


class FakeProc:
    """A /proc look-alike: <root>/<pid>/fd/<n> symlinks and fdinfo files."""

    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def add(self, pid: int, fd: int, target: str, info: str | None) -> None:
        (self.root / str(pid) / "fd").mkdir(parents=True, exist_ok=True)
        (self.root / str(pid) / "fdinfo").mkdir(parents=True, exist_ok=True)
        os.symlink(target, self.root / str(pid) / "fd" / str(fd))
        if info is not None:
            (self.root / str(pid) / "fdinfo" / str(fd)).write_text(info)

    def close(self) -> None:
        self.tmp.cleanup()


class Parsing(unittest.TestCase):
    def test_sizes_default_to_bytes_and_know_the_binary_units(self):
        self.assertEqual(fdinfo.parse_size("0"), 0.0)
        self.assertEqual(fdinfo.parse_size("12 KiB"), 12 * 1024)
        self.assertEqual(fdinfo.parse_size("2 MiB"), 2 * 1024 ** 2)
        self.assertEqual(fdinfo.parse_size("4096"), 4096)
        self.assertEqual(fdinfo.parse_size("junk"), 0.0)

    def test_amdgpu_fields_become_a_client(self):
        c = fdinfo.client_from_fields(fdinfo.parse_fdinfo(AMDGPU.format(compute=5, enc=7)))
        self.assertEqual(c.driver, "amdgpu")
        self.assertEqual(c.engines_ns, {"compute": 5, "enc": 7})
        self.assertAlmostEqual(c.device_bytes, 60060 * 1024)

    def test_resident_beats_the_deprecated_alias_and_total(self):
        text = "drm-driver:\tamdgpu\ndrm-total-vram:\t300 MiB\ndrm-memory-vram:\t200 MiB\ndrm-resident-vram:\t100 MiB\n"
        self.assertAlmostEqual(fdinfo.client_from_fields(fdinfo.parse_fdinfo(text)).device_bytes, 100 * 1024 ** 2)
        text = "drm-driver:\tamdgpu\ndrm-total-vram:\t300 MiB\n"
        self.assertAlmostEqual(fdinfo.client_from_fields(fdinfo.parse_fdinfo(text)).device_bytes, 300 * 1024 ** 2)

    def test_i915_counts_local_memory_not_system_memory(self):
        c = fdinfo.client_from_fields(fdinfo.parse_fdinfo(I915.format(render=1)))
        self.assertAlmostEqual(c.device_bytes, 128 * 1024 ** 2)
        self.assertEqual(c.capacity, {"video": 2})
        self.assertIn("render", c.engines_ns)
        self.assertNotIn("capacity-video", c.engines_ns)

    def test_xe_cycles_are_paired(self):
        c = fdinfo.client_from_fields(fdinfo.parse_fdinfo(XE.format(cycles=10, total=100)))
        self.assertEqual(c.cycles, {"rcs": (10, 100)})
        self.assertAlmostEqual(c.device_bytes, 512 * 1024 ** 2)


class Scanning(unittest.TestCase):
    def setUp(self):
        self.proc = FakeProc()
        self.addCleanup(self.proc.close)
        self.now = 100.0
        self.src = fdinfo.DrmFdinfo(str(self.proc.root), clock=lambda: self.now)

    def test_one_client_on_three_fds_counts_once(self):
        for fd in (3, 4, 5):
            self.proc.add(4242, fd, "/dev/dri/renderD129", AMDGPU.format(compute=0, enc=0))
        self.proc.add(4242, 6, "/home/user/file.txt", "pos:\t0\n")
        busy, mb, drivers = self.src.processes()[4242]
        self.assertAlmostEqual(mb, 60060 / 1024)
        self.assertEqual(drivers, frozenset({"amdgpu"}))

    def test_busy_share_is_the_delta_over_wall_time(self):
        self.proc.add(1, 3, "/dev/dri/renderD129", AMDGPU.format(compute=0, enc=0))
        self.assertEqual(self.src.processes()[1][0], 0.0, "first scan has nothing to compare")
        os.remove(self.proc.root / "1" / "fdinfo" / "3")
        # 2 s later the encoder was busy for 1 s and compute for 0.2 s: 50%
        (self.proc.root / "1" / "fdinfo" / "3").write_text(
            AMDGPU.format(compute=200_000_000, enc=1_000_000_000))
        self.now += 2.0
        self.assertAlmostEqual(self.src.processes()[1][0], 50.0)

    def test_capacity_divides_and_the_share_is_capped(self):
        self.proc.add(1, 3, "/dev/dri/renderD128", I915.format(render=0))
        self.src.processes()
        (self.proc.root / "1" / "fdinfo" / "3").write_text(
            I915.format(render=3_000_000_000).replace("drm-engine-video:\t0 ns", "drm-engine-video:\t3000000000 ns"))
        self.now += 1.0
        busy = self.src.processes()[1][0]
        self.assertEqual(busy, 100.0, "render alone is 300% of a second, capped; video/2 is 150, capped")

    def test_xe_share_comes_from_cycles(self):
        self.proc.add(1, 3, "/dev/dri/renderD128", XE.format(cycles=1000, total=10000))
        self.src.processes()
        (self.proc.root / "1" / "fdinfo" / "3").write_text(XE.format(cycles=1250, total=11000))
        self.now += 1.0
        self.assertAlmostEqual(self.src.processes()[1][0], 25.0)

    def test_unreadable_or_missing_fdinfo_is_skipped_quietly(self):
        self.proc.add(1, 3, "/dev/dri/renderD128", None)          # fd without fdinfo
        self.proc.add(2, 3, "/dev/dri/renderD128", AMDGPU.format(compute=0, enc=0))
        os.chmod(self.proc.root / "2" / "fdinfo" / "3", 0)
        self.proc.add(3, 3, "/dev/dri/card0", "pos:\t0\n")          # DRM fd, no drm- fields
        (self.proc.root / "4").mkdir()                              # process without an fd dir
        if os.getuid() == 0:
            self.skipTest("root can read a mode-0 file")
        self.assertEqual(self.src.processes(), {})

    def test_state_of_a_vanished_process_is_dropped(self):
        self.proc.add(1, 3, "/dev/dri/renderD128", AMDGPU.format(compute=0, enc=0))
        self.src.processes()
        self.assertTrue(self.src._prev)
        import shutil
        shutil.rmtree(self.proc.root / "1")
        self.src.processes()
        self.assertEqual(self.src._prev, {})

    def test_empty_proc_root_is_not_an_error(self):
        self.assertEqual(fdinfo.DrmFdinfo("/nonexistent").processes(), {})


class Merge(unittest.TestCase):
    """GpuMonitor.processes(): fdinfo first, nvidia-smi fills the gaps."""

    def monitor(self, nvidia: dict, fd: dict) -> GpuMonitor:
        m = GpuMonitor()
        m._procs_supported = bool(nvidia)
        import time
        m._procs = {pid: (sm, mb, time.monotonic()) for pid, (sm, mb) in nvidia.items()}
        m.fdinfo.processes = lambda: fd
        return m

    def test_fdinfo_alone(self):
        m = self.monitor({}, {1: (40.0, 100.0, frozenset({"amdgpu"}))})
        self.assertEqual(m.processes(), {1: (40.0, 100.0)})

    def test_nvidia_fills_what_fdinfo_does_not_see(self):
        m = self.monitor({2: (70.0, 900.0)}, {1: (40.0, 100.0, frozenset({"amdgpu"}))})
        self.assertEqual(m.processes(), {1: (40.0, 100.0), 2: (70.0, 900.0)})

    def test_a_process_on_both_cards_keeps_both(self):
        m = self.monitor({1: (70.0, 900.0)}, {1: (40.0, 100.0, frozenset({"amdgpu"}))})
        self.assertEqual(m.processes(), {1: (70.0, 1000.0)})

    def test_an_nvidia_fdinfo_entry_replaces_pmon_so_the_card_counts_once(self):
        m = self.monitor({1: (70.0, 900.0)}, {1: (65.0, 880.0, frozenset({"nvidia"}))})
        self.assertEqual(m.processes(), {1: (65.0, 880.0)})

    def test_pmon_polls_at_the_sampling_interval_not_faster(self):
        from archpm import gpu
        self.assertEqual(gpu.PMON_INTERVAL_S, 2)
        self.assertGreater(gpu._PROC_TTL, gpu.PMON_INTERVAL_S, "a pid must survive one missed poll")

    def test_per_process_available_follows_either_source(self):
        m = GpuMonitor()
        self.assertFalse(m.per_process_available)
        m.fdinfo.seen_any = True
        self.assertTrue(m.per_process_available)


if __name__ == "__main__":
    unittest.main()
