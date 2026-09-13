"""Headless sampler daemon: sample, publish status.json, repeat.

Runs as a systemd --user service so the desktop widget keeps working when the
GUI is closed. Costs ~1% of one core on a 7800X3D.
"""
from __future__ import annotations

import argparse
import signal
import sys
import time

from .gpu import GpuMonitor
from .publisher import publish, status_path
from .sampler import Sampler


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="archpm-agent", description="ArchPM background sampler")
    ap.add_argument("-i", "--interval", type=float, default=2.0, help="seconds between samples")
    ap.add_argument("-n", "--top", type=int, default=5, help="number of top processes in status.json")
    ap.add_argument("--once", action="store_true", help="take one sample, then exit")
    args = ap.parse_args(argv)

    gpu = GpuMonitor()
    gpu.start()
    sampler = Sampler(gpu)
    sampler.prime()

    running = True

    def _stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    if not args.once:
        time.sleep(min(args.interval, 1.0))  # give pmon/cpu_percent a baseline

    while running:
        start = time.monotonic()
        snap = sampler.sample()
        path = publish(snap)
        if args.once:
            print(path)
            print(path.read_text())
            break
        time.sleep(max(0.0, args.interval - (time.monotonic() - start)))

    gpu.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
