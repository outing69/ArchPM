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

# Autostart entries that are not one of the pieces above, by desktop-file
# name -> what you lose at the next login when the entry is switched off.
# An entry whose program is a piece above (org.kde.plasmashell.desktop runs
# plasmashell) takes that piece's line instead; see autostart_loss().
AUTOSTART = {
    "baloo_file.desktop": "file search in the launcher and in Dolphin: the index stops "
                          "being updated",
    "gmenudbusmenuproxy.desktop": "the menus of GTK programs in the panel's global menu",
    "kaccess.desktop": "sticky keys, slow keys and the other accessibility features",
    "kglobalacceld.desktop": "every global shortcut: the Meta key, the media keys and your "
                             "own shortcuts",
    "org.kde.plasma-fallback-session-restore.desktop": "the programs of your previous "
                                                       "session reopening at login",
    "pam_kwallet_init.desktop": "the wallet opening with your login password; KWallet asks "
                                "for it itself instead",
    "polkit-kde-authentication-agent-1.desktop": "every password prompt for a root task, "
                                                 "including ArchPM's own",
    "powerdevil.desktop": "power management: screen dimming, sleep, the battery icon and the "
                          "brightness keys",
    "xdg-user-dirs.desktop": "the Desktop, Downloads and Documents folder names following a "
                             "change of language",
    "xembedsniproxy.desktop": "the tray icons of older programs",
    "at-spi-dbus-bus.desktop": "the accessibility bus that screen readers and magnifiers use",
    "gnome-keyring-pkcs11.desktop": "the certificates GNOME Keyring holds for programs that "
                                    "use it",
    "gnome-keyring-secrets.desktop": "the passwords GNOME Keyring holds for programs that use "
                                     "it",
    "limine-snapper-notify.desktop": "the notice when Limine takes a snapshot",
    "limine-restore-notify.desktop": "the notice after a Limine snapshot restore",
    "org.kde.kdeconnect.daemon.desktop": "KDE Connect: phone notifications, file sharing and "
                                         "remote control",
}


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


def autostart_loss(entry_id: str, program: str) -> str:
    """What you lose at the next login when this autostart entry is off:
    the piece's line when its program is one of SESSION, else the entry's
    own line from AUTOSTART, else "" (the caller says what it knows)."""
    loss = process_loss(program)
    if loss:
        return loss
    return AUTOSTART.get(entry_id, "")


def pieces() -> str:
    """The list in plain words, for hints and docs."""
    return ", ".join(SESSION)
