#!/bin/bash
# Generate the icon sizes a desktop asks for, from logo.png.
#
#   ./make-icons.sh            regenerate icons/ from logo.png
#   ./make-icons.sh other.png  ...from a different file
#
# Run this whenever you change the logo, then rebuild or reinstall.
# A desktop does not scale one big image for you: it looks for the exact size
# it wants under hicolor/<size>x<size>/apps, and falls back badly if missing.
set -eu

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGO=${1:-$SRC/logo.png}
NAME=backatit
SIZES="16 24 32 48 64 128 256"

[ -f "$LOGO" ] || { echo "no such file: $LOGO" >&2; exit 1; }

python3 - "$LOGO" "$SRC/icons" "$NAME" "$SIZES" <<'PY'
import os, sys
import gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf

logo, outdir, name, sizes = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4].split()
master = GdkPixbuf.Pixbuf.new_from_file(logo)
w, h = master.get_width(), master.get_height()
if w != h:
    print(f"  warning: {w}x{h} is not square; it will be squashed", file=sys.stderr)

for s in sizes:
    s = int(s)
    d = os.path.join(outdir, "hicolor", f"{s}x{s}", "apps")
    os.makedirs(d, exist_ok=True)
    # HYPER is slow but gives the cleanest downscale, which is what matters
    # at 16 and 24 pixels where the detail has to survive.
    scaled = master.scale_simple(s, s, GdkPixbuf.InterpType.HYPER)
    path = os.path.join(d, f"{name}.png")
    scaled.savev(path, "png", [], [])
    print(f"  {s:3d}x{s:<3d} -> {os.path.relpath(path, os.path.dirname(outdir))}")
PY

echo "Done. Now run ./install.sh  or  ./build-deb.sh"
