"""The short CPU name shown on the Overview tile."""
from __future__ import annotations

import unittest

from archpm.sysinfo import short_cpu_name


class ShortName(unittest.TestCase):
    def test_common_models(self):
        cases = {
            "AMD Ryzen 7 7800X3D 8-Core Processor": "7800X3D",
            "AMD Ryzen 5 5600X 6-Core Processor": "5600X",
            "AMD Ryzen 9 7950X3D 16-Core Processor": "7950X3D",
            "AMD Ryzen 7 7840HS w/ Radeon 780M Graphics": "7840HS",
            "Intel(R) Core(TM) i7-13700K": "i7-13700K",
            "Intel(R) Core(TM) i5-8250U CPU @ 1.60GHz": "i5-8250U",
            "Intel(R) Core(TM) Ultra 7 155H": "Ultra 7 155H",
            "13th Gen Intel(R) Core(TM) i9-13900K": "13th Gen i9-13900K",
        }
        for model, want in cases.items():
            with self.subTest(model=model):
                self.assertEqual(short_cpu_name(model), want)

    def test_unknown_shape_falls_back_to_the_full_string(self):
        self.assertEqual(short_cpu_name("QEMU Virtual CPU version 2.5+"),
                         "QEMU Virtual version 2.5+")
        self.assertEqual(short_cpu_name(""), "")
