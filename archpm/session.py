"""What your desktop session runs on, and what ending each piece costs you.

One list for two guards. The signal guard (signalguard.py) matches process
names against it, the service guard (actions.py) matches systemd unit names.
Each used to carry its own list and they drifted: kwin was in one and not the
other, ksmserver and the session bus in neither. This is the one place now;
a piece added here is known to both.

No Qt, no psutil: every rule is testable.
"""
from __future__ import annotations

# key -> what you lose. A key matches the name itself and its variants with a
# "-" or "_" after it: kwin_wayland, kwin_x11, pipewire-pulse,
# xdg-desktop-portal-kde, dbus-broker.
SESSION = {
    "plasmashell": "the panel, the desktop and its widgets",
    "kwin": "the window borders and window switching, and on Wayland the whole screen",
    "ksmserver": "the session manager: logout, and the programs restored at login",
    "dbus": "the session bus every desktop program talks over, and with it the session",
    "pipewire": "all sound",
    "wireplumber": "all sound",
    "xdg-desktop-portal": "file dialogs and screen sharing for sandboxed apps",
}
UNIT_SUFFIXES = (".service", ".socket", ".timer", ".path")


def _matches(base: str, key: str) -> bool:
    return base == key or base.startswith(key + "-") or base.startswith(key + "_")


def process_loss(name: str) -> str:
    """What you lose when a process with this name ends; "" if nothing special.

    /proc truncates names to 15 characters, so "xdg-desktop-por" matches too.
    """
    for key, loss in SESSION.items():
        if _matches(name, key):
            return loss
        if len(name) == 15 and key.startswith(name):
            return loss
    return ""


def unit_loss(unit: str) -> str:
    """What you lose when this user unit stops; "" if nothing special.

    Plasma prefixes its units (plasma-kwin_wayland.service); that prefix is
    dropped before matching. A dbus-activated program's unit
    (dbus-:1.2-org.kde.kwalletd6@0.service) is that program, not the bus.
    """
    base = unit
    for suffix in UNIT_SUFFIXES:
        if base.endswith(suffix):
            base = base[:-len(suffix)]
            break
    if base.startswith("dbus-:"):
        return ""
    base = base.removeprefix("plasma-")
    for key, loss in SESSION.items():
        if _matches(base, key):
            return loss
    return ""


def pieces() -> str:
    """The list in plain words, for hints and docs."""
    return ", ".join(SESSION)
