#!/bin/bash
# Daemon lifecycle: one instance only, clean stop, crash recovery, the state
# it publishes for the live counter, and the poke that makes it react at once.
#
# The app is copied into a sandbox and run from there. alarmd.sh resolves its
# config relative to XDG_CONFIG_HOME, so running it in place would make it read
# your real settings, and counting daemons system-wide would find the real one.
APP=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

SB=$(mktemp -d)
cp "$APP"/{alarmd.sh,lib.sh,alert.py,alertctl.sh} "$SB/"
export XDG_RUNTIME_DIR="$SB/run"; mkdir -p "$XDG_RUNTIME_DIR"
export XDG_STATE_HOME="$SB/state"
export XDG_CONFIG_HOME="$SB/cfg"; mkdir -p "$XDG_CONFIG_HOME/backatit"

cat > "$XDG_CONFIG_HOME/backatit/config" <<CFG
INTERVAL_MIN=30
SNOOZE_MIN=5
WALK_ENABLED=0
WARN_ENABLED=0
IDLE_SKIP=0
SCHEDULE_ENABLED=0
CFG

cd "$SB" || exit 1
. "$SB/lib.sh"
trap 'stop_daemon >/dev/null 2>&1; rm -rf "$SB"' EXIT

fail=0
ck() { if [ "$2" = "$3" ]; then echo "  ok   $1 -> $2"; else echo "  FAIL $1 -> got [$2] want [$3]"; fail=1; fi; }
count() {
    local n=0 p
    for p in $(ps -eo pid=); do
        # cat, not a redirect: a process exiting mid-scan makes the shell
        # itself complain about the missing file, which clutters the output.
        cat "/proc/$p/cmdline" 2>/dev/null | tr '\0' ' ' | grep -q "$SB/alarmd.sh" && n=$((n + 1))
    done
    echo "$n"
}

echo "=== start / stop ==="
ck "baseline" "$(count)" 0
start_daemon && echo "  ok   started (pid $(cat "$DAEMON_PID"))" || { echo "  FAIL start"; fail=1; }
ck "exactly one daemon" "$(count)" 1
stop_daemon
ck "stopped cleanly" "$(count)" 0
ck "pid file removed" "$([ -f "$DAEMON_PID" ] && echo yes || echo no)" no

echo "=== stop then immediately start (the race that used to leave none) ==="
start_daemon; stop_daemon; start_daemon
sleep 0.5
ck "still exactly one" "$(count)" 1
daemon_running && echo "  ok   daemon_running agrees" || { echo "  FAIL daemon_running"; fail=1; }

echo "=== 8 simultaneous launches ==="
for i in $(seq 8); do setsid "$SB/alarmd.sh" >/dev/null 2>&1 </dev/null & done
sleep 2
ck "still exactly one" "$(count)" 1

echo "=== crash recovery (kill -9 must not wedge the next start) ==="
kill -KILL "$(cat "$DAEMON_PID")" 2>/dev/null
sleep 0.5
daemon_running && { echo "  FAIL still reported running"; fail=1; } || echo "  ok   reports not running"
start_daemon && echo "  ok   recovered (pid $(cat "$DAEMON_PID"))" || { echo "  FAIL could not restart"; fail=1; }
ck "one daemon after recovery" "$(count)" 1

echo "=== published state for the live counter ==="
touch "$MANUAL_FLAG"; poke_daemon >/dev/null
for i in $(seq 60); do [ -f "$NEXT_EPOCH" ] && break; sleep 0.2; done
ck "phase published" "$(cat "$PHASE_FILE" 2>/dev/null)" work
epoch=$(cat "$NEXT_EPOCH" 2>/dev/null)
if [[ "$epoch" =~ ^[0-9]+$ ]]; then
    left=$(( epoch - $(date +%s) ))
    [ "$left" -gt 1700 ] && [ "$left" -le 1800 ] &&
        echo "  ok   counter would read ${left}s (the sandbox's 30 min interval)" ||
        { echo "  FAIL countdown out of range: ${left}s"; fail=1; }
else
    echo "  FAIL next_epoch missing or not a number"; fail=1
fi

echo "=== poke_daemon makes it react at once, not at the next tick ==="
rm -f "$MANUAL_FLAG" "$PHASE_FILE" "$NEXT_EPOCH"; sleep 6
t0=$(date +%s%N)
touch "$MANUAL_FLAG"; poke_daemon >/dev/null
for i in $(seq 400); do [ -f "$PHASE_FILE" ] && break; sleep 0.02; done
ms=$(( ($(date +%s%N) - t0) / 1000000 ))
if [ -f "$PHASE_FILE" ] && [ "$ms" -lt 1500 ]; then
    echo "  ok   reacted in ${ms}ms (the tick alone would take up to 5000ms)"
else
    echo "  FAIL reacted in ${ms}ms"; fail=1
fi

echo "=== switching off clears the published state ==="
rm -f "$MANUAL_FLAG"; poke_daemon >/dev/null
for i in $(seq 30); do [ -f "$PHASE_FILE" ] || break; sleep 0.2; done
ck "phase cleared"      "$([ -f "$PHASE_FILE" ] && echo yes || echo no)" no
ck "next_epoch cleared" "$([ -f "$NEXT_EPOCH" ] && echo yes || echo no)" no

stop_daemon
ck "final daemon count" "$(count)" 0
exit $fail
