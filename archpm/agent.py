"""Headless sampler daemon: sample, publish status.json, repeat.

Runs as a systemd --user service so the desktop widgets keep working when the
GUI is closed. Measured on a 7800X3D over 3 h 19 min of ordinary desktop use
(September 2026): 3.6% of one core in total, 2.7% the sampler itself, 0.9% the
nvidia-smi pmon helper and 0.1% the nvidia-smi query loop; the README's table
carries the same figures.
"""
from __future__ import annotations

import argparse
import signal
import sys
import time

from .gpu import GpuMonitor
from .publisher import PublishError, publish
from .sampler import Sampler

NO_SAFE_DIR = 3   # exit status: the status directory is not ours; see RestartPreventExitStatus


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="archpm-agent", description="ArchPM background sampler")
    ap.add_argument("-i", "--interval", type=float, default=2.0, help="seconds between samples")
    ap.add_argument("-n", "--top", type=int, default=5,
                    help="number of top processes in status.json")
    ap.add_argument("--once", action="store_true", help="take one sample, then exit")
    args = ap.parse_args(argv)

    gpu = GpuMonitor()
    gpu.start()
    sampler = Sampler(gpu, group_memory=False)
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
        try:
            path = publish(snap)
        except PublishError as exc:
            # Nowhere safe to write: say so and stop. Exit status 3 tells
            # systemd not to restart us into the same wall.
            print(f"archpm-agent: not publishing: {exc}", file=sys.stderr)
            gpu.stop()
            return NO_SAFE_DIR
        if args.once:
            print(path)
            print(path.read_text())
            break
        time.sleep(max(0.0, args.interval - (time.monotonic() - start)))

    gpu.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
