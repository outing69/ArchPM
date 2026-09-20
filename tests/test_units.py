"""One byte formatter, one rate formatter, one fixed-gigabyte form: every
size and speed the interface shows comes out of archpm/units.py, and no
page rolls its own. Through 0.2.59 there were three byte formatters with
the same output, two hand-rolled gigabyte divisions and three rate formats
with different floors."""
from __future__ import annotations

import unittest
from pathlib import Path

from archpm.units import GIB, KIB, MIB, gb, gigabytes, human_bytes, human_rate

PACKAGE = Path(__file__).resolve().parent.parent / "archpm"


class Bytes(unittest.TestCase):
    def test_steps_of_1024_no_decimals_for_bytes_one_above(self):
        self.assertEqual(human_bytes(0), "0 B")
        self.assertEqual(human_bytes(512), "512 B")
        self.assertEqual(human_bytes(1023), "1023 B")
        self.assertEqual(human_bytes(1024), "1.0 KB")
        self.assertEqual(human_bytes(1536), "1.5 KB")
        self.assertEqual(human_bytes(87.9 * KIB), "87.9 KB")
        self.assertEqual(human_bytes(MIB), "1.0 MB")
        self.assertEqual(human_bytes(3 * GIB), "3.0 GB")
        self.assertEqual(human_bytes(2**40), "1.0 TB")
        self.assertEqual(human_bytes(2**50), "1.0 PB")
        self.assertEqual(human_bytes(2**60), "1024.0 PB", "past petabytes it stays in PB")

    def test_the_widgets_qml_copy_has_the_same_steps(self):
        """QML cannot import units.py; its fmtBytes is held to the same
        shape here, by the text it must contain."""
        qml = (PACKAGE.parent / "plasmoid" / "package" / "contents" / "ui" / "main.qml"
               ).read_text(encoding="utf-8")
        self.assertIn('["B", "KB", "MB", "GB", "TB"]', qml)
        self.assertIn("n >= 1024", qml)
        self.assertIn("i === 0 ? n.toFixed(0) : n.toFixed(1)", qml)


class Gigabytes(unittest.TestCase):
    def test_always_gigabytes_with_the_decimals_asked_for(self):
        self.assertEqual(gigabytes(15.6 * GIB), "15.6 GB")
        self.assertEqual(gigabytes(16 * GIB, 0), "16 GB")
        self.assertEqual(gigabytes(0.4 * GIB), "0.4 GB", "a pair's small side stays in GB")
        self.assertEqual(gigabytes(12288 * MIB, 0), "12 GB", "a value in megabytes, via MIB")
        self.assertEqual(gb(15.6 * GIB), "15.6")
        self.assertEqual(gb(16 * GIB, 0), "16")
        self.assertEqual(f"{gb(15.6 * GIB)} / {gigabytes(16 * GIB, 0)}", "15.6 / 16 GB",
                         "the tray's pair, the unit once")


class Rates(unittest.TestCase):
    def test_bytes_per_second_blank_under_the_floor(self):
        self.assertEqual(human_rate(0), "", "the Network page: blank under a byte")
        self.assertEqual(human_rate(0.5), "")
        self.assertEqual(human_rate(1), "1 B/s")
        self.assertEqual(human_rate(300), "300 B/s")
        self.assertEqual(human_rate(1024), "1.0 KB/s")
        self.assertEqual(human_rate(87.9 * KIB), "87.9 KB/s")
        self.assertEqual(human_rate(1.5 * MIB), "1.5 MB/s")

    def test_the_disk_columns_floor_is_a_kilobyte_and_the_graphs_have_none(self):
        self.assertEqual(human_rate(1023, blank_below=1024), "")
        self.assertEqual(human_rate(1024, blank_below=1024), "1.0 KB/s",
                         "at exactly a kilobyte the column shows it (through 0.2.59 it did not)")
        self.assertEqual(human_rate(0, blank_below=0), "0 B/s", "a graph's legend at rest")


class OneOfEach(unittest.TestCase):
    """No page rolls its own: the unit tuple, the gigabyte division and the
    per-second suffix exist in units.py only."""

    def test_no_other_module_formats_bytes_gigabytes_or_rates(self):
        offenders = []
        for path in sorted(PACKAGE.rglob("*.py")):
            if path.name == "units.py":
                continue
            text = path.read_text(encoding="utf-8")
            for needle in ('"KB"', "2**30", "2 ** 30", "/ 1024", "}/s\"", "} GB\"", " GB\","):
                if needle in text:
                    offenders.append(f"{path.relative_to(PACKAGE.parent)}: {needle}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
