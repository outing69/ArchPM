"""What can be thrown away safely, and throwing it away. No Qt.

Only things a program rebuilds on its own: per-program caches under
~/.cache, Steam's shader caches, thumbnails, the pacman package cache (kept
to the last two versions of each package) and old journal logs. Never Proton
prefixes, saves, settings or documents. The user-level items are removed by
this module directly; the two that need root run through the helper as fixed
commands with no arguments from us.

Deleting is restricted twice: an item's path must resolve inside one of the
roots this module itself discovered, and symlinks are never followed. The
directory itself is kept and emptied, since some programs expect it to exist.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .appinfo import SteamIndex, steam_roots

_PACCACHE_DRY = re.compile(r"(\d+)\s+candidates.*?saved:\s*([\d.,]+)\s*([KMGT]i?B)")
_JOURNAL_USAGE = re.compile(r"take up\s+([\d.,]+)\s*([KMGT]?)B?\b", re.IGNORECASE)
_UNIT = {"": 1, "K": 1 << 10, "M": 1 << 20, "G": 1 << 30, "T": 1 << 40}

# Names under ~/.cache that deserve a friendlier label and explanation.
KNOWN_CACHES: dict[str, tuple[str, str]] = {
    "thumbnails": ("Thumbnails", "Previews of pictures and videos in file managers; rebuilt "
                                 "the next time a folder is opened."),
    "mesa_shader_cache": ("Mesa shader cache", "Compiled shaders for AMD and Intel graphics; games "
                                               "recompile them, so the first minutes may stutter."),
    "mesa_shader_cache_db": ("Mesa shader cache", "Compiled shaders for AMD and Intel graphics; "
                                                  "games recompile them, so the first minutes may "
                                                  "stutter."),
    "nvidia": ("NVIDIA shader cache", "Compiled shaders for the NVIDIA driver; games recompile "
                                      "them, so the first minutes may stutter."),
    "paru": ("paru build cache", "Downloaded sources and built packages from the AUR; paru "
                                 "downloads them again when needed."),
    "yay": ("yay build cache", "Downloaded sources and built packages from the AUR; yay "
                               "downloads them again when needed."),
    "pip": ("pip download cache", "Python packages pip downloaded; downloaded again when needed."),
    "go-build": ("Go build cache", "Compiled Go packages; rebuilt on the next build."),
    "winetricks": ("Winetricks downloads", "Installers Winetricks fetched; downloaded again "
                                           "when a prefix needs them."),
    "BraveSoftware": ("Brave cache", "Web pages and images Brave keeps for speed. Close Brave "
                                     "first; it recreates the cache as you browse."),
    "mozilla": ("Firefox cache", "Web pages and images Firefox keeps for speed. Close Firefox "
                                 "first; it recreates the cache as you browse."),
    "google-chrome": ("Chrome cache", "Web pages and images Chrome keeps for speed. Close Chrome "
                                      "first; it recreates the cache as you browse."),
    "chromium": ("Chromium cache", "Web pages and images Chromium keeps for speed. Close it "
                                   "first; it recreates the cache as you browse."),
    "spotify": ("Spotify cache", "Songs Spotify keeps for offline-ish playback; fetched again "
                                 "when played."),
    "JetBrains": ("JetBrains cache", "Indexes PyCharm and friends build for your projects; "
                                     "rebuilt on the next open, which takes a while."),
    "fontconfig": ("Font cache", "List of installed fonts; rebuilt automatically."),
}
MIN_CACHE_BYTES = 1 << 20  # ~/.cache entries smaller than this are lumped together

# Which running program a ~/.cache folder belongs to, by process name. A cache
# can be emptied while its program runs (Linux keeps open files alive and the
# program recreates what it misses), but the program may stumble for a moment
# and will start refilling it at once, so the tab says so before you confirm.
CACHE_OWNERS: dict[str, tuple[str, ...]] = {
    "BraveSoftware": ("brave",), "mozilla": ("firefox",), "google-chrome": ("chrome",),
    "chromium": ("chromium",), "spotify": ("spotify",), "vivaldi": ("vivaldi",),
    "JetBrains": ("pycharm", "idea", "clion", "webstorm", "goland", "rider", "phpstorm",
                  "datagrip", "rubymine"),
    "paru": ("paru",), "yay": ("yay",), "winetricks": ("winetricks",), "wine": ("wine",),
    # driver-level caches have no single owning program
    "nvidia": (), "mesa_shader_cache": (), "mesa_shader_cache_db": (), "fontconfig": (),
    "thumbnails": (),
}


def running_owner(item: CleanupItem, procs) -> str:
    """Display name of a running program this item belongs to, "" if none.
    `procs` are ProcSamples (name, app_name, steam_appid)."""
    if item.id.startswith("shader:"):
        appid = int(item.id.rsplit(":", 1)[1])
        for p in procs:
            if p.steam_appid == appid:
                return p.app_name or p.name
        return ""
    if item.id.startswith("cache:") and item.id != "cache:small":
        folder = item.id.split(":", 1)[1]
        known = CACHE_OWNERS.get(folder)
        for p in procs:
            if not p.cmdline:
                continue  # kernel threads such as irq/84-nvidia own no cache
            name = p.name.lower()
            # Exact names only: Brave's chrome_crashpad_handler is not Chrome, and
            # an unknown folder matches nothing but a process of the same name.
            hit = name in known if known is not None else name == folder.lower()
            if hit:
                return p.app_name or p.name
    return ""


@dataclass
class CleanupItem:
    id: str
    name: str
    description: str
    size: int                    # bytes; for root items an estimate
    needs_root: bool = False
    paths: list[Path] = field(default_factory=list)   # what gets emptied (user items)
    helper_command: str = ""                          # helper subcommand (root items)
    note: str = ""                                    # e.g. "close the program first"

    @property
    def kind(self) -> str:
        return "root" if self.needs_root else "user"


def dir_size(path: Path) -> int:
    """Bytes under a directory, symlinks not followed, errors skipped."""
    total = 0
    stack = [path]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_symlink():
                            continue
                        if e.is_dir(follow_symlinks=False):
                            stack.append(Path(e.path))
                        elif e.is_file(follow_symlinks=False):
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _parse_size(number: str, unit: str) -> int:
    return int(float(number.replace(",", ".")) * _UNIT.get(unit[:1].upper(), 1))


def parse_paccache_dry_run(text: str) -> tuple[int, int]:
    """(packages, bytes) from `paccache -dk2`; (0, 0) when nothing to remove."""
    m = _PACCACHE_DRY.search(text)
    if not m:
        return 0, 0
    return int(m.group(1)), _parse_size(m.group(2), m.group(3))


def parse_journal_usage(text: str) -> int:
    m = _JOURNAL_USAGE.search(text)
    return _parse_size(m.group(1), m.group(2)) if m else 0


def _run(*argv: str) -> str:
    if not shutil.which(argv[0]):
        return ""
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout + proc.stderr


class Cleaner:
    def __init__(self, cache_dir: Path | None = None, steam: SteamIndex | None = None,
                 runner=_run) -> None:
        self.cache_dir = cache_dir if cache_dir is not None else Path(
            os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"))
        self.steam = steam if steam is not None else SteamIndex(roots=steam_roots())
        self._run = runner
        self.roots: list[Path] = []   # directories deletion is confined to

    # -- scanning --------------------------------------------------------------
    def scan(self) -> list[CleanupItem]:
        items: list[CleanupItem] = []
        self.roots = []
        items += self._scan_cache_dir()
        items += self._scan_shader_caches()
        items += self._scan_pacman()
        items += self._scan_journal()
        items.sort(key=lambda i: (i.needs_root, -i.size))
        return items

    def _scan_cache_dir(self) -> list[CleanupItem]:
        if not self.cache_dir.is_dir():
            return []
        self.roots.append(self.cache_dir.resolve())
        out: list[CleanupItem] = []
        small: list[Path] = []
        small_total = 0
        for entry in sorted(self.cache_dir.iterdir()):
            if entry.is_symlink() or not entry.is_dir():
                continue
            if entry.name == "archpm":
                continue  # our own status link lives here
            size = dir_size(entry)
            if size < MIN_CACHE_BYTES:
                small.append(entry)
                small_total += size
                continue
            name, desc = KNOWN_CACHES.get(entry.name, (
                f"{entry.name} cache",
                f"Cache of {entry.name}; the program rebuilds it when it needs it."))
            out.append(CleanupItem(id=f"cache:{entry.name}", name=name, description=desc,
                                   size=size, paths=[entry]))
        if small:
            out.append(CleanupItem(
                id="cache:small", name=f"Other small caches ({len(small)})",
                description="Every other folder in ~/.cache, each under 1 MB.",
                size=small_total, paths=small))
        return out

    def _scan_shader_caches(self) -> list[CleanupItem]:
        out: list[CleanupItem] = []
        libs = self.steam.libraries()
        for lib in libs:
            base = lib / "steamapps" / "shadercache"
            if not base.is_dir():
                continue
            self.roots.append(base.resolve())
            for d in sorted(base.iterdir()):
                if d.is_symlink() or not d.is_dir() or not d.name.isdigit():
                    continue
                size = dir_size(d)
                if size < MIN_CACHE_BYTES:
                    continue
                appid = int(d.name)
                game = self.steam.name(appid) or f"Steam app {appid}"
                where = f" on {lib}" if len(libs) > 1 else ""
                out.append(CleanupItem(
                    id=f"shader:{lib}:{appid}", name=f"Shader cache: {game}",
                    description="Compiled shaders Steam prepared for this game. Steam downloads "
                                "or rebuilds them; the first launch afterwards may stutter."
                                + where,
                    size=size, paths=[d]))
        # The same game can leave shader caches in several libraries (it moved,
        # or Steam keeps leftovers): tell them apart by app id.
        counts: dict[str, int] = {}
        for it in out:
            counts[it.name] = counts.get(it.name, 0) + 1
        for it in out:
            if counts[it.name] > 1:
                it.name += f" ({it.id.rsplit(':', 1)[1]})"
        return out

    def _scan_pacman(self) -> list[CleanupItem]:
        if not shutil.which("paccache"):
            return [CleanupItem(
                id="pacman", name="Package cache (pacman)",
                description="Old package versions in /var/cache/pacman/pkg. Needs the "
                            "'pacman-contrib' package for paccache before it can be cleaned.",
                size=0, needs_root=True, helper_command="", note="install pacman-contrib")]
        count, size = parse_paccache_dry_run(self._run("paccache", "-dk2"))
        return [CleanupItem(
            id="pacman", name="Package cache (pacman)",
            description=f"Old package versions in /var/cache/pacman/pkg: {count} files that are "
                        "not among the last two versions of a package. Kept versions still "
                        "let you downgrade.",
            size=size, needs_root=True, helper_command="paccache-clean")]

    def _scan_journal(self) -> list[CleanupItem]:
        size = parse_journal_usage(self._run("journalctl", "--disk-usage"))
        keep = 100 << 20
        return [CleanupItem(
            id="journal", name="System logs (journal)",
            description=f"Logs older than the most recent 100 MB. The journal takes "
                        f"{human(size)}; recent logs stay for troubleshooting.",
            size=max(0, size - keep), needs_root=True, helper_command="journal-vacuum")]

    # -- deleting (user items only) ----------------------------------------------
    def _allowed(self, path: Path) -> bool:
        try:
            real = path.resolve(strict=True)
        except OSError:
            return False
        if path.is_symlink():
            return False
        return any(real == r or r in real.parents for r in self.roots)

    def empty(self, item: CleanupItem) -> tuple[int, list[str]]:
        """Empty every path of a user item. Returns (bytes freed, errors)."""
        if item.needs_root:
            raise ValueError("root items go through the helper")
        freed = 0
        errors: list[str] = []
        for path in item.paths:
            if not self._allowed(path):
                errors.append(f"{path}: outside the allowed cache folders, skipped")
                continue
            before = dir_size(path)
            try:
                with os.scandir(path) as it:
                    for e in it:
                        p = Path(e.path)
                        try:
                            if e.is_dir(follow_symlinks=False):
                                shutil.rmtree(p)
                            else:
                                p.unlink()
                        except OSError as exc:
                            errors.append(f"{p}: {exc.strerror or exc}")
            except OSError as exc:
                errors.append(f"{path}: {exc.strerror or exc}")
                continue
            freed += before - dir_size(path)
        return freed, errors
