"""Friendly names and icons for processes.

Two sources, no Qt:

- `.desktop` entries from the XDG application directories. Their `Exec` line
  is matched against a process's command line, so `brave --type=renderer`
  becomes "Brave Web Browser" with the brave icon, and `python3 -m archpm`
  becomes "ArchPM" without every other python3 following suit.
- Steam. A process launched by Steam carries `SteamAppId` in its environment;
  the game's name is in `appmanifest_<id>.acf` in whichever library folder
  holds it, and Steam drops an icon per game in ~/.local/share/icons. Only
  processes whose executable lives in the game's own install directory
  (`steamapps/common/<installdir>/`, as the manifest states it) are renamed.
  Everything else that carries the app id -- reaper, the Steam runtime, Proton,
  wineserver and the Windows services Wine spawns (services.exe, explorer.exe)
  -- keeps its name but shares the icon.

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
_ACF_INSTALLDIR = re.compile(r'"installdir"\s+"((?:[^"\\]|\\.)*)"')
# Exec lines that start with one of these say nothing on their own: only match
# them together with the arguments that follow.
_INTERPRETERS = {"python", "python2", "python3", "sh", "bash", "zsh", "env", "wine", "wine64",
                 "java", "node", "perl", "ruby", "electron", "flatpak", "snap"}
_STEAM_ICON_SIZES = ("48x48", "32x32", "64x64", "128x128", "256x256", "24x24", "16x16",
                     "96x96", "192x192")


# freedesktop menu categories collapsed to a handful a user recognises. First
# match wins, so the specific ones (WebBrowser, Game) come before the broad
# ones (Network, Utility). "Other" is a program whose entry names none of these.
_CATEGORY_RULES: tuple[tuple[str, frozenset[str]], ...] = (
    ("Browser", frozenset({"WebBrowser"})),
    ("Game", frozenset({"Game"})),
    ("Communication", frozenset({"InstantMessaging", "Chat", "Email", "VideoConference",
                                 "IRCClient", "Telephony"})),
    ("Development", frozenset({"Development", "IDE", "TextEditor"})),
    ("Media", frozenset({"AudioVideo", "Audio", "Video", "Player", "Music", "TV",
                         "Recorder"})),
    ("Graphics", frozenset({"Graphics", "Photography", "2DGraphics", "3DGraphics",
                            "RasterGraphics", "VectorGraphics"})),
    ("Office", frozenset({"Office", "WordProcessor", "Spreadsheet", "Presentation",
                          "Finance"})),
    ("System", frozenset({"System", "Settings", "Monitor", "PackageManager",
                          "TerminalEmulator", "Security"})),
    ("Utility", frozenset({"Utility", "FileManager", "FileTools", "Archiving",
                           "Viewer", "Calculator", "Clock"})),
    ("Network", frozenset({"Network", "FileTransfer", "P2P", "RemoteAccess"})),
    ("Science", frozenset({"Education", "Science", "Math"})),
)
CATEGORIES = tuple(name for name, _ in _CATEGORY_RULES) + ("Other",)


def coarse_category(categories: str) -> str:
    """`Categories=Network;WebBrowser;Qt;` -> "Browser". "Other" when nothing matches."""
    have = {c.strip() for c in categories.split(";") if c.strip()}
    for label, members in _CATEGORY_RULES:
        if have & members:
            return label
    return "Other"


# Plain-language descriptions for the background pieces of a KDE/Arch desktop,
# keyed by executable name. Shown as tooltips in the process list and in the
# Startup tab, where "kglobalacceld" alone would tell a beginner nothing.
DESCRIPTIONS: dict[str, str] = {
    "plasmashell": "The desktop itself: panels, widgets, wallpaper, system tray.",
    "kwin_wayland": "KWin, the window manager and compositor: draws and moves every window.",
    "kwin_wayland_wrapper": "Starts and restarts KWin, the window manager and compositor.",
    "kwin_x11": "KWin, the window manager and compositor: draws and moves every window.",
    "kglobalacceld": "Global keyboard shortcuts (Meta key, media keys, custom shortcuts).",
    "org_kde_powerdevil": "Power management: screen dimming, sleep, brightness, battery.",
    "polkit-kde-authentication-agent-1": "Asks for your password when an app needs admin rights.",
    "xembedsniproxy": "System tray icons for older applications.",
    "gmenudbusmenuproxy": "Application menus for GTK programs.",
    "pam_kwallet_init": "Unlocks your KDE Wallet (saved passwords) at login.",
    "kaccess": "Accessibility features: sticky keys, slow keys, screen reader hooks.",
    "knighttimed": "Night Light: warmer screen colours in the evening.",
    "plasma-fallback-session-restore": "Reopens the programs from your previous session.",
    "ksmserver": "Session manager: remembers open programs for the next login.",
    "kded6": "KDE background services (network status, device notifications, ...).",
    "kactivitymanagerd": "KDE Activities and recent documents.",
    "baloo_file": "File indexing for the search in the launcher and Dolphin.",
    "xdg-user-dirs-update": "Keeps your Desktop, Downloads and Documents folder names up to date.",
    "at-spi-bus-launcher": "Accessibility bus used by screen readers.",
    "gnome-keyring-daemon": "Password storage for GNOME and GTK programs.",
    "kdeconnectd": "KDE Connect: phone notifications, file sharing, remote control.",
    "limine-snapper-notify": "Limine bootloader: notifies about snapper snapshots.",
    "limine-snapper-restore": "Limine bootloader: notifies after a snapshot restore.",
    "octopi-notifier": "Octopi: tells you when package updates are available.",
    "protonvpn-app": "Proton VPN client.",
    "pipewire": "Audio and video server: every sound on the system goes through it.",
    "pipewire-pulse": "PulseAudio compatibility for PipeWire; older programs need it for sound.",
    "wireplumber": "Session manager for PipeWire: routes audio between programs and devices.",
    "dbus-broker": "Message bus: how desktop programs talk to each other.",
    "xdg-desktop-portal": "Portals: file dialogs, screen sharing, permissions for sandboxed apps.",
    "xdg-desktop-portal-kde": "KDE's file dialogs and screen sharing for sandboxed apps.",
    "xdg-desktop-portal-gtk": "GTK file dialogs for sandboxed apps.",
    "steamwebhelper": "Steam's built-in browser (store, library, overlay).",
    "reaper": "Steam's launcher wrapper that keeps track of a game's processes.",
    "srt-bwrap": "Steam Linux Runtime sandbox around a game.",
    "pv-adverb": "Steam Linux Runtime helper inside the sandbox.",
    "wineserver": "Wine/Proton core: emulates the Windows kernel for a game.",
    "services.exe": "Wine/Proton: emulated Windows service manager.",
    "explorer.exe": "Wine/Proton: emulated Windows shell (needed by many games).",
}

# Executables that make up the desktop session. Switching their autostart entry
# off is the classic way to break a login; the Startup tab asks twice.
DESKTOP_PARTS = frozenset({
    "plasmashell", "kwin_wayland", "kwin_wayland_wrapper", "kwin_x11", "kglobalacceld",
    "org_kde_powerdevil", "polkit-kde-authentication-agent-1", "xembedsniproxy",
    "gmenudbusmenuproxy", "pam_kwallet_init", "kaccess", "plasma-fallback-session-restore",
    "ksmserver", "kded6", "at-spi-bus-launcher", "gnome-keyring-daemon", "xdg-user-dirs-update",
})


def describe(executable: str) -> str:
    """Description for an executable path or name; "" when we have none."""
    return DESCRIPTIONS.get(_basename(executable), "")


@dataclass(frozen=True)
class AppInfo:
    name: str = ""          # human-readable name, "" when unknown
    icon: str = ""          # icon theme name or absolute file path, "" when none
    steam_appid: int = 0
    category: str = ""      # one of CATEGORIES for a program, "" otherwise
    hidden: bool = False    # matched a NoDisplay entry: named, but not a "program"

    @property
    def program(self) -> bool:
        """Something a user would recognise: a visible menu entry or a Steam game."""
        return bool(self.steam_appid) or (bool(self.name or self.icon) and not self.hidden)

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
        # first token -> list of (remaining tokens, name, icon, hidden, category)
        self._by_first: dict[str, list[tuple[tuple[str, ...], str, str, bool, str]]] = {}
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
                    (tokens[1:], name, entry.get("Icon", ""), hidden,
                     coarse_category(entry.get("Categories", "")))
                )
        for entries in self._by_first.values():
            # longest prefix first; among equals, visible entries before hidden ones
            entries.sort(key=lambda e: (-len(e[0]), e[3]))

    def match(self, argv: list[str]) -> AppInfo:
        if not argv:
            return NONE
        first = _basename(argv[0])
        candidates = self._by_first.get(first)
        if candidates:
            rest = [_basename(a) for a in argv[1:]]
            for tail, name, icon, hidden, category in candidates:
                if tuple(rest[:len(tail)]) == tail:
                    return AppInfo(name=name, icon=icon, category=category, hidden=hidden)
        # `bash /home/x/.local/share/Steam/steam.sh` is how Steam actually runs:
        # a wrapper script that stays alive as the parent of the real binary.
        # Name it after the script when a plain entry for that name exists.
        if first in _INTERPRETERS and len(argv) > 1 and not argv[1].startswith("-"):
            script = _basename(argv[1]).rsplit(".", 1)[0]
            for tail, name, icon, hidden, category in self._by_first.get(script, ()):
                if not tail:
                    return AppInfo(name=name, icon=icon, category=category, hidden=hidden)
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


def parse_appmanifest(text: str) -> tuple[str, str]:
    """(name, installdir) from an appmanifest_<id>.acf; "" for whatever is missing."""
    name = _ACF_NAME.search(text)
    installdir = _ACF_INSTALLDIR.search(text)
    return (name.group(1).replace('\\"', '"') if name else "",
            installdir.group(1).replace('\\"', '"') if installdir else "")


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


def process_cwd(pid: int) -> str:
    """Working directory of a process; "" when it is not ours or gone."""
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return ""


def is_game_binary(argv0: str, name: str, installdir: str) -> bool:
    """True when the executable lives in the game's own install directory.

    Windows paths from Proton (Z:\\...\\steamapps\\common\\CULTIC\\CULTIC.exe) are
    normalised first. Crash handlers that ship with the game are not "the game".
    """
    if not installdir:
        return False
    path = argv0.replace("\\", "/").lower()
    if f"/steamapps/common/{installdir.lower()}/" not in path:
        return False
    # comm is cut to 15 chars ("UnityCrashHandl"), so look at the file name too
    return "crashhandler" not in name.lower() and "crashhandler" not in _basename(path)


class SteamIndex:
    def __init__(self, roots: list[Path] | None = None, icon_dir: Path | None = None) -> None:
        self.roots = roots if roots is not None else steam_roots()
        self.icon_dir = icon_dir if icon_dir is not None else (
            Path(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"))
            / "icons" / "hicolor"
        )
        self._libraries: list[Path] | None = None
        self._apps: dict[int, tuple[str, str]] = {}   # appid -> (name, installdir)
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

    def app(self, appid: int) -> tuple[str, str]:
        """(name, installdir) of an installed app, ("", "") if unknown."""
        if appid in self._apps:
            return self._apps[appid]
        found = ("", "")
        for lib in self.libraries():
            f = lib / "steamapps" / f"appmanifest_{appid}.acf"
            try:
                found = parse_appmanifest(f.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if found[0]:
                break
        self._apps[appid] = found
        return found

    def name(self, appid: int) -> str:
        return self.app(appid)[0]

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

    def resolve(self, pid: int, name: str, argv: list[str], owned: bool,
                cwd_of=process_cwd) -> AppInfo:
        appid = self.steam.appid_of(pid) if owned else 0
        if appid:
            game, installdir = self.steam.app(appid)
            icon = self.steam.icon(appid)
            argv0 = argv[0] if argv else ""
            if argv0.lower().endswith(".exe") and "/" not in argv0 and "\\" not in argv0:
                # Proton often starts a game as a bare "Game.exe" from inside
                # the game's directory; the working directory tells us where.
                # Only for .exe: Proton's own python3 also runs from there.
                cwd = cwd_of(pid)
                if cwd:
                    argv0 = f"{cwd}/{argv0}"
            if game and is_game_binary(argv0, name, installdir):
                return AppInfo(name=game, icon=icon, steam_appid=appid, category="Game")
            desktop = self.desktop.match(argv)
            return AppInfo(name=desktop.name, icon=icon or desktop.icon, steam_appid=appid,
                           category="Game")
        return self.desktop.match(argv)

    def forget(self, pid: int) -> None:
        self._cache.pop(pid, None)
