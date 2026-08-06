#!/bin/bash
# Break reminder — this is what the desktop icon launches.
# It makes sure the background app is alive, then opens the settings window.

# shellcheck source=lib.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

if ! python3 -c 'import gi; gi.require_version("Gtk","3.0")' 2>/dev/null; then
    command -v zenity >/dev/null 2>&1 &&
        zenity --error --text="Python GTK bindings are missing.\n\nRun:  sudo apt install python3-gi gir1.2-gtk-3.0"
    echo "python3-gi with GTK 3 is required" >&2
    exit 1
fi

# The schedule can only fire if this is running, so start it before showing
# anything — the window then reports honestly whether it is up.
start_daemon || notify "BackAtIt" "Could not start the background app."

exec python3 "$APP_DIR/settings.py" "$@"
