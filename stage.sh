#!/bin/bash
# Lay out BackAtIt under a root directory exactly as a package installs it:
#
#   ROOT/usr/lib/backatit/...            the program
#   ROOT/usr/bin/backatit                launcher
#   ROOT/usr/share/applications/...      menu entry
#   ROOT/usr/share/icons/hicolor/...     icons
#   ROOT/usr/share/metainfo/...          software-centre listing
#   ROOT/usr/share/doc/backatit/...      user guide and licence
#
# Sourced by build-deb.sh and build-rpm.sh, so the two packages can never
# disagree about what is in them. Expects SRC and PKG to be set.

APP_FILES="alarm.sh alarmd.sh alertctl.sh lib.sh deps.sh alert.py idle.py settings.py demo-stats.sh about.conf"

stage_tree() {
    local root=$1 libdir="$1/usr/lib/$PKG" f s src_icon icon_name=alarm-clock
    install -d "$libdir" "$root/usr/bin" "$root/usr/share/applications" \
               "$root/usr/share/doc/$PKG" "$root/usr/share/metainfo"

    for f in $APP_FILES; do install -m 0755 "$SRC/$f" "$libdir/$f"; done
    chmod 0644 "$libdir/about.conf" "$libdir/deps.sh"
    install -m 0644 "$SRC/instruction.txt" "$root/usr/share/doc/$PKG/instruction.txt"
    [ -f "$SRC/LICENSE" ] && install -m 0644 "$SRC/LICENSE" "$root/usr/share/doc/$PKG/copyright"

    # Every size make-icons.sh produced: a desktop picks the exact one it needs.
    for s in 16 24 32 48 64 128 256; do
        src_icon="$SRC/icons/hicolor/${s}x${s}/apps/$PKG.png"
        if [ -f "$src_icon" ]; then
            install -d "$root/usr/share/icons/hicolor/${s}x${s}/apps"
            install -m 0644 "$src_icon" "$root/usr/share/icons/hicolor/${s}x${s}/apps/$PKG.png"
            icon_name=$PKG
        fi
    done
    if [ -f "$SRC/icons/$PKG.svg" ]; then
        install -d "$root/usr/share/icons/hicolor/scalable/apps"
        install -m 0644 "$SRC/icons/$PKG.svg" "$root/usr/share/icons/hicolor/scalable/apps/$PKG.svg"
        icon_name=$PKG
    fi
    [ -f "$SRC/$PKG.metainfo.xml" ] &&
        install -m 0644 "$SRC/$PKG.metainfo.xml" "$root/usr/share/metainfo/$PKG.metainfo.xml"

    cat > "$root/usr/bin/$PKG" <<EOF
#!/bin/sh
exec /usr/lib/$PKG/alarm.sh "\$@"
EOF
    chmod 0755 "$root/usr/bin/$PKG"

    cat > "$root/usr/share/applications/$PKG.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=${APP_NAME:-BackAtIt}
GenericName=Break timer
Comment=Reminds you to get up and walk while you work
Exec=/usr/lib/$PKG/alarm.sh
Icon=$icon_name
Terminal=false
# Ties a running window back to this entry, so the dock shows our icon.
StartupWMClass=backatit
Categories=Utility;
Keywords=break;timer;health;posture;pomodoro;reminder;rsi;stretch;eyes;
StartupNotify=true
EOF
    chmod 0644 "$root/usr/share/applications/$PKG.desktop"
}

# Stopping a running daemon is worth explaining, because getting it wrong is
# invisible: the upgrade succeeds, the new files land, and the user carries on
# being served by a daemon that read the OLD lib.sh into memory at startup and
# will keep running it until the process dies. Nothing looks broken; the new
# behaviour simply never appears.
#
# The trap is XDG_RUNTIME_DIR. lib.sh keeps its pid file under it, and `su`
# here builds a fresh environment without one (pam_systemd is not in su's
# stack), so lib.sh fell back to a /tmp path the real session never used,
# found no pid file, and returned happily having stopped nothing. So set it
# explicitly from the user's uid.
stop_daemons_snippet() {
    cat <<EOF
if [ -r /usr/lib/$PKG/lib.sh ]; then
    for home in /home/*; do
        [ -d "\$home" ] || continue
        user=\$(basename "\$home")
        uid=\$(id -u "\$user" 2>/dev/null) || continue
        [ -d "/run/user/\$uid" ] || continue
        su "\$user" -c "XDG_RUNTIME_DIR=/run/user/\$uid; export XDG_RUNTIME_DIR; . /usr/lib/$PKG/lib.sh 2>/dev/null; stop_daemon" >/dev/null 2>&1 || true
    done
fi
EOF
}
