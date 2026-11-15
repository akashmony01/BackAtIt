#!/usr/bin/env python3
"""The locked break: one window holding prompt -> countdown -> back-to-work.

Run one case per process: several GTK main loops in a single process interfere
with each other and produce false failures.

    test_lock.py plumbing | cycle | hold | walkoff | turnoff | snooze | plain

Every windowed case runs NOT fullscreen and with the input grab disabled. That
second part is not a detail: these tests run on your real desktop, and a seat
grab taken here would take your mouse and keyboard away for the duration of
the run. The grab is asserted on, never executed.
"""
import argparse, importlib.util, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("alertmod", os.path.join(HERE, "..", "alert.py"))
alertmod = importlib.util.module_from_spec(spec); spec.loader.exec_module(alertmod)
from gi.repository import Gdk, GLib, Gtk

case = sys.argv[1] if len(sys.argv) > 1 else "plumbing"
fails = []
def ck(d, got, want):
    if got == want: print(f"  ok   {d} -> {got!r}")
    else: print(f"  FAIL {d} -> got {got!r} want {want!r}"); fails.append(d)


def args_for(lock=True, walk_seconds=2, grace=0, hold_seconds=1):
    return argparse.Namespace(
        title="Take a break!", message="Have a little walk.",
        hint="the screen stays locked for the whole break",
        button=(["Snooze 5 min|10|normal", "Turn off reminders|20|quiet"] if lock else
                ["I took my break!|0|primary", "Snooze 5 min|10|normal",
                 "Turn off reminders|20|quiet"]),
        default_code=0, grace=grace, fullscreen=False,
        sound="", player="true",
        buzz_mode="off", buzz_on=60, gap_start=120, gap_cap=900, sound_max=90,
        lock=lock, all_monitors=False, no_grab=True,
        walk_seconds=walk_seconds,
        walk_title="Walk time is up", walk_message="Time to get back to work.",
        walk_hint="this keeps buzzing until you click", walk_sound="",
        # Exactly what lib.sh sends, "now" included: coming back is the one
        # button where waiting buys nothing.
        walk_button=["I'm back at work|0|primary|now",
                     "Turn off reminders|20|quiet"],
        hold_seconds=hold_seconds, release_margin=120)


def styled():
    prov = Gtk.CssProvider(); prov.load_from_data(alertmod.CSS)
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                             Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def press(widget, kind):
    widget.emit(kind, Gdk.Event.new(
        Gdk.EventType.BUTTON_PRESS if kind == "button-press-event"
        else Gdk.EventType.BUTTON_RELEASE))


# ---------------------------------------------------------------- no window
if case == "plumbing":
    ck("mmss under a minute", alertmod.mmss(9), "0:09")
    ck("mmss minutes", alertmod.mmss(272), "4:32")
    ck("mmss past an hour", alertmod.mmss(3725), "1:02:05")
    ck("mmss never goes negative", alertmod.mmss(-5), "0:00")

    # A caller that knows nothing about the lock must still work: this is what
    # keeps an added option from breaking every existing constructor.
    bare = argparse.Namespace()
    filled = alertmod.with_defaults(bare)
    ck("lock defaults off", filled.lock, False)
    ck("walk buttons default to a list", filled.walk_button, [])
    ck("hold defaults to 5 seconds", filled.hold_seconds, 5)

    lk = alertmod.Lock(60 + 120, enabled=False)
    ck("ceiling is break plus margin", lk.ceiling, 180)
    ck("disabled lock never takes", lk.take(None), False)
    lk.release(); ck("release is safe when never held", lk.held, False)
    lk.release(); ck("release is idempotent", lk.held, False)

    # Call the real Gdk.Seat.grab, on a window that is realized but never
    # shown. The server answers NOT_VIEWABLE, so the argument list is checked
    # against the installed PyGObject for real while there is no chance of the
    # input actually being taken away from whoever is running the suite.
    live = alertmod.Lock(30, enabled=True)
    hidden = Gtk.Window(); hidden.realize()
    ck("a grab on a hidden window is refused", live.take(hidden.get_window()), False)
    ck("a refused grab is not recorded as held", live.held, False)
    live.release(); ck("a refused grab releases cleanly", live.held, False)
    hidden.destroy()

    a = alertmod.Alert(args_for(walk_seconds=90))
    ck("alert sizes its own ceiling", a.lock.ceiling, 210)
    ck("no-grab disables the lock", a.lock.enabled, False)
    ck("starts in the prompt phase before it is run", a.phase, "prompt")
    ck("walk buttons built up front", len(a.walk_buttons), 2)
    ck("countdown hidden until the break starts", a.count_box.get_no_show_all(), True)
    ck("walk row hidden until the walk", a.walk_row.get_no_show_all(), True)

    # The grab waits for the map, and a refused one is retried while the
    # window is still becoming viewable (KWin maps later than Mutter does).
    # A stand-in lock: the real one would take the input of whoever runs this.
    class FakeLock:
        enabled = True; held = False; ceiling = 1
        def __init__(self, answers): self.answers = list(answers); self.calls = 0; self.last_status = None
        def take(self, _win):
            self.calls += 1
            ok, self.last_status = self.answers.pop(0) if self.answers else (False, "failed")
            self.held = ok
            return ok
        def release(self): self.held = False
    b = alertmod.Alert(args_for(walk_seconds=90))
    b.lock = FakeLock([(False, "not-viewable"), (True, "success")])
    ck("nothing grabbed before the map", b.lock.calls, 0)
    scheduled = []
    real_timeout = alertmod.GLib.timeout_add
    alertmod.GLib.timeout_add = lambda ms, fn, *a: scheduled.append(fn) or 0
    b._on_mapped(); b._on_mapped()
    ck("a second map does not start a second attempt", b._lock_tries, 0)
    b._take_lock()
    ck("a not-viewable refusal is retried", len(scheduled), 1)
    b._take_lock()
    ck("the retry takes the lock", b.lock.held, True)
    b._take_lock()
    ck("a held lock is not taken twice", b.lock.calls, 2)
    c = alertmod.Alert(args_for(walk_seconds=90))
    c.lock = FakeLock([(False, "already-grabbed")])
    del scheduled[:]
    c._take_lock()
    ck("other refusals give up at once", scheduled, [])
    d = alertmod.Alert(args_for(walk_seconds=90))
    d.lock = FakeLock([(True, "success")]); d.phase = "walk"
    d._take_lock()
    ck("no grab once the walk has handed the machine back", d.lock.calls, 0)
    e = alertmod.Alert(args_for(walk_seconds=90))
    e.lock = FakeLock([(False, "not-viewable")] * 50)
    del scheduled[:]
    for _ in range(50): e._take_lock()
    ck("retries stop at the cap", len(scheduled), e.LOCK_RETRIES - 1)
    alertmod.GLib.timeout_add = real_timeout

# ------------------------------------------------------------- with a window
else:
    styled()
    plain = (case == "plain")
    # The cases that end the break themselves get a long one, so a slow tick
    # under load cannot let the walk arrive first and cancel what they are
    # testing. Only the cases that wait for the walk keep it short.
    w = alertmod.Alert(args_for(lock=not plain,
                                walk_seconds=2 if case in ("cycle", "walkoff") else 30,
                                hold_seconds=1 if case == "hold" else 5))
    st = {}

    def early():
        """Just after run() - a locked window is already counting down."""
        st["phase"] = w.phase
        st["count_visible"] = w.count_box.get_visible()
        st["walk_visible"] = w.walk_row.get_visible()
        st["counter"] = w.lbl_count.get_text()
        st["progress"] = w.progress.get_fraction()
        st["accent_break"] = w.rule.get_style_context().has_class("accent-break")
        st["hold_visible"] = w.hold_cell.get_visible()
        st["title"] = w.lbl_title.get_text()
        # The hold bar must never wait: it is immune to a stray click by
        # design, so a grace period on it is friction with no purpose.
        st["hold_live"] = w.btn_hold.get_sensitive()
        st["quiet_graced"] = w.buttons[0] in w.graced if w.buttons else None
        st["button_labels"] = [b.get_label() for b in w.buttons]
        st["row_visible"] = w.row.get_visible()
        # Pretend the grab succeeded, so entering the walk has something real
        # to let go of and the release is observable rather than assumed.
        w.lock.held = True
        if plain:
            w.buttons[0].emit("clicked")          # I took my break!
        elif case == "hold":
            press(w.btn_hold, "button-press-event")
        elif case == "turnoff":
            w.buttons[1].emit("clicked")          # Turn off reminders
        elif case == "snooze":
            w.buttons[0].emit("clicked")          # Snooze
        return False

    def during_walk():
        st["phase_walk"] = w.phase
        st["lock_held"] = w.lock.held
        st["count_in_walk"] = w.count_box.get_visible()
        st["row_in_walk"] = w.row.get_visible()
        st["walk_row"] = w.walk_row.get_visible()
        st["title_walk"] = w.lbl_title.get_text()
        st["body_walk"] = w.lbl_body.get_text()
        st["active_is_walk"] = w.active_buttons is w.walk_buttons
        if case == "walkoff":
            w.walk_buttons[1].emit("clicked")     # Turn off reminders
        else:
            w.walk_buttons[0].emit("clicked")     # I'm back at work
        return False

    GLib.timeout_add(300, early)
    if case in ("cycle", "walkoff"):
        GLib.timeout_add(3200, during_walk)
    # Nothing should ever outlive this; without it a hung phase would sit here
    # until the suite's own timeout killed it with no useful output.
    GLib.timeout_add_seconds(20, lambda: (Gtk.main_quit(), False)[1])
    code = w.run()

    if plain:
        ck("ordinary alert keeps all three buttons", len(st["button_labels"]), 3)
        ck("ordinary alert still asks first", st["button_labels"][0], "I took my break!")
        ck("ordinary alert shows no countdown", st["count_visible"], False)
        ck("ordinary alert stays in the prompt phase", st["phase"], "prompt")
        ck("ordinary alert closes on the first click", code, 0)
    elif case == "hold":
        ck("locked window counts down from the start", st["phase"], "countdown")
        ck("holding the bar bypasses the break", code, alertmod.BYPASSED)
        ck("bypass is not a turn-off", code == alertmod.OFF_CUT_SHORT, False)
    elif case == "turnoff":
        ck("turning off during the break", code, alertmod.OFF_CUT_SHORT)
    elif case == "snooze":
        ck("snoozing out of a locked break", code, alertmod.SNOOZED)
        ck("snooze is not a bypass", code == alertmod.BYPASSED, False)
        ck("the break had already started", st["phase"], "countdown")
    else:
        ck("no prompt stage at all", st["phase"], "countdown")
        ck("break accent while getting up", st["accent_break"], True)
        ck("hold bar on screen", st["hold_visible"], True)
        ck("hold bar never waits out the grace", st["hold_live"], True)
        ck("turning off still does wait", st["quiet_graced"], True)
        ck("countdown up immediately", st["count_visible"], True)
        ck("no 'I took my break' button",
           any("took my break" in l for l in st["button_labels"]), False)
        ck("snooze is still offered", st["button_labels"],
           ["Snooze 5 min", "Turn off reminders"])
        ck("that button is on screen", st["row_visible"], True)
        ck("countdown says how long is left", st["counter"], "0:02")
        ck("progress bar starts empty", st["progress"], 0.0)
        ck("the accent says which screen this is",
           w.rule.get_style_context().has_class("accent-walk"), True)
        ck("break wording kept during the break", st["title"], "Take a break!")
        ck("walk begins on its own", st["phase_walk"], "walk")
        ck("input released when the walk is up", st["lock_held"], False)
        ck("countdown gone in the walk", st["count_in_walk"], False)
        ck("the break's own button gone too", st["row_in_walk"], False)
        ck("walk buttons shown", st["walk_row"], True)
        ck("hold bar gone in the walk", w.hold_cell.get_visible(), False)
        ck("'I'm back at work' is live at once",
           w.walk_buttons[0] in w.graced, False)
        ck("...but turning off still waits", w.walk_buttons[1] in w.graced, True)
        ck("walk wording swapped in", st["title_walk"], "Walk time is up")
        ck("walk message swapped in", st["body_walk"], "Time to get back to work.")
        ck("grace now guards the walk buttons", st["active_is_walk"], True)
        if case == "walkoff":
            ck("turning off after a full break is not 'cut short'",
               code, alertmod.OFF_AFTER_BREAK)
        else:
            ck("completing the cycle returns 0", code, alertmod.DONE)

print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
