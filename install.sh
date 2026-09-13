#!/usr/bin/env bash
# Install Glorified PM.
#
#   ./install.sh            user part: agent, widget, menu entry
#   ./install.sh --root     root part: the pkexec helper and the polkit policy
#   ./install.sh --all      both
#   ./install.sh --uninstall-root
#
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
ROOT="$PWD"

HELPER_DST=/usr/local/lib/gpm/gpm-helper
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
    sed "s|@ROOT@|$ROOT|g" systemd/gpm-agent.service \
        > ~/.config/systemd/user/gpm-agent.service
    systemctl --user daemon-reload
    systemctl --user enable --now gpm-agent.service

    echo "→ Plasma widget"
    if kpackagetool6 -t Plasma/Applet -l 2>/dev/null | grep -q io.github.outing69.archpm; then
        kpackagetool6 -t Plasma/Applet -u plasmoid/package
    else
        kpackagetool6 -t Plasma/Applet -i plasmoid/package
    fi

    echo "→ menu entry"
    mkdir -p ~/.local/share/applications
    sed "s|@ROOT@|$ROOT|g" gpm.desktop > ~/.local/share/applications/gpm.desktop
    update-desktop-database ~/.local/share/applications 2>/dev/null || true

    echo "→ desktop shortcut"
    local desk
    desk="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
    [ -d "${desk:-}" ] || desk="$HOME/Desktop"
    if [ -d "$desk" ]; then
        sed "s|@ROOT@|$ROOT|g" gpm.desktop > "$desk/gpm.desktop"
        # Plasma only launches a .desktop file on the desktop without the
        # "untrusted" warning if it is executable.
        chmod +x "$desk/gpm.desktop"
        echo "   $desk/gpm.desktop"
    else
        echo "   no desktop directory found — skipped"
    fi
}

install_root() {
    echo "→ root helper and polkit policy (asks for your password)"
    # pkexec refuses a program that is not root-owned or that others can
    # write to -- hence the copy to /usr/local/lib.
    sudo install -Dm755 -o root -g root gpm/root/helper.py "$HELPER_DST"
    sudo install -Dm644 -o root -g root polkit/io.github.outing69.archpm.policy "$POLICY_DST"
    echo "   $HELPER_DST"
    echo "   $POLICY_DST"
    echo -n "→ check: "
    "$HELPER_DST" status >/dev/null && echo "helper responds"
}

uninstall_root() {
    sudo rm -f "$HELPER_DST" "$POLICY_DST"
    sudo rmdir --ignore-fail-on-non-empty /usr/local/lib/gpm 2>/dev/null || true
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
  Start the GUI:    python3 -m gpm      (or from the menu: Glorified PM)
  Agent status:     systemctl --user status gpm-agent
  Place the widget: right-click your desktop → Add Widgets → 'Glorified PM Monitor'
  Root tasks:       Overview → 'Root tasks' button
MSG
