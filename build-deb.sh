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

# shellcheck source=stage.sh
. "$SRC/stage.sh"
stage_tree "$STAGE"
install -d "$STAGE/DEBIAN"

cat > "$STAGE/DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Depends: bash (>= 4.4), python3 (>= 3.6), python3-gi, gir1.2-gtk-3.0,
 libglib2.0-bin, procps, util-linux
Recommends: libnotify-bin, pipewire-bin | pulseaudio-utils | alsa-utils, libxss1
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

# stop_daemons_snippet (stage.sh) stops a daemon still running the old copy.
cat > "$STAGE/DEBIAN/prerm" <<EOF
#!/bin/sh
set -e
$(stop_daemons_snippet)
exit 0
EOF
chmod 0755 "$STAGE/DEBIAN/prerm"

# The same sweep runs again here, and that is not redundant. On an upgrade it
# is the OLD package's prerm that dpkg runs — so a release that fixes a broken
# prerm cannot fix the upgrade INTO itself, only the one after. Doing it in
# postinst as well means this version can clear a stale daemon left behind by
# any earlier one, and the files it will restart from are already in place.
cat > "$STAGE/DEBIAN/postinst" <<EOF
#!/bin/sh
set -e
if [ "\$1" = configure ]; then
$(stop_daemons_snippet)
    command -v update-desktop-database >/dev/null 2>&1 &&
        update-desktop-database -q /usr/share/applications || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 &&
        gtk-update-icon-cache -qtf /usr/share/icons/hicolor || true
fi
exit 0
EOF
chmod 0755 "$STAGE/DEBIAN/postinst"

OUTDIR=${OUTDIR:-$SRC}
OUT="$OUTDIR/${PKG}_${VERSION}_${ARCH}.deb"
fakeroot dpkg-deb --build "$STAGE" "$OUT" >/dev/null
echo "Built $OUT"
echo "Maintainer: $MAINTAINER"
echo
# Warn only if the README really does name a different file, rather than
# guessing from the version number and crying wolf on every release.
if [ -f "$SRC/README.md" ] && ! grep -q "${PKG}_${VERSION}_${ARCH}.deb" "$SRC/README.md"; then
    stale=$(grep -o "${PKG}_[0-9.]*_${ARCH}\.deb" "$SRC/README.md" | head -1)
    echo "Note: README.md still names ${stale:-an older file}, not ${PKG}_${VERSION}_${ARCH}.deb."
    echo "      Update the download line, or people will get a 404."
    echo
fi
echo "Install it with:  sudo apt install $OUT"
echo "Remove it with:   sudo apt remove $PKG"
