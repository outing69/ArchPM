#!/usr/bin/env bash
# Install ArchPM.
#
#   ./install.sh            user part: agent, widget, menu entry
#   ./install.sh --root     root part: the pkexec helper and the polkit policy
#   ./install.sh --all      both
#   ./install.sh --uninstall-root   remove the root part
#   ./install.sh --uninstall        remove everything install.sh put on the machine
#
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
ROOT="$PWD"

HELPER_DST=/usr/local/lib/archpm/archpm-helper
POLICY_DST=/usr/share/polkit-1/actions/io.github.outing69.archpm.policy
# The package (PKGBUILD) puts the helper here and the policy at POLICY_DST.
# When this file exists the root part is the package's, and install.sh
# neither installs over it nor removes it.
PKG_HELPER=/usr/lib/archpm/archpm-helper
UNIT_DST=~/.config/systemd/user/archpm-agent.service
MENU_DST=~/.local/share/applications/archpm.desktop

# The rendered policy and the rendered widgets go through temporary files
# that are removed when the script ends, whichever way it ends.
POLICY_TMP=""
WIDGET_TMP=""
cleanup() {
    [ -z "$POLICY_TMP" ] || rm -f "$POLICY_TMP"
    [ -z "$WIDGET_TMP" ] || rm -rf "$WIDGET_TMP"
}
trap cleanup EXIT

# The widgets start ArchPM by this command, fixed here and rendered into the
# QML; they run nothing that comes out of status.json. The checkout path ends
# up inside a shell command line and inside a QML string, so it may not carry
# characters that mean something to either.
case "$ROOT" in
    *[!A-Za-z0-9/._+@-]*)
        echo "install.sh: the checkout path may only contain letters, digits and / . _ + @ -"
        echo "            ($ROOT)"
        exit 1 ;;
esac
LAUNCH="/usr/bin/python3 $ROOT/main.py"

have_plasma() { command -v kpackagetool6 >/dev/null 2>&1; }

desktop_dir() {
    local desk
    desk="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
    [ -d "${desk:-}" ] || desk="$HOME/Desktop"
    echo "$desk"
}

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
    mkdir -p "$(dirname "$UNIT_DST")"
    sed "s|@ROOT@|$ROOT|g" systemd/archpm-agent.service > "$UNIT_DST"
    systemctl --user daemon-reload
    systemctl --user enable --now archpm-agent.service

    echo "→ Plasma widgets"
    # Other desktops get the GUI but not the widgets: no kpackagetool6 means
    # no Plasma 6, so the widgets are skipped and the rest goes on.
    if ! have_plasma; then
        echo "   kpackagetool6 not found: no Plasma 6 here, widgets skipped"
    else
        WIDGET_TMP="$(mktemp -d)"
        local pkg
        for pkg in plasmoid/package plasmoid/network; do
            local id rendered
            id=$(sed -n 's/.*"Id": "\(.*\)".*/\1/p' "$pkg/metadata.json")
            rendered="$WIDGET_TMP/$(basename "$pkg")"
            cp -r "$pkg" "$rendered"
            sed -i "s|@LAUNCH@|$LAUNCH|" "$rendered/contents/ui/main.qml"
            if kpackagetool6 -t Plasma/Applet -l 2>/dev/null | grep -qx "$id"; then
                kpackagetool6 -t Plasma/Applet -u "$rendered"
            else
                kpackagetool6 -t Plasma/Applet -i "$rendered"
            fi
        done
    fi

    echo "→ menu entry"
    mkdir -p "$(dirname "$MENU_DST")"
    sed "s|@ROOT@|$ROOT|g" archpm.desktop > "$MENU_DST"
    update-desktop-database "$(dirname "$MENU_DST")" 2>/dev/null || true
    # Plasma's task manager and tooltips match the window's app id ("archpm")
    # against its own service cache; without a rebuild it shows "python3".
    kbuildsycoca6 --noincremental >/dev/null 2>&1 || true

    echo "→ desktop shortcut"
    local desk
    desk="$(desktop_dir)"
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
    if [ -f "$PKG_HELPER" ]; then
        echo "ArchPM is installed as a package ($PKG_HELPER exists);"
        echo "the root part comes from the package, not from install.sh. Nothing to do."
        return
    fi
    echo "→ root helper and polkit policy (asks for your password)"
    # pkexec refuses a program that is not root-owned or that others can
    # write to -- hence the copy to /usr/local/lib.
    sudo install -Dm755 -o root -g root archpm/root/helper.py "$HELPER_DST"
    POLICY_TMP="$(mktemp)"
    sed "s|@HELPER@|$HELPER_DST|" polkit/io.github.outing69.archpm.policy > "$POLICY_TMP"
    sudo install -Dm644 -o root -g root "$POLICY_TMP" "$POLICY_DST"
    echo "   $HELPER_DST"
    echo "   $POLICY_DST"
    echo -n "→ check: "
    "$HELPER_DST" status >/dev/null && echo "helper responds"
}

uninstall_root() {
    if [ -f "$PKG_HELPER" ]; then
        # The policy at POLICY_DST is the package's (pacman would not have
        # installed over one of ours), so it stays; only a helper left in
        # /usr/local by an earlier install.sh --root is ours to remove.
        echo "ArchPM is installed as a package ($PKG_HELPER exists);"
        echo "the root part is the package's and stays. Remove it with pacman -R archpm."
        if [ -e "$HELPER_DST" ]; then
            echo "→ a helper left behind by an earlier install.sh --root (asks for your password)"
            sudo rm -f "$HELPER_DST"
            sudo rmdir --ignore-fail-on-non-empty /usr/local/lib/archpm 2>/dev/null || true
            echo "   $HELPER_DST removed"
        fi
        return
    fi
    if [ ! -e "$HELPER_DST" ] && [ ! -e "$POLICY_DST" ]; then
        echo "root part: not installed, nothing to remove"
        return
    fi
    echo "→ root helper and polkit policy (asks for your password)"
    sudo rm -f "$HELPER_DST" "$POLICY_DST"
    sudo rmdir --ignore-fail-on-non-empty /usr/local/lib/archpm 2>/dev/null || true
    echo "   root part removed"
}

uninstall_user() {
    echo "→ systemd --user service"
    if [ -e "$UNIT_DST" ]; then
        systemctl --user disable --now archpm-agent.service 2>/dev/null || true
        rm -f "$UNIT_DST"
        systemctl --user daemon-reload 2>/dev/null || true
        echo "   removed"
    else
        echo "   not installed"
    fi

    echo "→ Plasma widgets"
    if ! have_plasma; then
        echo "   kpackagetool6 not found: no Plasma 6 here, nothing to remove"
    else
        local pkg id
        for pkg in plasmoid/package plasmoid/network; do
            id=$(sed -n 's/.*"Id": "\(.*\)".*/\1/p' "$pkg/metadata.json")
            if kpackagetool6 -t Plasma/Applet -l 2>/dev/null | grep -qx "$id"; then
                kpackagetool6 -t Plasma/Applet -r "$id"
            else
                echo "   $id: not installed"
            fi
        done
    fi

    echo "→ menu entry and desktop shortcut"
    rm -f "$MENU_DST" "$(desktop_dir)/archpm.desktop"
    update-desktop-database "$(dirname "$MENU_DST")" 2>/dev/null || true
    kbuildsycoca6 --noincremental >/dev/null 2>&1 || true
    echo "   removed"
    echo "Your settings (~/.config/archpm) and the cache (~/.cache/archpm) are kept."
}

case "${1:-}" in
    --root)            install_root ;;
    --uninstall-root)  uninstall_root; exit 0 ;;
    --uninstall)       uninstall_user; uninstall_root; exit 0 ;;
    --all)             install_user; install_root ;;
    "")                install_user ;;
    *) echo "unknown option: $1"; exit 2 ;;
esac

cat <<MSG

Done.
  Start the GUI:    python3 -m archpm      (or from the menu: ArchPM)
  Agent status:     systemctl --user status archpm-agent
$(have_plasma && echo "  Place the widget: right-click your desktop → Add Widgets → 'ArchPM Monitor'" \
              || echo "  Widgets:          not installed, this desktop is not Plasma 6")
  Root tasks:       Overview → 'Root tasks' button
MSG
