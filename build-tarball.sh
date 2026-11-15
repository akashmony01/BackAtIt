#!/bin/bash
# Build the source tarball for every distribution without a package:
#
#   ./build-tarball.sh          builds backatit-<version>.tar.gz here
#   OUTDIR=dist ./build-tarball.sh
#
# It unpacks to backatit-<version>/ and installs with ./install.sh.
# Built from git, so only committed files go in and nothing stray rides along.
set -eu

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$SRC/about.conf" ] && . "$SRC/about.conf"
VERSION=${VERSION:-${APP_VERSION:-1.0}}
OUTDIR=${OUTDIR:-$SRC}
PKG=backatit

mkdir -p "$OUTDIR"
OUT="$(cd "$OUTDIR" && pwd)/$PKG-$VERSION.tar.gz"
git -C "$SRC" archive --format=tar.gz --prefix="$PKG-$VERSION/" -o "$OUT" HEAD
echo "Built $OUT"
echo
echo "Install it with:"
echo "  tar xzf $PKG-$VERSION.tar.gz && cd $PKG-$VERSION && ./install.sh"
