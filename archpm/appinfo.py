"""Friendly names and icons for processes.

Two sources, no Qt:

- `.desktop` entries from the XDG application directories. Their `Exec` line
  is matched against a process's command line, so `brave --type=renderer`
  becomes "Brave Web Browser" with the brave icon, and `python3 -m archpm`
  becomes "ArchPM" without every other python3 following suit.
- Steam. A process launched by Steam carries `SteamAppId` in its environment;
  the game's name is in `appmanifest_<id>.acf` in whichever library folder
  holds it, and Steam drops an icon per game in ~/.local/share/icons. Only the
  game binary itself is renamed (Windows .exe under Proton, or anything under
  steamapps/common); the helpers around it (wineserver, reaper) keep their
  names but share the icon.

Icons are returned as either an icon-theme name or an absolute path; the UI
turns those into QIcons. Everything is cached per pid.
"""
from __future__ import annotations

import os
import re
import shlex
import time
from dataclasses import dataclass
from pathlib import Path

_FIELD_CODE = re.compile(r"^%[a-zA-Z%]$")
_VDF_PATH = re.compile(r'"path"\s+"((?:[^"\\]|\\.)*)"')
_ACF_NAME = re.compile(r'"name"\s+"((?:[^"\\]|\\.)*)"')
# Exec lines that start with one of these say nothing on their own: only match
# them together with the arguments that follow.
_INTERPRETERS = {"python", "python2", "python3", "sh", "bash", "zsh", "env", "wine", "wine64",
                 "java", "node", "perl", "ruby", "electron", "flatpak", "snap"}
_STEAM_ICON_SIZES = ("48x48", "32x32", "64x64", "128x128", "256x256", "24x24", "16x16",
                     "96x96", "192x192")


@dataclass(frozen=True)
class AppInfo:
    name: str = ""          # human-readable name, "" when unknown
    icon: str = ""          # icon theme name or absolute file path, "" when none
    steam_appid: int = 0

    def __bool__(self) -> bool:
        return bool(self.name or self.icon)


NONE = AppInfo()


def _basename(token: str) -> str:
    """Basename that also understands Windows paths from Proton (Z:\\...\\Game.exe)."""
    return token.replace("\\", "/").rpartition("/")[2]


# -- .desktop entries -----------------------------------------------------------
def data_dirs() -> list[Path]:
    home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    return [Path(home), *(Path(d) for d in dirs.split(":") if d)]


def parse_desktop_entry(text: str) -> dict[str, str]:
    """Keys of the [Desktop Entry] group only; actions have their own Exec lines."""
    out: dict[str, str] = {}
    in_group = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            in_group = line == "[Desktop Entry]"
            continue
        if not in_group or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out.setdefault(key.strip(), value.strip())
    return out


def exec_tokens(exec_line: str) -> tuple[str, ...]:
    """`Exec=env FOO=1 /usr/bin/brave %U` -> ("brave",). Field codes and env
    assignments are dropped; paths are reduced to basenames."""
    try:
        tokens = shlex.split(exec_line)
    except ValueError:
        return ()
    if tokens and _basename(tokens[0]) == "env":
        tokens = tokens[1:]
        while tokens and "=" in tokens[0] and not tokens[0].startswith("-"):
            tokens = tokens[1:]
    return tuple(_basename(t) for t in tokens if not _FIELD_CODE.match(t))


class DesktopIndex:
    """Exec-prefix -> (name, icon) over every visible application entry."""

    def __init__(self, dirs: list[Path] | None = None) -> None:
        self.dirs = dirs if dirs is not None else [d / "applications" for d in data_dirs()]
        # first token -> list of (remaining tokens, name, icon, hidden)
        self._by_first: dict[str, list[tuple[tuple[str, ...], str, str, bool]]] = {}
        self.scan()

    def scan(self) -> None:
        seen: set[str] = set()
        self._by_first = {}
        for d in self.dirs:
            try:
                files = sorted(d.glob("*.desktop"))
            except OSError:
                continue
            for f in files:
                if f.name in seen:
                    continue  # an earlier (higher-precedence) dir already provided it
                seen.add(f.name)
                try:
                    entry = parse_desktop_entry(f.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    continue
                if entry.get("Type", "Application") != "Application" or "Exec" not in entry:
                    continue
                tokens = exec_tokens(entry["Exec"])
                if not tokens or (len(tokens) == 1 and tokens[0] in _INTERPRETERS):
                    continue
                hidden = (entry.get("NoDisplay", "").lower() == "true"
                          or entry.get("Hidden", "").lower() == "true")
                name = entry.get("Name", "") or f.stem
                self._by_first.setdefault(tokens[0], []).append(
                    (tokens[1:], name, entry.get("Icon", ""), hidden)
                )
        for entries in self._by_first.values():
            # longest prefix first; among equals, visible entries before hidden ones
            entries.sort(key=lambda e: (-len(e[0]), e[3]))

    def match(self, argv: list[str]) -> AppInfo:
        if not argv:
            return NONE
        first = _basename(argv[0])
        candidates = self._by_first.get(first)
        if not candidates:
            return NONE
        rest = [_basename(a) for a in argv[1:]]
        for tail, name, icon, _hidden in candidates:
            if tuple(rest[:len(tail)]) == tail:
                return AppInfo(name=name, icon=icon)
        return NONE


# -- Steam ----------------------------------------------------------------------
def steam_roots() -> list[Path]:
    home = Path(os.path.expanduser("~"))
    candidates = [home / ".steam" / "root", home / ".local" / "share" / "Steam",
                  home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam"]
    out: list[Path] = []
    for c in candidates:
        try:
            r = c.resolve()
        except OSError:
            continue
        if r.is_dir() and r not in out:
            out.append(r)
    return out


def parse_library_folders(text: str) -> list[str]:
    return [m.replace("\\\\", "\\") for m in _VDF_PATH.findall(text)]


def parse_appmanifest_name(text: str) -> str:
    m = _ACF_NAME.search(text)
    return m.group(1).replace('\\"', '"') if m else ""


def read_environ(pid: int) -> dict[str, str]:
    """Environment of a process; empty when it is not ours (or gone)."""
    try:
        with open(f"/proc/{pid}/environ", "rb") as fh:
            raw = fh.read()
    except OSError:
        return {}
    out: dict[str, str] = {}
    for chunk in raw.split(b"\0"):
        if b"=" in chunk:
            k, _, v = chunk.partition(b"=")
            out[k.decode(errors="replace")] = v.decode(errors="replace")
    return out


def is_game_binary(argv0: str, name: str) -> bool:
    low = argv0.lower()
    return low.endswith(".exe") or name.lower().endswith(".exe") or "/steamapps/common/" in low


class SteamIndex:
    def __init__(self, roots: list[Path] | None = None, icon_dir: Path | None = None) -> None:
        self.roots = roots if roots is not None else steam_roots()
        self.icon_dir = icon_dir if icon_dir is not None else (
            Path(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"))
            / "icons" / "hicolor"
        )
        self._libraries: list[Path] | None = None
        self._names: dict[int, str] = {}
        self._icons: dict[int, str] = {}

    def libraries(self) -> list[Path]:
        if self._libraries is None:
            libs: list[Path] = []
            for root in self.roots:
                libs.append(root)
                vdf = root / "steamapps" / "libraryfolders.vdf"
                try:
                    text = vdf.read_text(encoding="utf-8", errors="replace")
                    libs.extend(Path(p) for p in parse_library_folders(text))
                except OSError:
                    pass
            seen: set[Path] = set()
            self._libraries = [p for p in libs if not (p in seen or seen.add(p))]
        return self._libraries

    def name(self, appid: int) -> str:
        if appid in self._names:
            return self._names[appid]
        found = ""
        for lib in self.libraries():
            f = lib / "steamapps" / f"appmanifest_{appid}.acf"
            try:
                found = parse_appmanifest_name(f.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if found:
                break
        self._names[appid] = found
        return found

    def icon(self, appid: int) -> str:
        if appid in self._icons:
            return self._icons[appid]
        found = ""
        for size in _STEAM_ICON_SIZES:
            p = self.icon_dir / size / "apps" / f"steam_icon_{appid}.png"
            if p.is_file():
                found = str(p)
                break
        self._icons[appid] = found
        return found

    @staticmethod
    def appid_of(pid: int) -> int:
        env = read_environ(pid)
        for key in ("SteamAppId", "SteamGameId"):
            value = env.get(key, "")
            if value.isdigit():
                return int(value)
        return 0


# -- resolver used by the sampler -------------------------------------------------
class AppResolver:
    """pid -> AppInfo, computed once per (pid, name) and remembered."""

    RESCAN_S = 900.0  # pick up newly installed apps without restarting

    def __init__(self, desktop: DesktopIndex | None = None,
                 steam: SteamIndex | None = None) -> None:
        self.desktop = desktop if desktop is not None else DesktopIndex()
        self.steam = steam if steam is not None else SteamIndex()
        self._cache: dict[int, tuple[str, AppInfo]] = {}  # pid -> (name it was computed for, info)
        self._scanned = time.monotonic()

    def lookup(self, pid: int, name: str, argv: list[str], owned: bool) -> AppInfo:
        hit = self._cache.get(pid)
        if hit is not None and hit[0] == name:
            return hit[1]
        if time.monotonic() - self._scanned > self.RESCAN_S:
            self.desktop.scan()
            self._scanned = time.monotonic()
        info = self.resolve(pid, name, argv, owned)
        self._cache[pid] = (name, info)
        return info

    def resolve(self, pid: int, name: str, argv: list[str], owned: bool) -> AppInfo:
        appid = self.steam.appid_of(pid) if owned else 0
        if appid:
            game = self.steam.name(appid)
            icon = self.steam.icon(appid)
            argv0 = argv[0] if argv else ""
            if game and is_game_binary(argv0, name):
                return AppInfo(name=game, icon=icon, steam_appid=appid)
            desktop = self.desktop.match(argv)
            return AppInfo(name=desktop.name, icon=icon or desktop.icon, steam_appid=appid)
        return self.desktop.match(argv)

    def forget(self, pid: int) -> None:
        self._cache.pop(pid, None)
