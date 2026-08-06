#!/usr/bin/env python3
"""Drive the real settings Window: live counter, Start/Stop, greying out."""
import importlib.util, os, shutil, sys, tempfile, time
from datetime import date

SB = tempfile.mkdtemp()
os.environ["XDG_RUNTIME_DIR"] = os.path.join(SB, "run")
os.environ["XDG_STATE_HOME"] = os.path.join(SB, "state")

spec = importlib.util.spec_from_file_location("st", "/home/mhmd1/alarm-app/settings.py")
st = importlib.util.module_from_spec(spec); spec.loader.exec_module(st)
from gi.repository import Gdk, Gtk

st.CONFIG = os.path.join(SB, "config")
st.STATE_DIR = os.path.join(SB, "state_dir"); os.makedirs(st.STATE_DIR)
st.MANUAL_FLAG = os.path.join(st.STATE_DIR, "manual_on")
st.PAUSE_FILE = os.path.join(st.STATE_DIR, "paused_on")
st.PHASE_FILE = os.path.join(st.STATE_DIR, "phase")
st.NEXT_EPOCH = os.path.join(st.STATE_DIR, "next_epoch")
st.DAEMON_PID = os.path.join(st.STATE_DIR, "daemon.pid")
st.STATS_FILE = os.path.join(SB, "stats.tsv")
st.AUTOSTART = os.path.join(SB, "autostart.desktop")

open(st.CONFIG, "w").write('''INTERVAL_MIN=30
SNOOZE_MIN=5
WALK_ENABLED=1
WALK_MIN=1
BUZZ_GAP_CAP_MIN=15
WARN_ENABLED=1
WARN_LEAD_MIN=2
IDLE_SKIP=1
IDLE_MIN=5
SCHEDULE_ENABLED=1
SCHEDULE_START="15:00"
SCHEDULE_END="23:00"
WEEKDAYS_ONLY=0
SOUND="/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga"
WALK_SOUND="/usr/share/sounds/freedesktop/stereo/complete.oga"
LOOP_SOUND=1
FULLSCREEN=1
''')

fake = {"running": True}
st.daemon_running = lambda: fake["running"]
st.Window._daemon = lambda self, action: None      # never touch a real daemon

fails = []
def ck(d, got, want):
    if got == want: print(f"  ok   {d} -> {got!r}")
    else: print(f"  FAIL {d} -> got {got!r} want {want!r}"); fails.append(d)

def clear_state():
    for p in (st.PHASE_FILE, st.NEXT_EPOCH, st.MANUAL_FLAG, st.PAUSE_FILE):
        if os.path.exists(p): os.remove(p)

provider = Gtk.CssProvider(); provider.load_from_data(st.CSS)
Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                         Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
clear_state()
w = st.Window()
w.show_all(); w._sync_sensitivity()

print("=== settings loaded from the config file ===")
ck("interval", w.sp_interval.get_value(), 30.0)
ck("walk length", w.sp_walk.get_value(), 1.0)
ck("nag cap", w.sp_cap.get_value(), 15.0)
ck("idle minutes", w.sp_idle.get_value(), 5.0)
ck("schedule on", w.cb_sched.get_active(), True)
ck("schedule start", w.e_start.get_text(), "15:00")
ck("weekdays off", w.cb_weekdays.get_active(), False)

print("=== status: stopped daemon ===")
fake["running"] = False; w.refresh_status()
ck("status", w.lbl_status.get_text(), "Not running")
ck("counter", w.lbl_counter.get_text(), "—")
ck("button offers Start", w.btn_go.get_label(), "Start reminders")

print("=== status: idle, schedule configured ===")
fake["running"] = True; clear_state(); w.refresh_status()
ck("status", w.lbl_status.get_text(), "Off")
ck("detail mentions the schedule", "15:00 to 23:00" in w.lbl_detail.get_text(), True)
ck("button offers Start", w.btn_go.get_label(), "Start reminders")

print("=== status: running with a live countdown ===")
open(st.PHASE_FILE, "w").write("work")
open(st.NEXT_EPOCH, "w").write(str(int(time.time()) + 754))   # 12:34
w.refresh_status()
ck("status", w.lbl_status.get_text(), "Running")
ck("detail", w.lbl_detail.get_text(), "Next break in")
ck("counter shows a countdown", w.lbl_counter.get_text() in ("12m 34s", "12m 33s"), True)
ck("button offers Stop", w.btn_go.get_label(), "Stop reminders")

print("=== the counter actually ticks ===")
first = w.lbl_counter.get_text()
time.sleep(2.1); w.refresh_status()
second = w.lbl_counter.get_text()
ck(f"counter advanced ({first} -> {second})", first != second, True)

print("=== status: during the walk ===")
open(st.PHASE_FILE, "w").write("walk")
open(st.NEXT_EPOCH, "w").write(str(int(time.time()) + 45))
w.refresh_status()
ck("detail", w.lbl_detail.get_text(), "Walk ends in")
ck("counter", w.lbl_counter.get_text() in ("45s", "44s"), True)

print("=== status: alert on screen ===")
open(st.PHASE_FILE, "w").write("alert")
os.remove(st.NEXT_EPOCH)
w.refresh_status()
ck("status", w.lbl_status.get_text(), "Alert on screen")
ck("counter", w.lbl_counter.get_text(), "—")

print("=== status: paused for today ===")
clear_state()
open(st.PAUSE_FILE, "w").write(date.today().isoformat())
w.refresh_status()
ck("status", w.lbl_status.get_text(), "Off for the rest of today")
clear_state()

print("=== Start / Stop button ===")
w.refresh_status()
w.on_toggle_running(None)
ck("Start creates the manual flag", os.path.exists(st.MANUAL_FLAG), True)
ck("Start clears any pause", os.path.exists(st.PAUSE_FILE), False)
open(st.PHASE_FILE, "w").write("work")          # daemon would publish this
w.refresh_status()
ck("now offers Stop", w.btn_go.get_label(), "Stop reminders")
w.on_toggle_running(None)
ck("Stop clears the manual flag", os.path.exists(st.MANUAL_FLAG), False)
ck("Stop pauses today (schedule is on)", st.paused_today(), True)

print("=== Start also saves what is on screen ===")
clear_state()
w.sp_interval.set_value(12.5)
w.cb_weekdays.set_active(True)
w.on_toggle_running(None)
c = st.read_config()
ck("interval saved", c["INTERVAL_MIN"], "12.5")
ck("weekdays saved", c["WEEKDAYS_ONLY"], "1")

print("=== dependent fields grey out ===")
w.cb_walk.set_active(False); w._sync_sensitivity()
ck("walk length disabled", w.row_walk.get_sensitive(), False)
ck("nag cap disabled", w.row_cap.get_sensitive(), False)
w.cb_walk.set_active(True); w._sync_sensitivity()
ck("walk length enabled", w.row_walk.get_sensitive(), True)
w.cb_sched.set_active(False); w._sync_sensitivity()
ck("schedule times disabled", w.row_times.get_sensitive(), False)
ck("weekdays disabled", w.cb_weekdays.get_sensitive(), False)
w.cb_idle.set_active(False); w._sync_sensitivity()
ck("idle minutes disabled", w.row_idle.get_sensitive(), False)
w.cb_warn.set_active(False); w._sync_sensitivity()
ck("warn lead disabled", w.row_warn.get_sensitive(), False)

print("=== a bad schedule time is rejected, not written ===")
w.cb_sched.set_active(True)
w.e_start.set_text("25:99")
st.Window._error = lambda self, t: print("   (dialog suppressed:", t.split('\n')[0], ")")
w._save()
c = st.read_config()
ck("bad start time not saved", c["SCHEDULE_START"], "15:00")
w.e_start.set_text("07:45"); w._save()
ck("good start time saved", st.read_config()["SCHEDULE_START"], "07:45")

shutil.rmtree(SB, ignore_errors=True)
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
