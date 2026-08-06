#!/usr/bin/env python3
"""Drive the real settings window: tabs, responsive columns, the live counter,
the Start/Stop button, saving, and the alert wording."""
import importlib.util, os, shutil, sys, tempfile, time
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
SB = tempfile.mkdtemp()
os.environ["XDG_RUNTIME_DIR"] = os.path.join(SB, "run")
os.environ["XDG_STATE_HOME"] = os.path.join(SB, "state")

spec = importlib.util.spec_from_file_location("st", os.path.join(APP, "settings.py"))
st = importlib.util.module_from_spec(spec); spec.loader.exec_module(st)
from gi.repository import Gdk, GLib, Gtk

st.CONFIG = os.path.join(SB, "config")
st.STATE_DIR = os.path.join(SB, "state_dir"); os.makedirs(st.STATE_DIR)
st.MANUAL_FLAG = os.path.join(st.STATE_DIR, "manual_on")
st.PAUSE_FILE = os.path.join(st.STATE_DIR, "paused_on")
st.PHASE_FILE = os.path.join(st.STATE_DIR, "phase")
st.NEXT_EPOCH = os.path.join(st.STATE_DIR, "next_epoch")
st.DAEMON_PID = os.path.join(st.STATE_DIR, "daemon.pid")
st.STATS_FILE = os.path.join(SB, "stats.tsv")
st.AUTOSTART = os.path.join(SB, "autostart.desktop")

open(st.CONFIG, "w").write("""INTERVAL_MIN=30
SNOOZE_MIN=5
WALK_ENABLED=1
WALK_MIN=1
BUZZ_GAP_CAP_MIN=15
WARN_ENABLED=1
WARN_LEAD_MIN=2
IDLE_SKIP=1
IDLE_MIN=5
SCHEDULE_ENABLED=1
SCHEDULE_START='15:00'
SCHEDULE_END='23:00'
DAYS_OFF=''
SOUND='/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga'
WALK_SOUND='/usr/share/sounds/freedesktop/stereo/complete.oga'
LOOP_SOUND=1
FULLSCREEN=1
""")

fake = {"running": True}
st.daemon_running = lambda: fake["running"]
st.Window._daemon = lambda self, action: None       # never touch a real daemon

fails = []
def ck(d, got, want):
    if got == want: print(f"  ok   {d} -> {got!r}")
    else: print(f"  FAIL {d} -> got {got!r} want {want!r}"); fails.append(d)

def clear_state():
    for p in (st.PHASE_FILE, st.NEXT_EPOCH, st.MANUAL_FLAG, st.PAUSE_FILE):
        if os.path.exists(p): os.remove(p)

prov = Gtk.CssProvider(); prov.load_from_data(st.CSS)
Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                         Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
clear_state()
w = st.Window()
w.show_all(); w._sync_sensitivity()

print("=== settings loaded from the config file ===")
ck("interval", w.sp_interval.get_value(), 30.0)
ck("break length", w.sp_walk.get_value(), 1.0)
ck("nag cap", w.sp_cap.get_value(), 15.0)
ck("idle minutes", w.sp_idle.get_value(), 5.0)
ck("schedule on", w.cb_sched.get_active(), True)
ck("schedule start", w.e_start.get_text(), "15:00")
ck("no days off", [i for i, t in w.day_toggles if t.get_active()], [])

print("=== tabs ===")
ck("five tabs", [t["name"] for t in w.tabs],
   ["Timing", "When it runs", "Alerts", "Stats", "Guide"])
ck("every group landed in a tab", sum(len(t["sections"]) for t in w.tabs), len(w.sections))
for name, n in (("Timing", 3), ("When it runs", 3), ("Alerts", 3),
                ("Stats", 3), ("Guide", 5)):
    got = [len(t["sections"]) for t in w.tabs if t["name"] == name][0]
    ck(f"{name} holds {n} groups", got, n)
for t in w.tabs:
    w.stack.set_visible_child(t["scroller"])
    ck(f"can show {t['name']}", w.stack.get_visible_child(), t["scroller"])

print("=== status ===")
fake["running"] = False; clear_state(); w._pending = None; w.refresh_status()
ck("stopped", w.lbl_status.get_text(), "Not running")
ck("stopped counter", w.lbl_counter.get_text(), "—")
ck("offers Start", w.btn_go.get_label(), "Start reminders")
fake["running"] = True; w.refresh_status()
ck("idle", w.lbl_status.get_text(), "Off")
ck("detail mentions the schedule", "15:00 to 23:00" in w.lbl_detail.get_text(), True)
open(st.PHASE_FILE, "w").write("work")
open(st.NEXT_EPOCH, "w").write(str(int(time.time()) + 754))
w.refresh_status()
ck("running", w.lbl_status.get_text(), "Running")
ck("counter counts down", w.lbl_counter.get_text() in ("12m 34s", "12m 33s"), True)
ck("offers Stop", w.btn_go.get_label(), "Stop reminders")
ck("tooltip carries the wording", w.lbl_counter.get_tooltip_text(), "Running — next break in")
first = w.lbl_counter.get_text(); time.sleep(2.1); w.refresh_status()
ck(f"counter ticks ({first} -> {w.lbl_counter.get_text()})", first != w.lbl_counter.get_text(), True)
open(st.PHASE_FILE, "w").write("walk")
open(st.NEXT_EPOCH, "w").write(str(int(time.time()) + 45)); w.refresh_status()
ck("during the walk", w.lbl_detail.get_text(), "walk ends in")
open(st.PHASE_FILE, "w").write("alert"); os.remove(st.NEXT_EPOCH); w.refresh_status()
ck("alert on screen", w.lbl_status.get_text(), "Alert on screen")
clear_state(); open(st.PAUSE_FILE, "w").write(date.today().isoformat()); w.refresh_status()
ck("paused for today", w.lbl_status.get_text(), "Off for today")
clear_state(); w._pending = None; w.refresh_status()

print("=== the button answers at once, without waiting for the daemon ===")
w.on_toggle_running(None)
ck("flips immediately", w.btn_go.get_label(), "Stop reminders")
ck("says what it is doing", w.lbl_status.get_text(), "Starting")
ck("manual flag written", os.path.exists(st.MANUAL_FLAG), True)
open(st.PHASE_FILE, "w").write("work"); w.refresh_status()
ck("guess cleared once confirmed", w._pending, None)
w.on_toggle_running(None)
ck("flips back", w.btn_go.get_label(), "Start reminders")
clear_state(); w.refresh_status()
ck("cleared once the daemon agrees", w._pending, None)
w._pending = (True, time.time() - 1); w.refresh_status()
ck("an expired guess is dropped", w._pending, None)
ck("and the truth shown", w.btn_go.get_label(), "Start reminders")

print("=== Start saves the on-screen values, Stop need not ===")
clear_state(); w._save(); w.sp_interval.set_value(26)
w.on_toggle_running(None)
ck("Start wrote what was on screen", st.read_config()["INTERVAL_MIN"], "26")
open(st.PHASE_FILE, "w").write("work"); w.refresh_status()
w.sp_interval.set_value(27); w.on_toggle_running(None)
ck("Stop left the unsaved edit alone", st.read_config()["INTERVAL_MIN"], "26")
ck("and still flags it unsaved", w._dirty, True)
clear_state(); w._pending = None; w._save()

print("=== days off round-trip ===")
for chosen in ([], [5], [6, 7], [1, 3, 5], [1, 2, 3, 4, 5, 6, 7]):
    for i, t in w.day_toggles:
        t.set_active(i in chosen)
    ck(f"days {chosen}", w._values()["DAYS_OFF"], ",".join(str(i) for i in chosen))
for i, t in w.day_toggles:
    t.set_active(False)

print("=== the alert wording is editable ===")
w.e_break_title.set_text("Oi, up you get")
w.tv_break_msg.get_buffer().set_text("Stretch.\nThen walk.")
v = w._values()
ck("break heading", v["BREAK_TITLE"], "Oi, up you get")
ck("newline stored as an escape", v["BREAK_MESSAGE"], "Stretch.\\nThen walk.")
w._save()
ck("saved", st.read_config()["BREAK_TITLE"], "Oi, up you get")
w.e_break_title.set_text("   "); w.e_walk_title.set_text(""); w._save()
ck("blank heading falls back", st.read_config()["BREAK_TITLE"], "Take a break!")
ck("blank walk heading falls back", st.read_config()["WALK_TITLE"], "Walk time is up")

print("=== label above field, field fills the width ===")
for name, g in (("break length", w.row_walk), ("nag cap", w.row_cap),
                ("warn lead", w.row_warn), ("idle", w.row_idle),
                ("schedule times", w.row_times), ("days off", w.row_days)):
    kids = g.get_children()
    stacked = (g.get_orientation() == Gtk.Orientation.VERTICAL
               and isinstance(kids[0], Gtk.Label) and kids[0].get_text() != "")
    ck(f"{name}: label stacked above", stacked, True)
ck("spin fields expand", w.sp_interval.get_hexpand(), True)
ck("time fields expand", w.e_start.get_hexpand(), True)
ck("sound chooser expands", w.fc_sound.get_hexpand(), True)

print("=== saving says so ===")
w._set_dirty(False); w._message("")
ck("quiet to begin with", w.lbl_saved.get_text(), "")
w.sp_interval.set_value(23)
ck("an edit is announced", w.lbl_saved.get_text(), "Unsaved changes")
ck("in the warning style", w.lbl_saved.get_style_context().has_class("msg-dirty"), True)
w._save()
ck("saving confirms", w.lbl_saved.get_text().startswith("✓ Saved at"), True)
ck("in the success style", w.lbl_saved.get_style_context().has_class("msg-ok"), True)
ck("no longer dirty", w._dirty, False)

print("=== save and close, and closing with unsaved edits ===")
closed = {"n": 0}
real_quit = Gtk.main_quit
st.Gtk.main_quit = lambda *a: closed.__setitem__("n", closed["n"] + 1)
w.sp_interval.set_value(19); w.on_save_close(None)
ck("saved before closing", st.read_config()["INTERVAL_MIN"], "19")
ck("and closed", closed["n"], 1)
w.e_start.set_text("99:99")
st.Window._error = lambda self, t: None
w.on_save_close(None)
ck("a bad value keeps the window open", closed["n"], 1)
w.e_start.set_text("15:00"); w._save(); closed["n"] = 0
w.sp_interval.set_value(21)
st.Gtk.MessageDialog.run = lambda self: Gtk.ResponseType.CANCEL
w.on_close(None)
ck("Back keeps it open", closed["n"], 0)
st.Gtk.MessageDialog.run = lambda self: Gtk.ResponseType.CLOSE
w.on_close(None)
ck("Discard closes without saving", (closed["n"], st.read_config()["INTERVAL_MIN"]), (1, "19"))
w.sp_interval.set_value(17)
st.Gtk.MessageDialog.run = lambda self: Gtk.ResponseType.OK
w.on_close(None)
ck("Save and close writes then closes",
   (closed["n"], st.read_config()["INTERVAL_MIN"]), (2, "17"))
st.Gtk.main_quit = real_quit

print("=== stats tab ===")
open(st.STATS_FILE, "w").write("".join(
    f"{(date.today() - timedelta(days=d)).isoformat()}\t{ev}\n"
    for d, evs in ((0, ["taken", "taken", "snoozed"]), (1, ["taken"]), (3, ["skipped"]))
    for ev in evs))
w._stats_stamp = None; w._refresh_stats_if_changed()
ck("chart got 7 rows", len(w.chart.rows), 7)
ck("last row is today", w.chart.rows[-1][0], date.today().isoformat())
ck("today's counts", w.chart.rows[-1][1], {"taken": 2, "snoozed": 1, "skipped": 0})
ck("totals mention 3 taken", "<b>3</b> taken" in w.lbl_totals.get_label(), True)

print("=== switching period must not change the width ===")
w._reflow(2)
stats_tab = [t for t in w.tabs if t["name"] == "Stats"][0]
measured = {}
for idx, days in ((0, 7), (1, 30)):
    w._period_btns[idx][1].set_active(True)
    while Gtk.events_pending():
        Gtk.main_iteration()
    measured[days] = (w.chart.get_preferred_width().minimum_width,
                      w.chart.get_preferred_height().minimum_height,
                      stats_tab["columns"].get_preferred_width().minimum_width,
                      len(w.chart.rows))
ck("chart width identical", measured[7][0], measured[30][0])
ck("tab width identical", measured[7][2], measured[30][2])
ck(f"tab minimum {measured[30][2]}px stays under 1000", measured[30][2] < 1000, True)
ck("a longer span grows downwards", measured[30][1] > measured[7][1], True)
ck("30 rows for 30 days", measured[30][3], 30)
w._period_btns[0][1].set_active(True)

print("=== clearing the history ===")
open(st.STATS_FILE, "w").write("2026-01-01\ttaken\n2026-01-01\ttaken\n")
st.Gtk.MessageDialog.run = lambda self: Gtk.ResponseType.OK
w.on_clear_stats(None)
ck("history emptied", os.path.getsize(st.STATS_FILE), 0)
ck("a backup was kept", os.path.exists(st.STATS_FILE + ".bak"), True)
st.Gtk.MessageDialog.run = lambda self: Gtk.ResponseType.CANCEL
open(st.STATS_FILE, "w").write("2026-01-01\ttaken\n")
w.on_clear_stats(None)
ck("cancel leaves it alone", open(st.STATS_FILE).read().count("taken"), 1)

print("=== every group is a card, and reflow loses none ===")
ck("all sections carry the card style",
   all(s.get_style_context().has_class("card") for s in w.sections), True)
for width, want in ((520, 1), (900, 1), (1000, 2), (1180, 2), (1500, 3), (1920, 3)):
    ck(f"{width}px", w._columns_for(width), want)
for n in (1, 2, 3, 1, 3, 2):
    w._reflow(n)
    for t in w.tabs:
        cols = t["columns"].get_children()
        ck(f"{n}col {t['name']}: all groups placed",
           sum(len(c.get_children()) for c in cols), len(t["sections"]))
        ck(f"{n}col {t['name']}: no empty column",
           len(cols), max(1, min(n, len(t["sections"]))))
w.cb_walk.set_active(False); w._reflow(1); w._reflow(2)
ck("greyed state survives a reflow", w.row_walk.get_sensitive(), False)
w.cb_walk.set_active(True); w._sync_sensitivity()
ck("live again", w.row_walk.get_sensitive(), True)

shutil.rmtree(SB, ignore_errors=True)
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
