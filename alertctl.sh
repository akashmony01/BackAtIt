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
    break)
        if use_locked_cycle; then
            # Show the real locked window - the whole point is to see what it
            # does before it does it for real - but stand a token countdown in
            # for the actual break, so pressing Test out of curiosity does not
            # seal the screen for the full walk length. The safety timer comes
            # down to match, so a wedged demo cannot sit on the input lock for
            # two minutes either.
            WALK_SEC=10
            LOCK_RELEASE_MARGIN=20
            locked_break_cycle
        else
            break_alert
        fi
        ;;
    walk)  walk_alert ;;
    *) echo "usage: ${0##*/} break|walk" >&2; exit 64 ;;
esac
exit $?
