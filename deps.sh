#!/bin/bash
# What BackAtIt needs, named the way each distribution's package manager names
# it. Sourced by install.sh (before anything is installed, possibly as root)
# and by alarm.sh, so it must not do anything on its own when sourced.

# The package manager this machine uses, or nothing if it is none we know.
pkg_manager() {
    local pm
    for pm in apt-get dnf zypper pacman; do
        command -v "$pm" >/dev/null 2>&1 && { echo "${pm%-get}"; return 0; }
    done
    return 1
}

# The install command for everything BackAtIt needs on a given manager.
deps_command() {
    case "$1" in
        apt)    echo "sudo apt install python3-gi gir1.2-gtk-3.0 libnotify-bin pipewire-bin" ;;
        dnf)    echo "sudo dnf install python3-gobject gtk3 libnotify pipewire-utils" ;;
        zypper) echo "sudo zypper install python3-gobject python3-gobject-Gdk typelib-1_0-Gtk-3_0 libnotify-tools pipewire-tools" ;;
        pacman) echo "sudo pacman -S python-gobject gtk3 libnotify pipewire" ;;
        *)      return 1 ;;
    esac
}

# Human-readable advice: this machine's command if we recognise it, otherwise
# the whole table so the reader can pick their own.
deps_hint() {
    local pm
    if pm=$(pkg_manager); then
        deps_command "$pm"
        return 0
    fi
    echo "On Debian, Ubuntu or Mint:  $(deps_command apt)"
    echo "On Fedora:                  $(deps_command dnf)"
    echo "On openSUSE:                $(deps_command zypper)"
    echo "On Arch or Manjaro:         $(deps_command pacman)"
}
