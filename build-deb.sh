#!/bin/bash
# Build a .deb that other people can install with:  sudo apt install ./file.deb
#
#   ./build-deb.sh            builds backatit_<version>_all.deb here
#   VERSION=1.1 ./build-deb.sh
#
# Needs dpkg-deb and fakeroot:  sudo apt install dpkg-dev fakeroot
set -eu

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$SRC/about.conf" ] && . "$SRC/about.conf"
VERSION=${VERSION:-${APP_VERSION:-1.0}}
MAINTAINER="${APP_AUTHOR:-BackAtIt} <${APP_EMAIL:-nobody@localhost}>"
PKG=backatit
ARCH=all                       # shell and python: nothing compiled, so any machine
STAGE=$(mktemp -d)
chmod 0755 "$STAGE"            # mktemp makes it 0700, which would ship as the mode of /
trap 'rm -rf "$STAGE"' EXIT

APP_FILES="alarm.sh alarmd.sh alertctl.sh lib.sh alert.py settings.py demo-stats.sh about.conf"

LIBDIR="$STAGE/usr/lib/$PKG"
install -d "$LIBDIR" "$STAGE/usr/bin" "$STAGE/usr/share/applications" \
           "$STAGE/usr/share/doc/$PKG" "$STAGE/usr/share/metainfo" \
           "$STAGE/DEBIAN"

for f in $APP_FILES; do install -m 0755 "$SRC/$f" "$LIBDIR/$f"; done
chmod 0644 "$LIBDIR/about.conf"
install -m 0644 "$SRC/instruction.txt" "$STAGE/usr/share/doc/$PKG/instruction.txt"
[ -f "$SRC/LICENSE" ] && install -m 0644 "$SRC/LICENSE" "$STAGE/usr/share/doc/$PKG/copyright"

# Every size make-icons.sh produced: a desktop picks the exact one it needs.
ICON_NAME=alarm-clock
for s in 16 24 32 48 64 128 256; do
    src_icon="$SRC/icons/hicolor/${s}x${s}/apps/$PKG.png"
    if [ -f "$src_icon" ]; then
        install -d "$STAGE/usr/share/icons/hicolor/${s}x${s}/apps"
        install -m 0644 "$src_icon" "$STAGE/usr/share/icons/hicolor/${s}x${s}/apps/$PKG.png"
        ICON_NAME=$PKG
    fi
done
if [ -f "$SRC/icons/$PKG.svg" ]; then
    install -d "$STAGE/usr/share/icons/hicolor/scalable/apps"
    install -m 0644 "$SRC/icons/$PKG.svg" "$STAGE/usr/share/icons/hicolor/scalable/apps/$PKG.svg"
    ICON_NAME=$PKG
fi
[ -f "$SRC/$PKG.metainfo.xml" ] &&
    install -m 0644 "$SRC/$PKG.metainfo.xml" "$STAGE/usr/share/metainfo/$PKG.metainfo.xml"

cat > "$STAGE/usr/bin/$PKG" <<EOF
#!/bin/sh
exec /usr/lib/$PKG/alarm.sh "\$@"
EOF
chmod 0755 "$STAGE/usr/bin/$PKG"

cat > "$STAGE/usr/share/applications/$PKG.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=${APP_NAME:-BackAtIt}
GenericName=Break timer
Comment=Reminds you to get up and walk while you work
Exec=/usr/lib/$PKG/alarm.sh
Icon=$ICON_NAME
Terminal=false
# Ties a running window back to this entry, so the dock shows our icon.
StartupWMClass=backatit
Categories=Utility;Office;
Keywords=break;timer;health;posture;pomodoro;reminder;rsi;stretch;eyes;
StartupNotify=true
EOF
chmod 0644 "$STAGE/usr/share/applications/$PKG.desktop"

cat > "$STAGE/DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Depends: bash (>= 4.4), python3 (>= 3.6), python3-gi, gir1.2-gtk-3.0,
 libglib2.0-bin, procps, util-linux
Recommends: libnotify-bin, pipewire-bin | pulseaudio-utils | alsa-utils
Maintainer: $MAINTAINER
Installed-Size: $(du -sk "$STAGE" | cut -f1)
Description: Reminds you to get up and walk while you work
 A break timer that is hard to ignore. At the interval you choose it takes
 over the screen and sounds an alarm; once you have had your break a second
 alert calls you back to the desk and keeps nagging until you answer it.
 .
 The alert ignores the keyboard entirely, so carrying on typing cannot
 dismiss it by accident, and it can run on a daily schedule with your own
 days off. It keeps a tally of the breaks you actually took.
EOF

cat > "$STAGE/DEBIAN/prerm" <<EOF
#!/bin/sh
set -e
if [ -r /usr/lib/$PKG/lib.sh ]; then
    for home in /home/*; do
        [ -d "\$home" ] || continue
        user=\$(basename "\$home")
        id "\$user" >/dev/null 2>&1 || continue
        su - "\$user" -c ". /usr/lib/$PKG/lib.sh 2>/dev/null; stop_daemon" >/dev/null 2>&1 || true
    done
fi
exit 0
EOF
chmod 0755 "$STAGE/DEBIAN/prerm"

cat > "$STAGE/DEBIAN/postinst" <<EOF
#!/bin/sh
set -e
if [ "\$1" = configure ]; then
    command -v update-desktop-database >/dev/null 2>&1 &&
        update-desktop-database -q /usr/share/applications || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 &&
        gtk-update-icon-cache -qtf /usr/share/icons/hicolor || true
fi
exit 0
EOF
chmod 0755 "$STAGE/DEBIAN/postinst"

OUT="$SRC/${PKG}_${VERSION}_${ARCH}.deb"
fakeroot dpkg-deb --build "$STAGE" "$OUT" >/dev/null
echo "Built $OUT"
echo "Maintainer: $MAINTAINER"
echo
if [ "$VERSION" != "1.0" ]; then
    echo "Note: the wget line in README.md still names backatit_1.0_all.deb."
    echo "      Update it, or attach this file to the release under that name."
    echo
fi
echo "Install it with:  sudo apt install $OUT"
echo "Remove it with:   sudo apt remove $PKG"
