#!/bin/bash
# Show one alert on demand, using exactly the same settings the daemon uses.
# The settings window calls this for its "Test" buttons, so the test really is
# the same window you get for real — no second copy of the arguments to drift.
#
#   alertctl.sh break   -> the "Take a break!" alert
#   alertctl.sh walk    -> the "Walk time is up" alert

# shellcheck source=lib.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

load_config

case "$1" in
    break) break_alert ;;
    walk)  walk_alert ;;
    *) echo "usage: ${0##*/} break|walk" >&2; exit 64 ;;
esac
exit $?
