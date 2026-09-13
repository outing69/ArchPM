"""Tests for the sysfs GPU backend against a fixture tree.

Lets the AMD path be exercised without an AMD card: the layout below is what
amdgpu exposes for a Ryzen 7000 iGPU (no product_name, power1_input instead of
power1_average), captured from a real machine.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from archpm import gpu

PCI_IDS = """\
# comment line
1001  Kolter Electronic
\t0010  PCI 1616 Measurement Card
1002  Advanced Micro Devices, Inc. [AMD/ATI]
\t164e  Raphael
\t\t1462 7e26  Something Subsystem
\t744c  Navi 31 [Radeon RX 7900 XT/7900 XTX/7900 GRE/7900M]
1003  ULSI Systems
\t164e  Not the same device, different vendor
"""


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class PciIds(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ids = Path(self.tmp.name) / "pci.ids"
        self.ids.write_text(PCI_IDS)

    def tearDown(self):
        self.tmp.cleanup()

    def test_finds_device_in_vendor_block(self):
        self.assertEqual(gpu.pci_ids_lookup("1002", "164e", (str(self.ids),)), "AMD Raphael")

    def test_accepts_sysfs_style_ids_with_0x_prefix_and_uppercase(self):
        self.assertEqual(gpu.pci_ids_lookup("0x1002", "0x164E", (str(self.ids),)), "AMD Raphael")

    def test_does_not_match_same_device_id_under_another_vendor(self):
        self.assertEqual(gpu.pci_ids_lookup("1003", "744c", (str(self.ids),)), "")

    def test_ignores_subsystem_lines(self):
        self.assertEqual(gpu.pci_ids_lookup("1002", "1462", (str(self.ids),)), "")

    def test_unknown_vendor_and_missing_file_are_empty(self):
        self.assertEqual(gpu.pci_ids_lookup("dead", "beef", (str(self.ids),)), "")
        self.assertEqual(gpu.pci_ids_lookup("1002", "164e", ("/nonexistent/pci.ids",)), "")


class SysfsSample(unittest.TestCase):
    """Fixture: /sys/class/drm/card0/device of a Ryzen 7800X3D iGPU (amdgpu)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dev = Path(self.tmp.name) / "device"
        write(self.dev / "vendor", "0x1002\n")
        write(self.dev / "device", "0x164e\n")
        write(self.dev / "gpu_busy_percent", "7\n")
        write(self.dev / "mem_info_vram_used", "26234880\n")
        write(self.dev / "mem_info_vram_total", "536870912\n")
        hw = self.dev / "hwmon" / "hwmon2"
        write(hw / "name", "amdgpu\n")
        write(hw / "temp1_input", "44000\n")
        write(hw / "power1_input", "46282000\n")
        write(hw / "freq1_input", "600000000\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_every_field_of_an_apu(self):
        s = gpu.sysfs_sample(self.dev, "AMD Raphael")
        self.assertEqual(s.name, "AMD Raphael")
        self.assertEqual(s.util, 7.0)
        self.assertAlmostEqual(s.mem_used_mb, 25.02, places=1)
        self.assertEqual(s.mem_total_mb, 512.0)
        self.assertEqual(s.temp_c, 44.0)
        self.assertAlmostEqual(s.power_w, 46.28, places=2)
        self.assertEqual(s.clock_mhz, 600.0)

    def test_prefers_power1_average_when_both_exist(self):
        write(self.dev / "hwmon" / "hwmon2" / "power1_average", "12000000\n")
        self.assertEqual(gpu.sysfs_sample(self.dev).power_w, 12.0)

    def test_missing_hwmon_leaves_zeros_but_still_samples(self):
        import shutil
        shutil.rmtree(self.dev / "hwmon")
        s = gpu.sysfs_sample(self.dev)
        self.assertEqual(s.util, 7.0)
        self.assertEqual((s.temp_c, s.power_w, s.clock_mhz), (0.0, 0.0, 0.0))

    def test_name_falls_back_to_pci_id_when_pci_ids_is_unavailable(self):
        name = gpu.sysfs_name(self.dev, pci_ids=("/nonexistent/pci.ids",))
        self.assertEqual(name, "GPU 1002:164e")

    def test_name_prefers_product_name_when_present(self):
        write(self.dev / "product_name", "Radeon RX 7900 XTX\n")
        self.assertEqual(gpu.sysfs_name(self.dev), "Radeon RX 7900 XTX")


if __name__ == "__main__":
    unittest.main()
