"""The machine's specs, as a list of sections of (label, value) pairs.

Everything is read once on request from /proc, /sys, psutil and, for NVIDIA,
one nvidia-smi call. No root, nothing that changes second to second: that is
what the Overview is for. Meant to be read, copied into a forum post, or
screenshotted.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time
from pathlib import Path

import psutil

from . import __version__
from .appinfo import read_environ
from .gpu import sysfs_name

Section = tuple[str, list[tuple[str, str]]]


def _read(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _os_release() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in _read("/etc/os-release").splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            out[k] = v.strip().strip('"')
    return out


def _cmd(*argv: str, timeout: float = 3.0) -> str:
    if not shutil.which(argv[0]):
        return ""
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout.strip()


def system_section() -> Section:
    rel = _os_release()
    env = os.environ
    desktop = env.get("XDG_CURRENT_DESKTOP", "") or "unknown"
    session = env.get("XDG_SESSION_TYPE", "")
    if not session:
        session = "wayland" if env.get("WAYLAND_DISPLAY") else "x11"
    plasma = _cmd("plasmashell", "--version").replace("plasmashell", "Plasma").strip()
    up = time.time() - psutil.boot_time()
    rows = [
        ("Hostname", platform.node()),
        ("Distribution", rel.get("PRETTY_NAME", "") or platform.system()),
        ("Kernel", platform.release()),
        ("Desktop", f"{desktop} ({session})" + (f", {plasma}" if plasma else "")),
        ("Uptime", f"{int(up // 86400)} d {int(up % 86400 // 3600)} h {int(up % 3600 // 60)} min"),
    ]
    board = " ".join(x for x in (_read("/sys/devices/virtual/dmi/id/board_vendor"),
                                 _read("/sys/devices/virtual/dmi/id/board_name")) if x)
    bios = " ".join(x for x in (_read("/sys/devices/virtual/dmi/id/bios_version"),
                                _read("/sys/devices/virtual/dmi/id/bios_date")) if x)
    if board:
        rows.append(("Motherboard", board))
    if bios:
        rows.append(("BIOS", bios))
    return "System", rows


def processor_section() -> Section:
    model = ""
    for line in _read("/proc/cpuinfo").splitlines():
        if line.startswith("model name"):
            model = line.partition(":")[2].strip()
            break
    physical = psutil.cpu_count(logical=False) or 0
    logical = psutil.cpu_count(logical=True) or 0
    rows = [("Model", model or platform.processor() or "unknown"),
            ("Cores / threads", f"{physical} / {logical}")]
    try:
        f = psutil.cpu_freq()
        if f and f.max:
            rows.append(("Max clock", f"{f.max:.0f} MHz"))
    except (OSError, AttributeError):
        pass
    governor = _read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
    if governor:
        rows.append(("Governor", governor))
    return "Processor", rows


def memory_section() -> Section:
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    rows = [("RAM", _human(vm.total)), ("Swap", _human(sw.total) if sw.total else "none")]
    zram = [p for p in Path("/sys/block").glob("zram*")]
    if zram:
        rows.append(("zram", ", ".join(z.name for z in zram)))
    return "Memory", rows


def graphics_section() -> Section:
    rows: list[tuple[str, str]] = []
    smi = _cmd("nvidia-smi", "--query-gpu=name,driver_version,memory.total",
               "--format=csv,noheader,nounits")
    for i, line in enumerate(ln for ln in smi.splitlines() if ln.strip()):
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3:
            rows.append((f"GPU {i}", f"{parts[0]}, {parts[2]} MB, driver {parts[1]}"))
    for card in sorted(Path("/sys/class/drm").glob("card[0-9]*")):
        dev = card / "device"
        if not (dev / "vendor").exists():
            continue
        try:
            driver = os.path.basename(os.readlink(dev / "driver"))
        except OSError:
            driver = ""
        if driver == "nvidia":
            continue  # already listed via nvidia-smi, with more detail
        name = sysfs_name(dev)
        vram = _read(str(dev / "mem_info_vram_total"))
        detail = f"{name}, driver {driver}" if driver else name
        if vram.isdigit():
            detail += f", {int(vram) // (1 << 20)} MB"
        rows.append((card.name, detail))
    return "Graphics", rows or [("GPU", "none detected")]


def storage_section() -> Section:
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    for part in psutil.disk_partitions(all=False):
        if part.device in seen or part.fstype in ("squashfs", "overlay"):
            continue
        seen.add(part.device)
        try:
            u = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        rows.append((part.mountpoint, f"{_human(u.used)} of {_human(u.total)} used "
                                       f"({u.percent:.0f}%), {part.fstype}, {part.device}"))
    return "Storage", rows


def network_section() -> Section:
    rows: list[tuple[str, str]] = []
    stats = psutil.net_if_stats()
    for name, addrs in psutil.net_if_addrs().items():
        if name == "lo":
            continue
        v4 = [a.address for a in addrs if a.family.name == "AF_INET"]
        st = stats.get(name)
        state = "up" if st and st.isup else "down"
        speed = f", {st.speed} Mb/s" if st and st.speed > 0 else ""
        rows.append((name, f"{state}{speed}" + (f", {', '.join(v4)}" if v4 else "")))
    return "Network", rows


def archpm_section() -> Section:
    try:
        import PySide6
        qt = PySide6.__version__
    except ImportError:
        qt = "not installed"
    candidates = ("/usr/lib/archpm/archpm-helper", "/usr/local/lib/archpm/archpm-helper")
    helper = next((p for p in candidates if Path(p).is_file()), "not installed")
    return "ArchPM", [
        ("Version", __version__),
        ("Python", platform.python_version()),
        ("PySide6", qt),
        ("psutil", psutil.__version__),
        ("Root helper", helper),
        ("Session", f"uid {os.getuid()}, {read_environ(os.getpid()).get('XDG_SESSION_ID', '?')}"),
    ]


def gather() -> list[Section]:
    return [system_section(), processor_section(), memory_section(), graphics_section(),
            storage_section(), network_section(), archpm_section()]


def as_text(sections: list[Section]) -> str:
    out: list[str] = []
    for title, rows in sections:
        out.append(f"## {title}")
        width = max((len(k) for k, _ in rows), default=0)
        out.extend(f"{k.ljust(width)}  {v}" for k, v in rows)
        out.append("")
    return "\n".join(out).rstrip() + "\n"
