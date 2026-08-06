#!/bin/bash
# Fill the Stats tab with plausible made-up figures, so you can see what a full
# 7- and 30-day history looks like — and put your real ones back afterwards.
#
#   ./demo-stats.sh on      swap in 30 days of demo data (your real file is kept)
#   ./demo-stats.sh off     restore your real figures
#   ./demo-stats.sh status  say which is currently in place
#
# Your genuine history is never thrown away: "on" copies it aside first, and
# refuses to overwrite an existing copy so repeated "on" cannot lose it.

STATS_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/backatit"
STATS="$STATS_DIR/stats.tsv"
REAL="$STATS_DIR/stats.tsv.real"

mkdir -p "$STATS_DIR"

generate() {
    # Fixed seed, so the same demo history comes back every time.
    RANDOM=20260806
    local i d dow taken snoozed skipped n
    for i in $(seq 29 -1 0); do
        d=$(date -d "-$i days" +%F)
        dow=$(date -d "-$i days" +%u)
        if [ "$dow" -ge 6 ]; then
            # Weekends: mostly nothing, the odd bit of catching up.
            taken=$(( RANDOM % 4 )); snoozed=0; skipped=$(( RANDOM % 2 ))
        elif [ $(( RANDOM % 11 )) -eq 0 ]; then
            taken=0; snoozed=0; skipped=0          # a day away from the desk
        else
            taken=$(( 6 + RANDOM % 9 ))
            snoozed=$(( RANDOM % 4 ))
            skipped=$(( RANDOM % 3 ))
        fi
        for n in $(seq "$taken");   do printf '%s\ttaken\n%s\tback\n' "$d" "$d"; done
        for n in $(seq "$snoozed"); do printf '%s\tsnoozed\n' "$d"; done
        for n in $(seq "$skipped"); do printf '%s\tskipped\n' "$d"; done
    done
}

case "$1" in
    on)
        if [ -f "$REAL" ]; then
            echo "Demo data is already in place (your real figures are in $REAL)."
        else
            [ -f "$STATS" ] && cp "$STATS" "$REAL" || : > "$REAL"
            echo "Your real figures were copied to $REAL"
        fi
        generate > "$STATS"
        echo "Demo data written: 30 days, $(wc -l < "$STATS") events."
        echo "Run './demo-stats.sh off' to put your real figures back."
        ;;
    off)
        if [ -f "$REAL" ]; then
            mv "$REAL" "$STATS"
            echo "Your real figures are back ($(wc -l < "$STATS") events)."
        else
            echo "No demo data is in place; nothing to restore."
        fi
        ;;
    status)
        if [ -f "$REAL" ]; then
            echo "Showing DEMO data. Real figures are parked in $REAL"
        else
            echo "Showing your real figures."
        fi
        ;;
    *)
        echo "usage: ${0##*/} on|off|status" >&2
        exit 64
        ;;
esac
