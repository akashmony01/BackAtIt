#!/bin/bash
# Background daemon for the break reminder.
#
# It runs all the time (started at login) and decides on its own whether the
# reminder should currently be firing:
#   - you switched it on by hand in the app window, OR
#   - the daily schedule is enabled and the clock is inside the window.
# So a scheduled window works whether or not you ever opened the app today.
#
# A full cycle is two stages:
#   1. "Take a break!"     -> you get up
#   2. "Walk time is up"   -> you come back, and it nags until you say so
# Stage 2 is optional (WALK_ENABLED).

# shellcheck source=lib.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

TICK=5              # how often we re-check the clock and the settings

# Only one daemon, ever.
claim_daemon_slot || exit 0

log() { printf '%s %s\n' "$(date '+%F %T')" "$*" >> "$LOG"; }

cleanup() {
    rm -f "$DAEMON_PID"
    clear_next
    exit 0
}
trap cleanup TERM INT HUP

# Publish what we are counting down to, so the settings window can show a live
# ticking counter and you can tell at a glance that the app is really running.
write_next() {
    # Minutes are too coarse to be useful for a sub-two-minute interval.
    local fmt='+%H:%M'
    [ "$1" -lt 120 ] && fmt='+%H:%M:%S'
    date -d "+$1 seconds" "$fmt" > "$NEXT_FILE" 2>/dev/null
    date -d "+$1 seconds" '+%s'  > "$NEXT_EPOCH" 2>/dev/null
    echo "${2:-work}" > "$PHASE_FILE"
}

clear_next() { rm -f "$NEXT_FILE" "$NEXT_EPOCH" "$PHASE_FILE"; }

# While an alert is on screen there is nothing to count down to.
set_phase() { echo "$1" > "$PHASE_FILE"; rm -f "$NEXT_EPOCH"; }

# "Turn off reminders" was clicked: stop nagging without destroying the setup.
# The manual switch goes off, and a schedule is muted for the rest of today
# only — so tomorrow works as configured, and saving in the app resumes now.
turn_off() {
    rm -f "$MANUAL_FLAG"
    if [ "$SCHEDULE_ENABLED" = "1" ]; then
        pause_today
        notify "Reminders off for today" "The schedule resumes tomorrow, or open the app to start again."
    else
        notify "Reminders turned off" "Open the app when you want them back."
    fi
    record_stat turned_off
    log "turned off by the user"
}

# Stage 2: wait out the walk, then nag until they say they are back.
walk_stage() {
    local left=$WALK_SEC step
    log "walk started ($(human_dur "$WALK_SEC"))"
    write_next "$left" walk
    while [ "$left" -gt 0 ]; do
        step=$TICK
        [ "$left" -lt "$TICK" ] && step=$left
        sleep "$step"
        left=$((left - step))
        # Bail out if the schedule window closed or they turned it off elsewhere.
        load_config
        is_active || { log "walk abandoned, reminder no longer active"; return 1; }
    done

    log "walk over, nagging to come back"
    set_phase alert
    walk_alert
    local rc=$?
    if [ "$rc" = "20" ]; then
        turn_off
        return 1
    fi
    record_stat back
    log "back at work"
    return 0
}

# ---------------- main loop ----------------

log "daemon started (pid $BASHPID)"
# A predecessor that was killed rather than stopped may have left published
# state behind. Nothing is due yet, so start from a clean slate.
clear_next
remaining=-1        # -1 means "not counting down"
warned=0

while :; do
    load_config

    if ! is_active; then
        # Clear whenever anything is still published, not only on the tick we
        # went inactive. An abandoned walk already sets remaining to -1 before
        # looping, so a guard on remaining alone left the phase and countdown
        # files behind for good — and the settings window then believed a
        # reminder was still running, showed a stale counter, and turned every
        # press of the button into a Stop.
        if [ "$remaining" -ge 0 ] || [ -f "$PHASE_FILE" ]; then
            log "reminder off"
            clear_next
        fi
        remaining=-1
        warned=0
        sleep "$TICK"
        continue
    fi

    # Just became active (manual switch, or the schedule window opened).
    if [ "$remaining" -lt 0 ]; then
        remaining=$INTERVAL_SEC
        warned=0
        write_next "$remaining"
        log "reminder on, next break in $(human_dur "$INTERVAL_SEC")"
        notify "Break reminder is ON" "Next break at $(cat "$NEXT_FILE" 2>/dev/null)"
    fi

    if [ "$remaining" -le 0 ]; then
        # No point alarming an empty room — if they are already away from the
        # keyboard they are already having their break.
        if user_is_away; then
            log "already away ($(human_dur "$(idle_sec)") idle), skipping this break"
            record_stat skipped
            remaining=$INTERVAL_SEC
            warned=0
            write_next "$remaining"
            continue
        fi

        log "firing break alert"
        set_phase alert
        break_alert
        case $? in
            10)
                record_stat snoozed
                remaining=$SNOOZE_SEC
                log "snoozed $(human_dur "$SNOOZE_SEC")"
                ;;
            20)
                turn_off
                remaining=-1
                ;;
            *)
                record_stat taken
                if [ "$WALK_ENABLED" = "1" ]; then
                    walk_stage || { remaining=-1; continue; }
                fi
                remaining=$INTERVAL_SEC
                log "next break in $(human_dur "$INTERVAL_SEC")"
                ;;
        esac
        warned=0
        [ "$remaining" -gt 0 ] && write_next "$remaining"
    else
        # Heads-up so a break is never a surprise mid-thought.
        if [ "$WARN_ENABLED" = "1" ] && [ "$warned" = "0" ] &&
           [ "$remaining" -le "$WARN_LEAD_SEC" ]; then
            notify "Break coming up" "Break in about $(human_dur "$remaining")."
            warned=1
        fi
        # Never sleep past zero, or a 30-second interval would fire late.
        step=$TICK
        [ "$remaining" -lt "$TICK" ] && step=$remaining
        sleep "$step"
        remaining=$((remaining - step))
    fi
done
