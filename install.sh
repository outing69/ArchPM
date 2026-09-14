#!/usr/bin/env bash
# Install ArchPM.
#
#   ./install.sh            user part: agent, widget, menu entry
#   ./install.sh --root     root part: the pkexec helper and the polkit policy
#   ./install.sh --all      both
#   ./install.sh --uninstall-root
#
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
ROOT="$PWD"

HELPER_DST=/usr/local/lib/archpm/archpm-helper
POLICY_DST=/usr/share/polkit-1/actions/io.github.outing69.archpm.policy

install_user() {
    echo "→ checking dependencies"
    local missing=()
    python3 -c "import psutil"  2>/dev/null || missing+=(python-psutil)
    python3 -c "import PySide6" 2>/dev/null || missing+=(pyside6)
    if ((${#missing[@]})); then
        echo "   missing: ${missing[*]}"
        echo "   install with: sudo pacman -S --needed ${missing[*]}"
        exit 1
    fi

    echo "→ systemd --user service"
    mkdir -p ~/.config/systemd/user
    sed "s|@ROOT@|$ROOT|g" systemd/archpm-agent.service \
        > ~/.config/systemd/user/archpm-agent.service
    systemctl --user daemon-reload
    systemctl --user enable --now archpm-agent.service

    echo "→ Plasma widgets"
    local pkg
    for pkg in plasmoid/package plasmoid/network; do
        local id
        id=$(sed -n 's/.*"Id": "\(.*\)".*/\1/p' "$pkg/metadata.json")
        if kpackagetool6 -t Plasma/Applet -l 2>/dev/null | grep -qx "$id"; then
            kpackagetool6 -t Plasma/Applet -u "$pkg"
        else
            kpackagetool6 -t Plasma/Applet -i "$pkg"
        fi
    done

    echo "→ menu entry"
    mkdir -p ~/.local/share/applications
    sed "s|@ROOT@|$ROOT|g" archpm.desktop > ~/.local/share/applications/archpm.desktop
    update-desktop-database ~/.local/share/applications 2>/dev/null || true
    # Plasma's task manager and tooltips match the window's app id ("archpm")
    # against its own service cache; without a rebuild it shows "python3".
    kbuildsycoca6 --noincremental >/dev/null 2>&1 || true

    echo "→ desktop shortcut"
    local desk
    desk="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
    [ -d "${desk:-}" ] || desk="$HOME/Desktop"
    if [ -d "$desk" ]; then
        sed "s|@ROOT@|$ROOT|g" archpm.desktop > "$desk/archpm.desktop"
        # Plasma only launches a .desktop file on the desktop without the
        # "untrusted" warning if it is executable.
        chmod +x "$desk/archpm.desktop"
        echo "   $desk/archpm.desktop"
    else
        echo "   no desktop directory found, skipped"
    fi
}

install_root() {
    if [ -f /usr/lib/archpm/archpm-helper ]; then
        echo "ArchPM is installed as a package (/usr/lib/archpm/archpm-helper exists);"
        echo "the root part comes from the package, not from install.sh. Nothing to do."
        return
    fi
    echo "→ root helper and polkit policy (asks for your password)"
    # pkexec refuses a program that is not root-owned or that others can
    # write to -- hence the copy to /usr/local/lib.
    sudo install -Dm755 -o root -g root archpm/root/helper.py "$HELPER_DST"
    sed "s|@HELPER@|$HELPER_DST|" polkit/io.github.outing69.archpm.policy > "$ROOT/.policy.tmp"
    sudo install -Dm644 -o root -g root "$ROOT/.policy.tmp" "$POLICY_DST"
    rm -f "$ROOT/.policy.tmp"
    echo "   $HELPER_DST"
    echo "   $POLICY_DST"
    echo -n "→ check: "
    "$HELPER_DST" status >/dev/null && echo "helper responds"
}

uninstall_root() {
    sudo rm -f "$HELPER_DST" "$POLICY_DST"
    sudo rmdir --ignore-fail-on-non-empty /usr/local/lib/archpm 2>/dev/null || true
    echo "root part removed"
}

case "${1:-}" in
    --root)            install_root ;;
    --uninstall-root)  uninstall_root ;;
    --all)             install_user; install_root ;;
    "")                install_user ;;
    *) echo "unknown option: $1"; exit 2 ;;
esac

cat <<MSG

Done.
  Start the GUI:    python3 -m archpm      (or from the menu: ArchPM)
  Agent status:     systemctl --user status archpm-agent
  Place the widget: right-click your desktop → Add Widgets → 'ArchPM Monitor'
  Root tasks:       Overview → 'Root tasks' button
MSG
