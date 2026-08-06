#!/usr/bin/env python3
"""settings.py pure logic: config round-trip, formatting, state reading."""
import importlib.util, os, shutil, subprocess, sys, tempfile
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
SB = tempfile.mkdtemp()
shutil.copy(os.path.join(APP, "lib.sh"), SB)
os.environ["XDG_RUNTIME_DIR"] = os.path.join(SB, "run")
os.environ["XDG_STATE_HOME"] = os.path.join(SB, "state")
os.makedirs(os.environ["XDG_RUNTIME_DIR"], exist_ok=True)

spec = importlib.util.spec_from_file_location("st", os.path.join(APP, "settings.py"))
st = importlib.util.module_from_spec(spec); spec.loader.exec_module(st)
st.CONFIG = os.path.join(SB, "config")
st.STATE_DIR = os.path.join(os.environ["XDG_RUNTIME_DIR"], "backatit")
os.makedirs(st.STATE_DIR, exist_ok=True)
st.PAUSE_FILE = os.path.join(st.STATE_DIR, "paused_on")
st.STATS_FILE = os.path.join(SB, "stats.tsv")

fails = []
def ck(d, got, want):
    if got == want: print(f"  ok   {d} -> {got}")
    else: print(f"  FAIL {d} -> got {got!r} want {want!r}"); fails.append(d)

print("=== the app identifies itself to the desktop ===")
ck("APP_ID", st.APP_ID, "backatit")
ck("config under XDG", st.CONFIG_DIR.endswith("/backatit"), True)

print("=== formatting ===")
ck("mmss 0", st.mmss(0), "0s")
ck("mmss 65", st.mmss(65), "1m 05s")
ck("mmss 1800", st.mmss(1800), "30m 00s")
ck("mmss 3725", st.mmss(3725), "1h 02m")
ck("mmss negative", st.mmss(-5), "0s")
ck("human 0.5", st.human_minutes(0.5), "30 seconds")
ck("human 1", st.human_minutes(1), "1 minute")
ck("human 30", st.human_minutes(30), "30 minutes")
ck("human 1.5", st.human_minutes(1.5), "1.5 minutes")

print("=== reading what lib.sh writes ===")
# Raw: the escaped apostrophe below must reach the file as backslash-quote,
# not be collapsed by python before it is written.
open(st.CONFIG, "w").write(r"""INTERVAL_MIN=30
SNOOZE_MIN=5
SOUND='/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga'
SCHEDULE_ENABLED=1
SCHEDULE_START='15:00'
BREAK_TITLE='it'\''s time'
""")
c = st.read_config()
ck("plain number", c["INTERVAL_MIN"], "30")
ck("quoted path", c["SOUND"], "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga")
ck("quoted time", c["SCHEDULE_START"], "15:00")
ck("escaped apostrophe", c["BREAK_TITLE"], "it's time")
ck("num() clamps", st.num({"X": "999"}, "X", 30), 240.0)
ck("num() comma decimal", st.num({"X": "0,5"}, "X", 30), 0.5)
ck("num() junk -> default", st.num({"X": "abc"}, "X", 7), 7.0)
ck("flag on", st.flag({"A": "1"}, "A"), True)
ck("flag off", st.flag({"A": "0"}, "A"), False)

print("=== write_config preserves comments and unknown keys ===")
open(st.CONFIG, "w").write("""# BackAtIt settings.

# --- timing ---
INTERVAL_MIN=30
SNOOZE_MIN=5

# --- advanced, not in the window ---
BUZZ_ON_MIN=1
CUSTOM_THING='leave me alone'
""")
st.write_config({"INTERVAL_MIN": 12.5, "SCHEDULE_START": "08:30", "WALK_ENABLED": 1})
after = open(st.CONFIG).read()
ck("comment kept", "# --- timing ---" in after, True)
ck("unmanaged key kept", "CUSTOM_THING='leave me alone'" in after, True)
ck("advanced key kept", "BUZZ_ON_MIN=1" in after, True)
ck("value updated in place", "INTERVAL_MIN=12.5" in after, True)
ck("old value gone", "INTERVAL_MIN=30" in after, False)
ck("new key appended", "WALK_ENABLED=1" in after, True)
ck("time single-quoted", "SCHEDULE_START='08:30'" in after, True)
ck("untouched key intact", "SNOOZE_MIN=5" in after, True)

print("=== bash reads back what python wrote ===")
st.write_config({
    "INTERVAL_MIN": 0.5, "SNOOZE_MIN": 2.5, "WALK_ENABLED": 0,
    "SCHEDULE_START": "09:00", "SCHEDULE_END": "18:00", "DAYS_OFF": "6,7",
    "SOUND": "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga",
    "WALK_SOUND": "/usr/share/sounds/freedesktop/stereo/complete.oga",
})
out = subprocess.run(
    ["bash", "-c",
     'CONFIG="$1"; . "$2/lib.sh"; CONFIG="$1"; load_config; '
     'echo "$INTERVAL_MIN|$INTERVAL_SEC|$SNOOZE_MIN|$SNOOZE_SEC|$WALK_ENABLED|$SCHEDULE_START|$DAYS_OFF"',
     "_", st.CONFIG, SB],
    capture_output=True, text=True)
ck("bash reads it cleanly", out.returncode, 0)
if out.stderr.strip(): print("   stderr:", out.stderr.strip())
ck("values survive", out.stdout.strip(), "0.5|30|2.5|150|0|09:00|6,7")

print("=== state reading ===")
ck("no pause file", st.paused_today(), False)
open(st.PAUSE_FILE, "w").write(date.today().isoformat())
ck("paused today", st.paused_today(), True)
open(st.PAUSE_FILE, "w").write("1999-01-01")
ck("stale pause ignored", st.paused_today(), False)
os.remove(st.PAUSE_FILE)

today = date.today().isoformat()
open(st.STATS_FILE, "w").write(
    f"{today}\ttaken\n{today}\ttaken\n{today}\tsnoozed\n1999-01-01\ttaken\n{today}\tturned_off\n")
ck("stats today", st.stats_today(), {"taken": 2, "snoozed": 1, "skipped": 0})
rows = st.stats_range(7)
ck("range length", len(rows), 7)
ck("range ends today", rows[-1][0], today)
ck("range oldest first", rows[0][0] < rows[-1][0], True)
st.STATS_FILE = "/nonexistent/x.tsv"
ck("missing stats file", st.stats_today(), {"taken": 0, "snoozed": 0, "skipped": 0})
ck("missing file still gives rows", len(st.stats_range(30)), 30)

ck("daemon_running with no pidfile", st.daemon_running(), False)

shutil.rmtree(SB, ignore_errors=True)
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
