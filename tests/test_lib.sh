#!/bin/bash
# Pure logic in lib.sh: times, config parsing, schedules, days off, pausing,
# statistics, away detection and sound helpers.
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
. ./lib.sh

CONFIG=/dev/null
STATE_DIR=$(mktemp -d); MANUAL_FLAG="$STATE_DIR/manual_on"; PAUSE_FILE="$STATE_DIR/paused_on"
STATS_DIR=$(mktemp -d); STATS_FILE="$STATS_DIR/stats.tsv"
trap 'rm -rf "$STATE_DIR" "$STATS_DIR"' EXIT

fail=0
ck() { if [ "$2" = "$3" ]; then echo "  ok   $1 -> $2"; else echo "  FAIL $1 -> got [$2] want [$3]"; fail=1; fi; }

echo "=== minutes -> seconds (fractions must survive) ==="
for pair in "30 1800" "10 600" "1 60" "0.5 30" "1.5 90" "0.75 45" "2.25 135" "240 14400"; do
  set -- $pair; ck "$1 min" "$(min_to_sec "$1")" "$2"
done

echo "=== human_dur ==="
ck "30s"   "$(human_dur 30)"   "30 sec"
ck "60s"   "$(human_dur 60)"   "1 min"
ck "90s"   "$(human_dur 90)"   "1.5 min"
ck "1800s" "$(human_dur 1800)" "30 min"

echo "=== valid_hm ==="
for t in 09:00 9:00 23:59 00:00; do valid_hm "$t" && echo "  ok   $t accepted" || { echo "  FAIL $t rejected"; fail=1; }; done
for t in 24:00 09:60 nope 9 "" 25:99; do valid_hm "$t" && { echo "  FAIL $t accepted"; fail=1; } || echo "  ok   $t rejected"; done

echo "=== config validation falls back on junk ==="
for v in 0 0.1 241 abc -5 ""; do
  C=$(mktemp); printf 'INTERVAL_MIN=%s\n' "$v" > "$C"
  ( CONFIG=$C; load_config; [ "$INTERVAL_MIN" = "30" ] ) && echo "  ok   [$v] -> default 30" || { echo "  FAIL [$v] not rejected"; fail=1; }
  rm -f "$C"
done
C=$(mktemp)
printf 'INTERVAL_MIN=0,5\n' > "$C"
( CONFIG=$C; load_config; [ "$INTERVAL_SEC" = "30" ] ) && echo "  ok   comma decimal 0,5 -> 30s" || { echo "  FAIL comma decimal"; fail=1; }
printf 'BUZZ_GAP_START_MIN=5\nBUZZ_GAP_CAP_MIN=1\n' > "$C"
( CONFIG=$C; load_config; [ "$BUZZ_GAP_CAP_MIN" = "5" ] ) && echo "  ok   nag cap below start is clamped up" || { echo "  FAIL cap clamp"; fail=1; }
printf 'BREAK_TITLE=""\nWALK_TITLE=""\n' > "$C"
( CONFIG=$C; load_config; [ -n "$BREAK_TITLE" ] && [ -n "$WALK_TITLE" ] ) &&
  echo "  ok   empty alert headings fall back" || { echo "  FAIL empty headings kept"; fail=1; }
rm -f "$C"

echo "=== the config is parsed, never executed ==="
C=$(mktemp)
printf 'INTERVAL_MIN=5\nEVIL=$(touch %s.pwned)\nALSO=`touch %s.pwned2`\n' "$C" "$C" > "$C"
( CONFIG=$C; load_config >/dev/null 2>&1 )
if [ -e "$C.pwned" ] || [ -e "$C.pwned2" ]; then
  echo "  FAIL config contents were executed"; fail=1
else
  echo "  ok   nothing in the config runs"
fi
( CONFIG=$C; load_config; [ "$INTERVAL_MIN" = "5" ] ) && echo "  ok   real settings still read" || { echo "  FAIL value not parsed"; fail=1; }
rm -f "$C" "$C.pwned" "$C.pwned2"

echo "=== an unknown key cannot set a shell variable ==="
C=$(mktemp)
printf 'PATH=/tmp/evil\nHOME=/tmp/evil\nINTERVAL_MIN=7\n' > "$C"
out=$( CONFIG=$C; load_config; printf '%s|%s' "$INTERVAL_MIN" "$HOME" )
case "$out" in
  "7|/tmp/evil") echo "  FAIL HOME was overwritten by the config"; fail=1 ;;
  "7|"*)         echo "  ok   only whitelisted keys are assigned" ;;
  *)             echo "  FAIL unexpected: $out"; fail=1 ;;
esac
rm -f "$C"

echo "=== every whitelisted key is actually read ==="
# CONFIG_KEYS spans several lines; a key at a line boundary was once silently
# dropped by a padded-string membership test, so check all of them.
C=$(mktemp); miss=0
for k in $CONFIG_KEYS; do printf '%s=TESTVAL\n' "$k" >> "$C"; done
for k in $CONFIG_KEYS; do
  v=$( unset "$k"; read_config_file "$C"; printf '%s' "${!k}" )
  [ "$v" = "TESTVAL" ] || { echo "  FAIL $k was skipped (got '$v')"; miss=1; fail=1; }
done
[ "$miss" = 0 ] && echo "  ok   all $(echo $CONFIG_KEYS | wc -w) keys round-trip"
rm -f "$C"

echo "=== quoting styles the writers produce ==="
C=$(mktemp)
cat > "$C" <<'CFG'
INTERVAL_MIN=12.5
BREAK_TITLE='it'\''s time'
BREAK_MESSAGE='a $(dangerous) `looking` "string"'
SOUND="/tmp/x.oga"
CFG
( CONFIG=$C; load_config
  ok=0
  [ "$INTERVAL_MIN" = "12.5" ] && echo "  ok   bare number" || { echo "  FAIL bare number [$INTERVAL_MIN]"; ok=1; }
  [ "$BREAK_TITLE" = "it's time" ] && echo "  ok   single-quoted with an escaped quote" || { echo "  FAIL title [$BREAK_TITLE]"; ok=1; }
  [ "$BREAK_MESSAGE" = 'a $(dangerous) `looking` "string"' ] && echo "  ok   shell metacharacters kept as text" || { echo "  FAIL message [$BREAK_MESSAGE]"; ok=1; }
  exit $ok ) || fail=1
rm -f "$C"

echo "=== schedule window ==="
load_config; SCHEDULE_ENABLED=1; DAYS_OFF=""
sched() { # start end now expect
  SCHEDULE_START=$1; SCHEDULE_END=$2
  eval "date() { case \"\$*\" in '+%H:%M') echo '$3' ;; '+%u') echo 3 ;; *) command date \"\$@\" ;; esac; }"
  if in_schedule; then g=IN; else g=OUT; fi
  unset -f date
  ck "$1-$2 at $3" "$g" "$4"
}
sched 09:00 18:00 08:59 OUT
sched 09:00 18:00 09:00 IN
sched 09:00 18:00 17:59 IN
sched 09:00 18:00 18:00 OUT
sched 08:00 09:00 08:30 IN      # leading zero must not be read as octal
sched 22:00 02:00 21:59 OUT     # window crossing midnight
sched 22:00 02:00 22:00 IN
sched 22:00 02:00 00:30 IN
sched 22:00 02:00 01:59 IN
sched 22:00 02:00 02:00 OUT
SCHEDULE_ENABLED=0
in_schedule && { echo "  FAIL disabled schedule fired"; fail=1; } || echo "  ok   disabled schedule never fires"

echo "=== days off (any combination, not just weekends) ==="
SCHEDULE_ENABLED=1
wd() { # dow hm expect   (DAYS_OFF set by the caller)
  eval "date() { case \"\$*\" in
    '+%u') echo $1 ;; '+%H:%M') echo '$2' ;;
    '-d yesterday +%u') echo \$(( $1 == 1 ? 7 : $1 - 1 )) ;;
    *) command date \"\$@\" ;; esac; }"
  if in_schedule; then g=IN; else g=OUT; fi
  unset -f date
  ck "days_off=[$DAYS_OFF] dow=$1 at $2" "$g" "$3"
}
SCHEDULE_START=09:00; SCHEDULE_END=18:00
DAYS_OFF="";          wd 1 13:00 IN;  wd 6 13:00 IN;  wd 7 13:00 IN
DAYS_OFF="6,7";       wd 1 13:00 IN;  wd 5 13:00 IN;  wd 6 13:00 OUT; wd 7 13:00 OUT
DAYS_OFF="5";         wd 4 13:00 IN;  wd 5 13:00 OUT; wd 6 13:00 IN
DAYS_OFF="1,3,5";     wd 1 13:00 OUT; wd 2 13:00 IN;  wd 3 13:00 OUT; wd 5 13:00 OUT
DAYS_OFF="1,2,3,4,5,6,7"; wd 1 13:00 OUT; wd 4 13:00 OUT; wd 7 13:00 OUT

echo "=== days off with an overnight window (a shift belongs to the day it began) ==="
SCHEDULE_START=22:00; SCHEDULE_END=02:00; DAYS_OFF="6,7"
wd 5 23:00 IN     # Friday night is Friday's shift
wd 6 01:00 IN     # ...running into Saturday morning
wd 6 23:00 OUT    # Saturday's own shift is off
wd 7 01:00 OUT

echo "=== is_day_off ==="
DAYS_OFF="2,4"
is_day_off 2 && echo "  ok   2 is off" || { echo "  FAIL 2 should be off"; fail=1; }
is_day_off 3 && { echo "  FAIL 3 should not be off"; fail=1; } || echo "  ok   3 is not off"
DAYS_OFF=""
is_day_off 1 && { echo "  FAIL empty list marks days off"; fail=1; } || echo "  ok   empty list -> nothing off"

echo "=== the old weekends-only setting migrates once ==="
C=$(mktemp)
printf 'WEEKDAYS_ONLY=1\n' > "$C"
( CONFIG=$C; load_config; [ "$DAYS_OFF" = "6,7" ] ) && echo "  ok   WEEKDAYS_ONLY=1 -> DAYS_OFF=6,7" || { echo "  FAIL migration"; fail=1; }
printf 'WEEKDAYS_ONLY=1\nDAYS_OFF="3"\n' > "$C"
( CONFIG=$C; load_config; [ "$DAYS_OFF" = "3" ] ) && echo "  ok   an explicit DAYS_OFF wins over the old key" || { echo "  FAIL migration overrode DAYS_OFF"; fail=1; }
printf 'DAYS_OFF="9,banana"\n' > "$C"
( CONFIG=$C; load_config; [ -z "$DAYS_OFF" ] ) && echo "  ok   junk DAYS_OFF rejected" || { echo "  FAIL junk accepted"; fail=1; }
rm -f "$C"

echo "=== pause for today ==="
load_config; SCHEDULE_ENABLED=0
touch "$MANUAL_FLAG"
is_active && echo "  ok   manual switch activates" || { echo "  FAIL manual switch"; fail=1; }
pause_today
is_active && { echo "  FAIL pause did not block"; fail=1; } || echo "  ok   pause blocks it"
echo "1999-01-01" > "$PAUSE_FILE"
is_active && echo "  ok   yesterday's pause is ignored" || { echo "  FAIL stale pause still blocking"; fail=1; }
resume
is_active && echo "  ok   resume restores it" || { echo "  FAIL resume"; fail=1; }
rm -f "$MANUAL_FLAG"

echo "=== stats ==="
record_stat taken; record_stat taken; record_stat snoozed; record_stat skipped
printf '1999-01-01\ttaken\n' >> "$STATS_FILE"
ck "taken today"   "$(stat_today taken)"   2
ck "snoozed today" "$(stat_today snoozed)" 1
ck "unseen event"  "$(stat_today back)"    0
ck "summary"       "$(stats_summary)"      "Today: 2 taken, 1 snoozed, 1 skipped"
( STATS_FILE=/nonexistent/x.tsv; [ "$(stat_today taken)" = "0" ] ) && echo "  ok   missing stats file -> 0" || { echo "  FAIL missing stats file"; fail=1; }

echo "=== away detection (must not be fooled by the 64 in uint64) ==="
idle() { eval "gdbus() { echo '$1'; }"; local g; g=$(idle_sec); unset -f gdbus; ck "$2" "$g" "$3"; }
idle "(uint64 44793,)"   "44793 ms -> 44 s"  44
idle "(uint64 300000,)"  "5 min idle"        300
idle "(uint64 3600000,)" "1 hour idle"       3600
idle "(uint64 0,)"       "0 ms"              0
idle "garbage"           "unparseable -> 0"  0
eval "gdbus() { echo '(uint64 400000,)'; }"
IDLE_SKIP=1; IDLE_SEC=300; user_is_away && echo "  ok   400s idle >= 300s -> away" || { echo "  FAIL"; fail=1; }
IDLE_SEC=600; user_is_away && { echo "  FAIL 400s should not exceed 600s"; fail=1; } || echo "  ok   400s idle < 600s -> present"
IDLE_SKIP=0; IDLE_SEC=0; user_is_away && { echo "  FAIL off switch ignored"; fail=1; } || echo "  ok   IDLE_SKIP=0 disables the check"
unset -f gdbus

echo "=== sound helpers ==="
SOUND=/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga
[ -n "$(player_cmd)" ] && echo "  ok   player resolved: $(player_cmd)" || { echo "  FAIL no player"; fail=1; }
SOUND=/nonexistent/nope.oga
play_once && { echo "  FAIL played a missing file"; fail=1; } || echo "  ok   missing sound file fails cleanly"

exit $fail
