#!/bin/bash
# Build an .rpm for Fedora, openSUSE and their relatives:
#
#   ./build-rpm.sh              builds backatit-<version>-1.noarch.rpm here
#   VERSION=2.0 ./build-rpm.sh
#   OUTDIR=dist ./build-rpm.sh
#
# Needs rpmbuild:  sudo dnf install rpm-build   (or apt install rpm on Debian)
#
# The files are the same ones the .deb ships - both are laid out by stage.sh.
set -eu

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$SRC/about.conf" ] && . "$SRC/about.conf"
VERSION=${VERSION:-${APP_VERSION:-1.0}}
PACKAGER="${APP_AUTHOR:-BackAtIt} <${APP_EMAIL:-nobody@localhost}>"
PKG=backatit
RELEASE=1
OUTDIR=${OUTDIR:-$SRC}

command -v rpmbuild >/dev/null 2>&1 || {
    echo "rpmbuild not found. Install it with: sudo dnf install rpm-build" >&2
    exit 1
}

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
STAGE="$WORK/stage"
install -d "$STAGE" "$WORK/rpmbuild/SPECS" "$WORK/rpmbuild/RPMS"

# shellcheck source=stage.sh
. "$SRC/stage.sh"
stage_tree "$STAGE"

# rpm wants the file list spelt out; derive it from what was staged, so a file
# added to stage.sh cannot be forgotten here.
FILES=$(cd "$STAGE" && find . -type f -o -type l | sed 's|^\.||' | sort)
DIRS="/usr/lib/$PKG
/usr/share/doc/$PKG"

SPEC="$WORK/rpmbuild/SPECS/$PKG.spec"
{
cat <<EOF
Name:           $PKG
Version:        $VERSION
Release:        $RELEASE
Summary:        Reminds you to get up and walk while you work
License:        MIT
URL:            https://github.com/akashmony01/BackAtIt
BuildArch:      noarch
Packager:       $PACKAGER

# Shell and Python only: turn off rpm's own dependency guessing and say
# exactly what is needed. Package names differ between Fedora and openSUSE,
# so each one is either a file path (resolved by both) or an "or" of the two.
AutoReqProv:    no
Requires:       bash >= 4.4
Requires:       python3 >= 3.6
Requires:       python3-gobject
Requires:       (gtk3 or typelib-1_0-Gtk-3_0)
Requires:       /usr/bin/gdbus
Requires:       /usr/bin/pkill
Requires:       /usr/bin/setsid
Recommends:     /usr/bin/notify-send
Recommends:     (pipewire-utils or pipewire-tools or pulseaudio-utils or alsa-utils)

%description
A break timer that is hard to ignore. At the interval you choose it takes
over the screen and sounds an alarm; once you have had your break a second
alert calls you back to the desk and keeps nagging until you answer it.

The alert ignores the keyboard entirely, so carrying on typing cannot
dismiss it by accident, and it can run on a daily schedule with your own
days off. It keeps a tally of the breaks you actually took.

%install
cp -a "$STAGE/." "%{buildroot}/"

# Stop a daemon still running the old copy - see stage.sh. Run both before
# the old files go and after the new ones land, for the same reason the
# .deb does: an upgrade runs the OLD package's scriptlets.
%preun
$(stop_daemons_snippet)
exit 0

%post
$(stop_daemons_snippet)
command -v update-desktop-database >/dev/null 2>&1 &&
    update-desktop-database -q /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null 2>&1 &&
    gtk-update-icon-cache -qtf /usr/share/icons/hicolor || true
exit 0

%changelog
* $(LC_ALL=C date -u +'%a %b %d %Y') $PACKAGER - $VERSION-$RELEASE
- See CHANGELOG.md for what changed in this release.

%files
EOF
while IFS= read -r d; do echo "%dir $d"; done <<< "$DIRS"
while IFS= read -r f; do
    case "$f" in
        /usr/share/doc/*) echo "%doc $f" ;;
        *) echo "$f" ;;
    esac
done <<< "$FILES"
} > "$SPEC"

rpmbuild --quiet -bb \
    --define "_topdir $WORK/rpmbuild" \
    --define "_rpmdir $WORK/rpmbuild/RPMS" \
    "$SPEC"

mkdir -p "$OUTDIR"
OUT="$OUTDIR/$PKG-$VERSION-$RELEASE.noarch.rpm"
cp "$WORK/rpmbuild/RPMS/noarch/$PKG-$VERSION-$RELEASE.noarch.rpm" "$OUT"
echo "Built $OUT"
echo
echo "Install it with:  sudo dnf install $OUT      (openSUSE: sudo zypper install $OUT)"
echo "Remove it with:   sudo dnf remove $PKG"
