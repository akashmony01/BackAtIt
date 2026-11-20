#!/bin/bash
# Shared helpers for BackAtIt. Sourced by alarm.sh and alarmd.sh.

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Settings live in the standard per-user place, not beside the program.
# Sitting next to the program only works while the program is in your home
# directory; once it is installed to /usr or /opt that directory is shared
# between users and read-only, and nothing could be saved.
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/backatit"
CONFIG="$CONFIG_DIR/config"
mkdir -p "$CONFIG_DIR" 2>/dev/null

# Carry across settings from where earlier versions kept them, once each.
# The app was called break-reminder before, and kept its settings beside the
# program before that; neither should cost you your configuration.
if [ ! -f "$CONFIG" ]; then
    for old_cfg in "${XDG_CONFIG_HOME:-$HOME/.config}/break-reminder/config" \
                   "$APP_DIR/config"; do
        if [ -f "$old_cfg" ]; then
            cp "$old_cfg" "$CONFIG" 2>/dev/null && chmod 600 "$CONFIG" 2>/dev/null
            break
        fi
    done
fi

# Runtime state lives in XDG_RUNTIME_DIR so it is wiped on logout/reboot.
# That is what kills the old "stale PID file makes the app think it is running"
# bug: there is nothing left behind to go stale.
STATE_DIR="${XDG_RUNTIME_DIR:-/tmp/backatit-$UID}/backatit"
mkdir -p "$STATE_DIR"

MANUAL_FLAG="$STATE_DIR/manual_on"   # exists => user switched the reminder on by hand
PAUSE_FILE="$STATE_DIR/paused_on"    # holds a date => reminders are off for that day
DAEMON_PID="$STATE_DIR/daemon.pid"   # doubles as the single-instance lock
NEXT_FILE="$STATE_DIR/next_break"    # HH:MM of the upcoming break, for the UI
NEXT_EPOCH="$STATE_DIR/next_epoch"   # same moment as a unix timestamp, so the
                                     # settings window can tick a live countdown
PHASE_FILE="$STATE_DIR/phase"        # work | walk | alert — what we are counting to
LOG="$STATE_DIR/daemon.log"

# Stats must outlive the session, so they do not live in XDG_RUNTIME_DIR.
STATS_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/backatit"
STATS_FILE="$STATS_DIR/stats.tsv"

# Bring the history over from the break-reminder days rather than starting
# your tally again from zero.
if [ ! -f "$STATS_FILE" ]; then
    _old_stats="${XDG_STATE_HOME:-$HOME/.local/state}/break-reminder"
    if [ -d "$_old_stats" ]; then
        mkdir -p "$STATS_DIR" 2>/dev/null
        cp -a "$_old_stats/." "$STATS_DIR/" 2>/dev/null || true
    fi
    unset _old_stats
fi

AUTOSTART_FILE="$HOME/.config/autostart/backatit.desktop"

DEFAULT_SOUND="/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga"
DEFAULT_WALK_SOUND="/usr/share/sounds/freedesktop/stereo/complete.oga"

# Intervals are entered in minutes and may be fractional (0.5 = 30 seconds),
# so they need a little care: bash cannot do floating-point arithmetic, and a
# comma-decimal locale would hand us "0,5".
MIN_MINUTES=0.5
MAX_MINUTES=240

norm_num() { echo "${1//,/.}"; }

# valid_num VALUE LOW HIGH
valid_num() {
    [[ "$1" =~ ^[0-9]+(\.[0-9]+)?$ ]] || return 1
    awk -v v="$1" -v lo="$2" -v hi="$3" 'BEGIN { exit !(v >= lo && v <= hi) }'
}

# Decimal minutes -> whole seconds (never less than 1).
min_to_sec() {
    awk -v m="$1" 'BEGIN { s = int(m * 60 + 0.5); if (s < 1) s = 1; printf "%d", s }'
}

# 30 -> "30", 0.5 -> "0.5"  (for messages; avoids showing "30.0")
fmt_min() {
    awk -v m="$1" 'BEGIN { if (m == int(m)) printf "%d", m; else printf "%g", m }'
}

# Seconds -> a phrase a human wants to read: "30 sec", "5 min", "1.5 min".
human_dur() {
    if [ "$1" -lt 60 ]; then
        echo "$1 sec"
    else
        echo "$(fmt_min "$(awk -v s="$1" 'BEGIN { printf "%g", s / 60 }')") min"
    fi
}

# A real 24-hour HH:MM time. The 10# forces base 10 so "08"/"09" are not read
# as invalid octal — but note it only works inside (( )), never inside [ ].
valid_hm() {
    [[ "$1" =~ ^([0-9]{1,2}):([0-9]{2})$ ]] || return 1
    local h=$((10#${BASH_REMATCH[1]})) m=$((10#${BASH_REMATCH[2]}))
    [ "$h" -le 23 ] && [ "$m" -le 59 ]
}

hm_to_min() {
    local h=${1%%:*} m=${1##*:}
    echo $((10#$h * 60 + 10#$m))
}

# ---------------- config ----------------

# Only these may appear in the config file. Anything else is ignored.
CONFIG_KEYS="INTERVAL_MIN SNOOZE_MIN SOUND LOOP_SOUND FULLSCREEN GRACE_SEC
WALK_ENABLED WALK_MIN WALK_SOUND BUZZ_ON_MIN BUZZ_GAP_START_MIN BUZZ_GAP_CAP_MIN
WARN_ENABLED WARN_LEAD_MIN IDLE_SKIP IDLE_MIN SCHEDULE_ENABLED SCHEDULE_START
SCHEDULE_END DAYS_OFF WEEKDAYS_ONLY BREAK_TITLE BREAK_MESSAGE WALK_TITLE
WALK_MESSAGE LOCK_BREAK LOCK_ALL_MONITORS LOCK_HOLD_SEC
LOCK_ALARM_SEC LOCK_RELEASE_MARGIN"

# Read the config by parsing it, NOT by sourcing it.
#
# Sourcing would run whatever the file contains: one stray $(...) in it — from
# a bad edit, a botched merge, or anything else that can write to the file —
# would execute as you, every time the daemon ticked. Assigning only known
# names, and never evaluating the values, removes that entirely.
read_config_file() {
    [ -r "$1" ] || return 0
    local line key val k known esc="'\''"
    while IFS= read -r line || [ -n "$line" ]; do
        [[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
        key=${BASH_REMATCH[1]}
        # Word-split the list rather than pattern-match a padded string:
        # CONFIG_KEYS spans several lines, so a key sitting at the start or end
        # of one is bounded by a newline, not a space, and was being dropped.
        known=0
        for k in $CONFIG_KEYS; do
            [ "$k" = "$key" ] && { known=1; break; }
        done
        [ "$known" = 1 ] || continue
        val=${BASH_REMATCH[2]}
        val=${val%"${val##*[![:space:]]}"}          # trim trailing blanks
        case "$val" in
            \'*\')  val=${val:1:${#val}-2}; val=${val//"$esc"/\'} ;;
            \"*\")  val=${val:1:${#val}-2} ;;
        esac
        printf -v "$key" '%s' "$val"
    done < "$1"
}


load_config() {
    INTERVAL_MIN=30
    SNOOZE_MIN=5
    SOUND="$DEFAULT_SOUND"
    LOOP_SOUND=1          # keep the sound going until the alert is dismissed
    FULLSCREEN=1          # take over the screen so the alert cannot hide behind windows
    GRACE_SEC=3           # a click already in flight when the alert appears must
                          # not land on a button; typing is handled separately,
                          # by swallowing every key. 0 disables it.

    # What the alerts actually say. "\n" in a message becomes a line break.
    BREAK_TITLE="Take a break!"
    BREAK_MESSAGE="Have a little walk. Stretch your body and relax a bit, then start again."
    WALK_TITLE="Walk time is up"
    WALK_MESSAGE="Time to get back to work."

    WALK_ENABLED=1        # second stage: tell you when the walk is over
    WALK_MIN=1
    WALK_SOUND="$DEFAULT_WALK_SOUND"
    BUZZ_ON_MIN=1         # length of each back-to-work buzz
    BUZZ_GAP_START_MIN=2  # first silence between buzzes; doubles each round
    BUZZ_GAP_CAP_MIN=15   # ...but never grows past this

    LOCK_BREAK=1          # hold the screen for the whole break, not just the alert
    LOCK_ALL_MONITORS=1   # ...and blank the other screens too, or the lock leaks
    LOCK_HOLD_SEC=5       # how long the unlock button must be held down
    LOCK_ALARM_SEC=10     # a short burst; nothing silences it, and on a one
                          # minute break the usual 90 would be the whole break
    LOCK_RELEASE_MARGIN=120  # how long past the end of a locked break the input
                          # lock lets go on its own, if this app has wedged

    WARN_ENABLED=1        # heads-up notification before a break lands
    WARN_LEAD_MIN=2

    IDLE_SKIP=1           # if you are already away, do not alarm an empty room
    IDLE_MIN=5

    SCHEDULE_ENABLED=0
    SCHEDULE_START="09:00"
    SCHEDULE_END="18:00"
    DAYS_OFF=""           # ISO weekday numbers, 1=Mon .. 7=Sun, e.g. "6,7"
    WEEKDAYS_ONLY=""      # superseded by DAYS_OFF; kept only to migrate

    read_config_file "$CONFIG"

    # Guard against a hand-edited config with nonsense in it.
    local k
    for k in INTERVAL_MIN SNOOZE_MIN WALK_MIN BUZZ_ON_MIN BUZZ_GAP_START_MIN \
             BUZZ_GAP_CAP_MIN WARN_LEAD_MIN IDLE_MIN; do
        printf -v "$k" '%s' "$(norm_num "${!k}")"
    done
    valid_num "$INTERVAL_MIN"       "$MIN_MINUTES" "$MAX_MINUTES" || INTERVAL_MIN=30
    valid_num "$SNOOZE_MIN"         "$MIN_MINUTES" "$MAX_MINUTES" || SNOOZE_MIN=5
    valid_num "$WALK_MIN"           "$MIN_MINUTES" "$MAX_MINUTES" || WALK_MIN=1
    valid_num "$BUZZ_ON_MIN"        "$MIN_MINUTES" "$MAX_MINUTES" || BUZZ_ON_MIN=1
    valid_num "$BUZZ_GAP_START_MIN" "$MIN_MINUTES" "$MAX_MINUTES" || BUZZ_GAP_START_MIN=2
    valid_num "$BUZZ_GAP_CAP_MIN"   "$MIN_MINUTES" "$MAX_MINUTES" || BUZZ_GAP_CAP_MIN=15
    valid_num "$WARN_LEAD_MIN"      "$MIN_MINUTES" "$MAX_MINUTES" || WARN_LEAD_MIN=2
    valid_num "$IDLE_MIN"           "$MIN_MINUTES" "$MAX_MINUTES" || IDLE_MIN=5
    [[ "$GRACE_SEC" =~ ^[0-9]+$ ]] && [ "$GRACE_SEC" -le 30 ] || GRACE_SEC=3
    # A hold of zero would make the unlock button a single click, which is the
    # one thing it must never be; a huge one would make it unusable.
    [[ "$LOCK_HOLD_SEC" =~ ^[0-9]+$ ]] &&
        [ "$LOCK_HOLD_SEC" -ge 1 ] && [ "$LOCK_HOLD_SEC" -le 30 ] || LOCK_HOLD_SEC=5
    [[ "$LOCK_ALARM_SEC" =~ ^[0-9]+$ ]] &&
        [ "$LOCK_ALARM_SEC" -ge 1 ] && [ "$LOCK_ALARM_SEC" -le 300 ] || LOCK_ALARM_SEC=10
    # The safety net must outlast a slow-but-alive app, or it would cut a
    # working lock loose part way through the break it is holding.
    [[ "$LOCK_RELEASE_MARGIN" =~ ^[0-9]+$ ]] &&
        [ "$LOCK_RELEASE_MARGIN" -ge 10 ] && [ "$LOCK_RELEASE_MARGIN" -le 3600 ] ||
        LOCK_RELEASE_MARGIN=120

    # An older config had a single weekends-off tick box. Carry it across the
    # first time we see one, so nobody silently loses their days off.
    [ -z "$DAYS_OFF" ] && [ "$WEEKDAYS_ONLY" = "1" ] && DAYS_OFF="6,7"
    [[ "$DAYS_OFF" =~ ^[1-7](,[1-7])*$ ]] || DAYS_OFF=""

    # Never let the alerts end up with nothing to say.
    [ -n "$BREAK_TITLE" ]   || BREAK_TITLE="Take a break!"
    [ -n "$WALK_TITLE" ]    || WALK_TITLE="Walk time is up"

    valid_hm "$SCHEDULE_START" || SCHEDULE_START="09:00"
    valid_hm "$SCHEDULE_END"   || SCHEDULE_END="18:00"
    [ -r "$SOUND" ]      || SOUND="$DEFAULT_SOUND"
    [ -r "$WALK_SOUND" ] || WALK_SOUND="$DEFAULT_WALK_SOUND"

    # A gap cap below the starting gap would make the backoff go backwards.
    awk -v a="$BUZZ_GAP_CAP_MIN" -v b="$BUZZ_GAP_START_MIN" 'BEGIN{exit !(a<b)}' &&
        BUZZ_GAP_CAP_MIN=$BUZZ_GAP_START_MIN

    # What the daemon actually counts down in.
    INTERVAL_SEC=$(min_to_sec "$INTERVAL_MIN")
    SNOOZE_SEC=$(min_to_sec "$SNOOZE_MIN")
    WALK_SEC=$(min_to_sec "$WALK_MIN")
    BUZZ_ON_SEC=$(min_to_sec "$BUZZ_ON_MIN")
    BUZZ_GAP_START_SEC=$(min_to_sec "$BUZZ_GAP_START_MIN")
    BUZZ_GAP_CAP_SEC=$(min_to_sec "$BUZZ_GAP_CAP_MIN")
    WARN_LEAD_SEC=$(min_to_sec "$WARN_LEAD_MIN")
    IDLE_SEC=$(min_to_sec "$IDLE_MIN")
}

# Single-quote a value for a file that gets sourced. Single quotes stop bash
# expanding anything inside, so a message containing $(...) or backticks is
# text and nothing more; an embedded quote is closed, escaped and reopened.
sq() { printf "'%s'" "${1//\'/\'\\\'\'}"; }

save_config() {
    umask 077
    cat > "$CONFIG" <<EOF
# Break-reminder settings. Edit here or use the app window.

# --- timing (minutes; fractions allowed, 0.5 = 30 seconds) ---
INTERVAL_MIN=$INTERVAL_MIN
SNOOZE_MIN=$SNOOZE_MIN

# --- second stage: the walk itself ---
WALK_ENABLED=$WALK_ENABLED
WALK_MIN=$WALK_MIN
BUZZ_ON_MIN=$BUZZ_ON_MIN
BUZZ_GAP_START_MIN=$BUZZ_GAP_START_MIN
BUZZ_GAP_CAP_MIN=$BUZZ_GAP_CAP_MIN
LOCK_BREAK=$LOCK_BREAK
LOCK_ALL_MONITORS=$LOCK_ALL_MONITORS
LOCK_HOLD_SEC=$LOCK_HOLD_SEC
LOCK_ALARM_SEC=$LOCK_ALARM_SEC
LOCK_RELEASE_MARGIN=$LOCK_RELEASE_MARGIN

# --- heads-up before a break ---
WARN_ENABLED=$WARN_ENABLED
WARN_LEAD_MIN=$WARN_LEAD_MIN

# --- skip the alarm when you are already away ---
IDLE_SKIP=$IDLE_SKIP
IDLE_MIN=$IDLE_MIN

# --- what the alerts say ("\n" makes a line break) ---
BREAK_TITLE=$(sq "$BREAK_TITLE")
BREAK_MESSAGE=$(sq "$BREAK_MESSAGE")
WALK_TITLE=$(sq "$WALK_TITLE")
WALK_MESSAGE=$(sq "$WALK_MESSAGE")

# --- sounds and appearance ---
SOUND=$(sq "$SOUND")
WALK_SOUND=$(sq "$WALK_SOUND")
LOOP_SOUND=$LOOP_SOUND
FULLSCREEN=$FULLSCREEN
GRACE_SEC=$GRACE_SEC

# --- daily schedule ---
SCHEDULE_ENABLED=$SCHEDULE_ENABLED
SCHEDULE_START=$(sq "$SCHEDULE_START")
SCHEDULE_END=$(sq "$SCHEDULE_END")
DAYS_OFF=$(sq "$DAYS_OFF")
EOF
}

# ---------------- when should the reminder run ----------------

# Which weekday does the current shift belong to? For a window that crosses
# midnight, the small hours still belong to the day the shift started on — so a
# Friday-night shift is Friday's, not Saturday's.
shift_day() {
    local day
    day=$(date +%u)
    if [ "$(hm_to_min "$SCHEDULE_START")" -gt "$(hm_to_min "$SCHEDULE_END")" ] &&
       [ "$(hm_to_min "$(date +%H:%M)")" -lt "$(hm_to_min "$SCHEDULE_END")" ]; then
        day=$(date -d 'yesterday' +%u)
    fi
    echo "$day"
}

# Is this ISO weekday (1=Mon .. 7=Sun) one of the days off?
is_day_off() {
    [ -n "$DAYS_OFF" ] || return 1
    local d
    for d in ${DAYS_OFF//,/ }; do
        [ "$d" = "$1" ] && return 0
    done
    return 1
}

# True when the daily schedule is on and the clock is inside the window.
# Handles windows that cross midnight (e.g. 22:00 -> 02:00).
in_schedule() {
    [ "$SCHEDULE_ENABLED" = "1" ] || return 1
    is_day_off "$(shift_day)" && return 1

    local now start end
    now=$(hm_to_min "$(date +%H:%M)")
    start=$(hm_to_min "$SCHEDULE_START")
    end=$(hm_to_min "$SCHEDULE_END")
    if [ "$start" -le "$end" ]; then
        [ "$now" -ge "$start" ] && [ "$now" -lt "$end" ]
    else
        [ "$now" -ge "$start" ] || [ "$now" -lt "$end" ]
    fi
}

paused_today() { [ "$(cat "$PAUSE_FILE" 2>/dev/null)" = "$(date +%F)" ]; }
pause_today()  { date +%F > "$PAUSE_FILE"; }
resume()       { rm -f "$PAUSE_FILE"; }

# The reminder runs if you turned it on by hand, OR the schedule says so —
# unless you told it to leave you alone for the rest of today.
is_active() {
    paused_today && return 1
    [ -f "$MANUAL_FLAG" ] || in_schedule
}

# ---------------- idle time ----------------
#
# Seconds since you last touched the mouse or keyboard. There is no one way to
# ask that on Linux, so each desktop family gets the source it actually has,
# tried in order until one answers:
#
#   mutter   GNOME (Wayland or X11) - Mutter's own idle monitor over D-Bus
#   wayland  KDE Plasma 6, Sway, Hyprland ... - the ext-idle-notify protocol,
#            through the watcher idle.py keeps running beside the daemon
#   x11      XFCE, MATE, Cinnamon, Budgie, any X11 session - MIT-SCREEN-SAVER
#   logind   last resort: the session's idle flag. Coarse - it only flips when
#            the desktop itself decides you are idle (screen dimming)
#
# KDE's freedesktop ScreenSaver GetSessionIdleTime is deliberately not on the
# list: on Wayland it answers "not supported", and the implementations that do
# answer disagree on whether the number is seconds or milliseconds.
#
# Nothing answering means 0 - assume present, so we never go silent by mistake.
IDLE_STATE="$STATE_DIR/idle_state"   # written by `idle.py watch`
IDLE_WATCH_PID="$STATE_DIR/idle_watch.pid"

idle_mutter() {
    local out
    out=$(gdbus call --session --dest org.gnome.Mutter.IdleMonitor \
            --object-path /org/gnome/Mutter/IdleMonitor/Core \
            --method org.gnome.Mutter.IdleMonitor.GetIdletime 2>/dev/null)
    # Anchor on "uint64 " — a bare ([0-9]+) matches the 64 in the type name
    # itself, which silently pinned the idle time at 0 and stopped the
    # skip-when-away check from ever firing.
    [[ "$out" =~ uint64\ ([0-9]+) ]] || return 1
    echo $(( BASH_REMATCH[1] / 1000 ))
}

# Only trusted while the watcher that writes it is alive: a file left by one
# that died would otherwise freeze the reading at whatever it last said.
idle_wayland() {
    idle_watch_running || return 1
    local st
    st=$(cat "$IDLE_STATE" 2>/dev/null) || return 1
    case "$st" in
        active) echo 0 ;;
        "idle "*)
            local since=${st#idle } now
            [[ "$since" =~ ^[0-9]+$ ]] || return 1
            now=$(date +%s)
            [ "$now" -ge "$since" ] && echo $(( now - since )) || echo 0 ;;
        *) return 1 ;;
    esac
}

idle_x11() {
    [ -n "${DISPLAY:-}" ] || return 1
    # A Wayland session's XWayland has no idle extension; skip the Python start.
    [ "${XDG_SESSION_TYPE:-}" = wayland ] && return 1
    local out
    out=$(python3 "$APP_DIR/idle.py" x11 2>/dev/null) || return 1
    [[ "$out" =~ ^[0-9]+$ ]] || return 1
    echo "$out"
}

idle_logind() {
    local sid=${XDG_SESSION_ID:-} out hint since now
    [ -n "$sid" ] || return 1
    command -v loginctl >/dev/null 2>&1 || return 1
    out=$(loginctl show-session "$sid" -p IdleHint -p IdleSinceHint 2>/dev/null) || return 1
    hint=$(sed -n 's/^IdleHint=//p' <<< "$out")
    since=$(sed -n 's/^IdleSinceHint=//p' <<< "$out")
    case "$hint" in
        no) echo 0 ;;
        yes)
            [[ "$since" =~ ^[0-9]+$ ]] && [ "$since" -gt 0 ] || return 1
            now=$(date +%s)
            echo $(( now - since / 1000000 )) ;;
        *) return 1 ;;
    esac
}

# "<seconds> <source>", e.g. "312 wayland" - or "0 none".
idle_probe() {
    local b s
    for b in mutter wayland x11 logind; do
        if s=$("idle_$b"); then
            echo "$s $b"
            return 0
        fi
    done
    echo "0 none"
}

idle_sec() {
    local r
    r=$(idle_probe)
    echo "${r%% *}"
}

idle_watch_running() {
    local pid
    pid=$(cat "$IDLE_WATCH_PID" 2>/dev/null)
    [[ "$pid" =~ ^[0-9]+$ ]] || return 1
    kill -0 "$pid" 2>/dev/null || return 1
    tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q 'idle\.py watch'
}

# Started by the daemon, as its own child: the watcher notices the daemon is
# gone and exits by itself, so even a kill -9 does not leave it behind.
# Only worth running on Wayland where Mutter is not there to ask instead.
start_idle_watch() {
    [ -n "${WAYLAND_DISPLAY:-}" ] || return 1
    idle_mutter >/dev/null && return 1
    idle_watch_running && return 0
    python3 "$APP_DIR/idle.py" watch "$IDLE_STATE" >/dev/null 2>&1 < /dev/null &
    echo $! > "$IDLE_WATCH_PID"
    return 0
}

stop_idle_watch() {
    idle_watch_running && kill "$(cat "$IDLE_WATCH_PID")" 2>/dev/null
    rm -f "$IDLE_WATCH_PID" "$IDLE_STATE"
}

user_is_away() {
    [ "$IDLE_SKIP" = "1" ] || return 1
    [ "$(idle_sec)" -ge "$IDLE_SEC" ]
}

# ---------------- stats ----------------

record_stat() {
    ( umask 077; mkdir -p "$STATS_DIR"; touch "$STATS_FILE" )
    printf '%s\t%s\n' "$(date +%F)" "$1" >> "$STATS_FILE"
}

# Count of one event today. Note grep -c already prints 0 when nothing matches
# *and* exits non-zero, so a `|| echo 0` fallback here would print 0 twice.
stat_today() {
    [ -r "$STATS_FILE" ] || { echo 0; return; }
    local n
    n=$(grep -c -P "^$(date +%F)\t$1\$" "$STATS_FILE" 2>/dev/null)
    echo "${n:-0}"
}

stats_summary() {
    local t s k c
    t=$(stat_today taken); s=$(stat_today snoozed); k=$(stat_today skipped)
    c=$(stat_today cut_short)
    echo "Today: $t taken, $s snoozed, $k skipped, $c cut short"
}

# ---------------- daemon ----------------

# Is this PID a live daemon of ours? Checking the command line too means a
# recycled PID belonging to some unrelated program cannot masquerade as one.
is_our_daemon() {
    local pid=$1
    [[ "$pid" =~ ^[0-9]+$ ]] || return 1
    kill -0 "$pid" 2>/dev/null || return 1
    tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q 'alarmd\.sh'
}

daemon_running() {
    [ -r "$DAEMON_PID" ] || return 1
    is_our_daemon "$(cat "$DAEMON_PID" 2>/dev/null)"
}

# Single-instance guard, called by the daemon itself. Returns 0 if we got the slot.
#
# This deliberately avoids flock: the daemon spends its life in `sleep`, and a
# child inherits the lock fd, so a kill -9'd daemon left its orphaned sleep
# holding the lock and blocked the next daemon from ever starting. An atomic
# O_EXCL create plus a liveness check on the recorded PID has no such problem.
claim_daemon_slot() {
    local me=$BASHPID i
    for i in 1 2; do
        if ( set -o noclobber; echo "$me" > "$DAEMON_PID" ) 2>/dev/null; then
            return 0
        fi
        is_our_daemon "$(cat "$DAEMON_PID" 2>/dev/null)" && return 1
        rm -f "$DAEMON_PID"   # stale file left by a crash — take the slot over
    done
    return 1
}

start_daemon() {
    daemon_running && return 0
    setsid "$APP_DIR/alarmd.sh" >/dev/null 2>&1 < /dev/null &
    local i
    for i in $(seq 15); do
        daemon_running && return 0
        sleep 0.2
    done
    return 1
}

# Nudge the daemon to re-read the state now rather than at its next tick.
#
# It spends nearly all its life inside `sleep`, and bash defers a trap until
# the running command returns — so the quickest way to wake it is to end that
# sleep. Only processes actually named `sleep` are targeted: while an alert is
# on screen alert.py is also a child, and must not be touched.
poke_daemon() {
    local pid
    pid=$(cat "$DAEMON_PID" 2>/dev/null)
    is_our_daemon "$pid" || return 1
    pkill -P "$pid" -x sleep 2>/dev/null
    return 0
}

stop_daemon() {
    local pid i
    [ -r "$DAEMON_PID" ] || { rm -f "$NEXT_FILE"; return 0; }
    pid=$(cat "$DAEMON_PID")
    kill "$pid" 2>/dev/null

    # The daemon spends most of its life inside `sleep`, and bash only runs a
    # trap once the current command returns. Kill that sleep so the daemon's
    # cleanup fires now instead of up to TICK seconds from now.
    pkill -TERM -P "$pid" 2>/dev/null

    # Do not report "stopped" until it really is: start_daemon would otherwise
    # hit the still-held lock and quietly leave us with no daemon at all.
    for i in $(seq 40); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.2
    done
    kill -0 "$pid" 2>/dev/null && kill -KILL "$pid" 2>/dev/null

    rm -f "$DAEMON_PID" "$NEXT_FILE"
}

# ---------------- sound ----------------

# The command that plays a sound file (the file is appended as the last argument).
# pw-play talks to PipeWire and handles .oga/.wav/.flac; the rest are fallbacks
# for a differently configured machine.
player_cmd() {
    if command -v pw-play >/dev/null 2>&1; then echo "pw-play"; return 0; fi
    if command -v paplay >/dev/null 2>&1; then echo "paplay"; return 0; fi
    case "${SOUND,,}" in
        *.wav) command -v aplay >/dev/null 2>&1 && { echo "aplay -q"; return 0; } ;;
    esac
    command -v canberra-gtk-play >/dev/null 2>&1 && { echo "canberra-gtk-play -f"; return 0; }
    return 1
}

play_once() {
    [ -r "$SOUND" ] || return 1
    local -a cmd
    read -r -a cmd <<< "$(player_cmd)"
    [ "${#cmd[@]}" -gt 0 ] || return 1
    "${cmd[@]}" "$SOUND" 2>/dev/null
}

# Desktop notifications clean up after themselves. Every one is marked
# transient, which the freedesktop spec defines as "show it, then drop it -
# never keep it in the history" (honoured by GNOME, KDE, XFCE, Cinnamon, MATE
# and Budgie alike). Without it, KDE in particular kept every "Break coming up"
# in its notification list until there was a long column of them.
#
# Each one also replaces the one before, so a desktop that ignores the hint
# still never shows more than one of ours. How long one stays on screen is left
# to the desktop.
NOTIFY_ID_FILE="$STATE_DIR/notify_id"

# notify-send learnt --print-id/--replace-id in 0.7.10; Ubuntu 22.04 ships
# 0.7.9. Ask it rather than parse a version, and remember the answer.
notify_can_replace() {
    if [ -z "${_NOTIFY_REPLACE:-}" ]; then
        if notify-send --help 2>/dev/null | grep -q -- '--replace-id'; then
            _NOTIFY_REPLACE=yes
        else
            _NOTIFY_REPLACE=no
        fi
    fi
    [ "$_NOTIFY_REPLACE" = yes ]
}

notify() {
    command -v notify-send >/dev/null 2>&1 || return 0
    local -a cmd=(notify-send -a "BackAtIt" -i alarm-clock
                  -h boolean:transient:true
                  -h string:desktop-entry:backatit)
    if notify_can_replace; then
        local old new
        old=$(cat "$NOTIFY_ID_FILE" 2>/dev/null)
        [[ "$old" =~ ^[0-9]+$ ]] && [ "$old" -gt 0 ] && cmd+=(-r "$old")
        new=$("${cmd[@]}" -p "$1" "$2" 2>/dev/null)
        [[ "$new" =~ ^[0-9]+$ ]] && echo "$new" > "$NOTIFY_ID_FILE"
    else
        "${cmd[@]}" "$1" "$2" 2>/dev/null
    fi
    return 0
}

# ---------------- the alert ----------------

# Show an alert window and return the clicked button's code.
# The heavy lifting is in alert.py: yad could neither go fullscreen on this
# compositor nor ignore the keyboard, and a stray keystroke dismissing the
# alarm the moment it appeared was the whole problem.
show_alert() {
    local -a cmd=(python3 "$APP_DIR/alert.py"
                  --player "$(player_cmd)"
                  --grace "$GRACE_SEC")
    [ "$FULLSCREEN" = "1" ] && cmd+=(--fullscreen)
    cmd+=("$@")

    # Wayland compositors (GNOME, KDE) will not let a window raise itself above
    # the one you are using. Under XWayland the keep-above hint is honoured,
    # and the input lock can hold Super and Alt-Tab, so prefer it.
    # Its notes ("input locked", "could not lock input ...") go to the daemon
    # log, which is where anyone troubleshooting a desktop will look.
    if [ -n "$DISPLAY" ]; then
        GDK_BACKEND=x11 "${cmd[@]}" 2>>"$LOG"
    else
        "${cmd[@]}" 2>>"$LOG"
    fi
}

break_alert() {
    local mode=loop
    [ "$LOOP_SOUND" = "1" ] || mode=once
    show_alert \
        --title "$BREAK_TITLE" \
        --message "$BREAK_MESSAGE" \
        --hint "this only closes when you click" \
        --sound "$SOUND" --buzz-mode "$mode" --sound-max 90 \
        --default-code 0 \
        --button "I took my break!|0|primary" \
        --button "Snooze $(human_dur "$SNOOZE_SEC")|10|normal" \
        --button "Turn off reminders|20|quiet"
}

walk_alert() {
    show_alert \
        --title "$WALK_TITLE" \
        --message "$WALK_MESSAGE" \
        --hint "this keeps buzzing until you click" \
        --sound "$WALK_SOUND" --buzz-mode backoff \
        --buzz-on "$BUZZ_ON_SEC" \
        --gap-start "$BUZZ_GAP_START_SEC" \
        --gap-cap "$BUZZ_GAP_CAP_SEC" \
        --default-code 0 \
        --button "I'm back at work|0|primary|now" \
        --button "Turn off reminders|20|quiet"
}

# Is this break one the screen gets locked for? The lock ends when the walk is
# up, so without a walk stage there is nothing for it to end at.
use_locked_cycle() {
    [ "$LOCK_BREAK" = "1" ] && [ "$WALK_ENABLED" = "1" ]
}

# The whole break in a single window: the prompt, then the break itself with
# the screen held, then the call back. One process rather than three, because
# the gap between break_alert ending and walk_alert starting is precisely the
# moment you could sit back down - which is what the lock exists to stop.
#
# Fullscreen is forced regardless of FULLSCREEN: a window that claims the
# mouse and keyboard but only covers part of the screen is the worst of both.
locked_break_cycle() {
    local mode=loop
    [ "$LOOP_SOUND" = "1" ] || mode=once
    local -a lock=(--lock --fullscreen
                   --walk-seconds "$WALK_SEC"
                   --hold-seconds "$LOCK_HOLD_SEC"
                   --release-margin "$LOCK_RELEASE_MARGIN")
    [ "$LOCK_ALL_MONITORS" = "1" ] && lock+=(--all-monitors)
    # No "I took my break!": the screen is locked the moment this appears, so
    # acknowledging it would only start a clock that may as well already be
    # running. Snooze and "Turn off reminders" both stay - putting a break off
    # and calling the day off have to remain possible from here.
    #
    # The alarm is a short burst rather than the usual 90 seconds, because
    # nothing silences it any more - and on a one-minute break the old cap
    # would have meant alarm for the entire break.
    show_alert \
        --title "$BREAK_TITLE" \
        --message "$BREAK_MESSAGE" \
        --hint "the screen stays locked until the break is over" \
        --sound "$SOUND" --buzz-mode "$mode" \
        --sound-max "$LOCK_ALARM_SEC" \
        --default-code 0 \
        --button "Snooze $(human_dur "$SNOOZE_SEC")|10|normal" \
        --button "Turn off reminders|20|quiet" \
        "${lock[@]}" \
        --walk-title "$WALK_TITLE" \
        --walk-message "$WALK_MESSAGE" \
        --walk-hint "this keeps buzzing until you click" \
        --walk-sound "$WALK_SOUND" \
        --buzz-on "$BUZZ_ON_SEC" \
        --gap-start "$BUZZ_GAP_START_SEC" \
        --gap-cap "$BUZZ_GAP_CAP_SEC" \
        --walk-button "I'm back at work|0|primary|now" \
        --walk-button "Turn off reminders|20|quiet"
}
