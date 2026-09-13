"""What starts when you log in: XDG autostart entries, and switching them off.

Sources, in order of precedence: `$XDG_CONFIG_HOME/autostart` (yours), then
each directory in `$XDG_CONFIG_DIRS/autostart` (the system's, `/etc/xdg` by
default). A file in your directory with the same name as a system one
replaces it; that is also how an entry is disabled without touching anything
outside your home: a copy with `Hidden=true`. Enabling again removes that copy
when the system file still exists, or flips the line in an entry that was
yours to begin with. Nothing here needs root and nothing is ever deleted
except an override ArchPM wrote itself.

`OnlyShowIn` / `NotShowIn` decide whether an entry applies to the running
desktop; entries for other desktops are listed but marked, so a GNOME-only
helper on a Plasma system is not mistaken for something that runs.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .appinfo import DESKTOP_PARTS, coarse_category, describe, exec_tokens, parse_desktop_entry

OVERRIDE_MARK = "X-ArchPM-Override"


@dataclass
class StartupEntry:
    id: str                     # file name, e.g. "org.kde.kdeconnect.daemon.desktop"
    name: str
    icon: str
    exec: str
    path: Path                  # the file that is in effect (yours or the system's)
    system_path: Path | None    # the system file, if any
    user_path: Path | None      # your file, if any
    enabled: bool               # not Hidden
    for_this_desktop: bool      # OnlyShowIn / NotShowIn against XDG_CURRENT_DESKTOP
    category: str = ""
    tokens: tuple[str, ...] = field(default_factory=tuple)
    description: str = ""
    kind: str = "App"           # "Desktop" (part of the session), "System" or "App"

    @property
    def source(self) -> str:
        return "User" if self.path == self.user_path else "System"

    @property
    def essential(self) -> bool:
        return self.kind == "Desktop"

    @property
    def is_override(self) -> bool:
        return self.user_path is not None and self.system_path is not None


def config_dirs() -> tuple[Path, list[Path]]:
    home = Path(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"))
    dirs = os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg"
    return home / "autostart", [Path(d) / "autostart" for d in dirs.split(":") if d]


def current_desktops(env: dict[str, str] | None = None) -> set[str]:
    env = os.environ if env is None else env
    raw = env.get("XDG_CURRENT_DESKTOP", "")
    return {d.strip() for d in raw.split(":") if d.strip()}


def applies_to(entry: dict[str, str], desktops: set[str]) -> bool:
    only = {d for d in entry.get("OnlyShowIn", "").split(";") if d}
    not_in = {d for d in entry.get("NotShowIn", "").split(";") if d}
    if only and not (only & desktops):
        return False
    return not (not_in & desktops)


def _truthy(value: str) -> bool:
    return value.strip().lower() == "true"


def classify(entry: dict[str, str], from_system: bool, tokens: tuple[str, ...]) -> str:
    """"Desktop" for pieces of the session itself, "System" for other entries the
    system installed, "App" for the user's own. Desktop entries are what a
    beginner must not switch off: no panels, no shortcuts, no password prompts."""
    if tokens and tokens[0] in DESKTOP_PARTS:
        return "Desktop"
    if from_system and entry.get("OnlyShowIn", "").strip(";"):
        return "Desktop"   # shipped for one desktop environment: part of it
    return "System" if from_system else "App"


class Autostart:
    def __init__(self, user_dir: Path | None = None, system_dirs: list[Path] | None = None,
                 desktops: set[str] | None = None) -> None:
        u, s = config_dirs()
        self.user_dir = user_dir if user_dir is not None else u
        self.system_dirs = system_dirs if system_dirs is not None else s
        self.desktops = desktops if desktops is not None else current_desktops()

    # -- reading -------------------------------------------------------------
    def entries(self) -> list[StartupEntry]:
        files: dict[str, tuple[Path | None, Path | None]] = {}  # id -> (user, system)
        for d in self.system_dirs:
            for f in sorted(d.glob("*.desktop")) if d.is_dir() else []:
                if f.name not in files:
                    files[f.name] = (None, f)
        if self.user_dir.is_dir():
            for f in sorted(self.user_dir.glob("*.desktop")):
                files[f.name] = (f, files.get(f.name, (None, None))[1])

        out: list[StartupEntry] = []
        for name, (user, system) in sorted(files.items()):
            path = user or system
            assert path is not None
            try:
                entry = parse_desktop_entry(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if entry.get("Type", "Application") != "Application":
                continue
            # A bare override only carries Hidden=true; take the rest from the system file.
            if user is not None and system is not None and "Exec" not in entry:
                try:
                    base = parse_desktop_entry(system.read_text(encoding="utf-8",
                                                                errors="replace"))
                    base.update(entry)
                    entry = base
                except OSError:
                    pass
            tokens = exec_tokens(entry.get("Exec", ""))
            out.append(StartupEntry(
                id=name,
                name=entry.get("Name", "") or name.removesuffix(".desktop"),
                icon=entry.get("Icon", ""),
                exec=entry.get("Exec", ""),
                path=path,
                system_path=system,
                user_path=user,
                enabled=not _truthy(entry.get("Hidden", "")),
                for_this_desktop=applies_to(entry, self.desktops),
                category=coarse_category(entry.get("Categories", "")),
                tokens=tokens,
                description=(entry.get("Comment", "") or (describe(tokens[0]) if tokens else "")
                             or entry.get("GenericName", "")),
                kind=classify(entry, system is not None, tokens),
            ))
        return out

    # -- writing (only inside the user's directory) ----------------------------
    def set_enabled(self, entry: StartupEntry, enabled: bool) -> None:
        self.user_dir.mkdir(parents=True, exist_ok=True)
        user = self.user_dir / entry.id
        if enabled:
            if entry.system_path is not None and user.is_file() and self._is_our_override(user):
                user.unlink()          # the system entry is what remains: enabled again
                return
            if user.is_file():
                self._set_hidden(user, False)
            return
        # disabling
        if user.is_file():
            self._set_hidden(user, True)
            return
        # system entry: write the smallest override that disables it
        user.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={entry.name}\n"
            f"Exec={entry.exec}\n"
            "Hidden=true\n"
            f"{OVERRIDE_MARK}=true\n",
            encoding="utf-8",
        )

    @staticmethod
    def _is_our_override(path: Path) -> bool:
        try:
            entry = parse_desktop_entry(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            return False
        return _truthy(entry.get(OVERRIDE_MARK, ""))

    @staticmethod
    def _set_hidden(path: Path, hidden: bool) -> None:
        """Rewrite only the Hidden= line of the [Desktop Entry] group; keep the rest as is."""
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        out: list[str] = []
        in_group = False
        done = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("["):
                if in_group and not done:
                    out.append(f"Hidden={'true' if hidden else 'false'}")
                    done = True
                in_group = stripped == "[Desktop Entry]"
            elif in_group and stripped.startswith("Hidden="):
                out.append(f"Hidden={'true' if hidden else 'false'}")
                done = True
                continue
            out.append(line)
        if not done:
            out.append(f"Hidden={'true' if hidden else 'false'}")
        path.write_text("\n".join(out) + "\n", encoding="utf-8")


# -- "is it running?" ---------------------------------------------------------
def running_pids(entries: list[StartupEntry], argvs: dict[int, list[str]]) -> dict[str, int]:
    """entry id -> a pid whose command line starts with the entry's Exec tokens."""
    from .appinfo import _basename  # same normalisation the process list uses
    out: dict[str, int] = {}
    for pid, argv in argvs.items():
        if not argv:
            continue
        base = [_basename(a) for a in argv]
        for e in entries:
            if e.id in out or not e.tokens:
                continue
            n = len(e.tokens)
            if tuple(base[:n]) == e.tokens:
                out[e.id] = pid
    return out
