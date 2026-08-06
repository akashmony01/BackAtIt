#!/bin/bash
# Remove every trace of BackAtIt from this machine.
#
#   ./purge.sh --dry-run            list what would go, change nothing
#   ./purge.sh                      remove the app, your settings and statistics
#   ./purge.sh --including-source   ...and the ~/backatit working copy as well
#
# --including-source saves the built .deb to your home directory first, so you
# can still reinstall afterwards. Without it the working copy is left alone.
set -u

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRY=0
SOURCE_TOO=0
for arg in "$@"; do
    case "$arg" in
        --dry-run)          DRY=1 ;;
        --including-source) SOURCE_TOO=1 ;;
        -h|--help)          sed -n '2,9p' "$0" | sed 's/^# \?//'; exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 64 ;;
    esac
done

gone() { [ "$DRY" = 1 ] && echo "  would remove  $1" || { rm -rf "$1"; echo "  removed       $1"; }; }

echo "BackAtIt — complete removal"
[ "$DRY" = 1 ] && echo "(dry run: nothing will actually be deleted)"
echo

echo "Running processes:"
found=0
for pat in 'alarmd\.sh' 'settings\.py' 'alert\.py'; do
    for pid in $(pgrep -f "$pat" 2>/dev/null); do
        tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q 'backatit\|backatit' || continue
        found=1
        if [ "$DRY" = 1 ]; then echo "  would stop    pid $pid"
        else kill "$pid" 2>/dev/null && echo "  stopped       pid $pid"; fi
    done
done
[ "$found" = 0 ] && echo "  none"
[ "$DRY" = 0 ] && sleep 1

echo
echo "Installed package:"
if dpkg -l backatit break-reminder 2>/dev/null | grep -q '^ii'; then
    if [ "$DRY" = 1 ]; then echo "  would run     sudo apt-get purge -y backatit break-reminder"
    else
        echo "  running       sudo apt-get purge -y backatit break-reminder"
        sudo apt-get purge -y backatit break-reminder || {
            echo "  !! could not remove the package; run it yourself:" >&2
            echo "     sudo apt-get purge -y backatit break-reminder" >&2; }
    fi
else
    echo "  not installed"
fi

echo
echo "Home-directory install:"
any=0
for p in "$HOME/.local/lib/backatit" "$HOME/.local/bin/backatit" \
         "$HOME/.local/share/applications/backatit.desktop" \
         "$HOME/.local/share/icons/hicolor/scalable/apps/backatit.svg" \
         "$HOME/.local/share/metainfo/backatit.metainfo.xml"; do
    [ -e "$p" ] && { gone "$p"; any=1; }
done
[ "$any" = 0 ] && echo "  nothing there"

echo
echo "Launchers and autostart:"
any=0
for p in "$HOME/Desktop/RepeatAlarm.desktop" "$HOME/Desktop/backatit.desktop" \
         "$HOME/.config/autostart/backatit.desktop" \
         "$HOME/.config/autostart/break-reminder.desktop"; do
    [ -e "$p" ] && { gone "$p"; any=1; }
done
[ "$any" = 0 ] && echo "  none"

echo
echo "Settings and statistics:"
any=0
for p in "$HOME/.config/backatit" "$HOME/.local/state/backatit" \
         "$HOME/.config/break-reminder" "$HOME/.local/state/break-reminder"; do
    [ -e "$p" ] && { gone "$p"; any=1; }
done
[ "$any" = 0 ] && echo "  none"

echo
echo "Runtime state:"
any=0
for p in "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/backatit" /tmp/alarm_pid /tmp/alarm_loop_pid; do
    [ -e "$p" ] && { gone "$p"; any=1; }
done
[ "$any" = 0 ] && echo "  none"

echo
echo "Working copy:"
if [ "$SOURCE_TOO" = 1 ]; then
    deb=$(ls -1t "$SRC"/backatit_*_all.deb 2>/dev/null | head -1)
    if [ -n "$deb" ]; then
        if [ "$DRY" = 1 ]; then echo "  would keep    $HOME/$(basename "$deb")  (so you can reinstall)"
        else cp "$deb" "$HOME/" && echo "  kept          $HOME/$(basename "$deb")"; fi
    else
        echo "  !! no .deb found to keep — you will not be able to reinstall" >&2
    fi
    gone "$SRC"
else
    echo "  left alone    $SRC   (use --including-source to remove it too)"
fi

echo
[ "$DRY" = 1 ] && echo "Nothing was changed. Run without --dry-run to do it." \
               || echo "Done. BackAtIt is gone from this machine."
