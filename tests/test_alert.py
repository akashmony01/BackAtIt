#!/usr/bin/env python3
"""The alert window and its buzzer.

Run one case per process: several GTK main loops in a single process interfere
with each other and produce false failures.

    test_alert.py window | fullscreen | backoff | loop | once

The "window" case runs NOT fullscreen on purpose. A fullscreen alert sits over
whatever you are doing, and clicking it dismisses it — which ends the test
early and looks like a failure. Fullscreen is checked separately by the
"fullscreen" case, which measures the geometry and closes in about a second.
"""
import argparse, importlib.util, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("alertmod", os.path.join(HERE, "..", "alert.py"))
alertmod = importlib.util.module_from_spec(spec); spec.loader.exec_module(alertmod)
from gi.repository import Gdk, GLib, Gtk

case = sys.argv[1] if len(sys.argv) > 1 else "window"
fails = []
def ck(d, got, want):
    if got == want: print(f"  ok   {d} -> {got!r}")
    else: print(f"  FAIL {d} -> got {got!r} want {want!r}"); fails.append(d)

if case in ("window", "fullscreen"):
    args = argparse.Namespace(
        title="Take a break!", message="Have a little walk.", hint="click to dismiss",
        button=["I took my break!|0|primary", "Snooze 5 min|10|normal",
                "Turn off reminders|20|quiet"],
        default_code=0, grace=1, fullscreen=(case == "fullscreen"),
        sound="", player="true",
        buzz_mode="off", buzz_on=60, gap_start=120, gap_cap=900, sound_max=90)
    prov = Gtk.CssProvider(); prov.load_from_data(alertmod.CSS)
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                             Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    w = alertmod.Alert(args)
    st = {}

    def early():
        a = w.get_allocation()
        mon = Gdk.Display.get_default().get_monitor(0).get_geometry()
        st["size"] = f"{a.width}x{a.height}"
        st["monitor"] = f"{mon.width}x{mon.height}"
        st["grace"] = [b.get_sensitive() for b in w.buttons]
        st["focusable"] = [b.get_can_focus() for b in w.buttons]
        st["focus"] = w.get_focus()
        for name, kv in (("enter", Gdk.KEY_Return), ("space", Gdk.KEY_space),
                         ("esc", Gdk.KEY_Escape), ("letter", Gdk.KEY_a)):
            ev = Gdk.Event.new(Gdk.EventType.KEY_PRESS); ev.keyval = kv
            st["k_" + name] = bool(w.emit("key-press-event", ev))
        st["delete"] = bool(w.emit("delete-event", Gdk.Event.new(Gdk.EventType.DELETE)))
        return False

    def late():
        st["after"] = [b.get_sensitive() for b in w.buttons]
        st["hint"] = w.hint.get_text()
        w.buttons[2].emit("clicked")
        return False

    GLib.timeout_add(400, early)
    GLib.timeout_add(1800, late)
    code = w.run()

    if case == "fullscreen":
        ck("covers the whole monitor", st["size"], st["monitor"])
    else:
        ck("buttons inert during grace", st["grace"], [False] * 3)
        ck("no button can take focus", st["focusable"], [False] * 3)
        ck("nothing holds keyboard focus", st["focus"], None)
        for k in ("enter", "space", "esc", "letter"):
            ck(f"{k} keypress swallowed", st["k_" + k], True)
        ck("window cannot be closed by the WM", st["delete"], True)
        if "after" in st:
            ck("buttons live after grace", st["after"], [True] * 3)
            ck("hint restored after grace", st["hint"], "click to dismiss")
            ck("click returns that button's code", code, 20)
        else:
            print("  SKIP grace/click checks - the window was dismissed by hand")
else:
    loop = GLib.MainLoop(); marks = []; t0 = time.monotonic()
    mark = lambda: marks.append(round(time.monotonic() - t0, 1))
    if case == "backoff":
        bz = alertmod.Buzzer(["sleep"], "0.3", "backoff", 2, 2, 4, 90, on_buzz=mark); run = 18
    elif case == "loop":
        bz = alertmod.Buzzer(["sleep"], "0.2", "loop", 60, 120, 900, 3, on_buzz=mark); run = 7
    else:
        bz = alertmod.Buzzer(["sleep"], "1", "once", 60, 120, 900, 90, on_buzz=mark); run = 5
    bz.start()
    GLib.timeout_add_seconds(run, lambda: (loop.quit(), False)[1])
    loop.run()
    alive = bz.proc is not None and bz.proc.poll() is None
    bz.stop(); time.sleep(0.3)
    print(f"  bursts at {marks}")
    if case == "backoff":
        gaps = [round(marks[i + 1] - marks[i], 1) for i in range(len(marks) - 1)]
        print(f"  gaps {gaps} (expect roughly 4, 6, 6)")
        ck("at least 3 bursts", len(marks) >= 3, True)
        ck("silence grows after the first round", gaps[0] < gaps[1], True)
        if len(gaps) > 2:
            ck("silence settles at the cap", abs(gaps[1] - gaps[2]) <= 1.5, True)
    else:
        ck("exactly one burst", len(marks), 1)
        ck("not still playing", alive, False)
    ck("no player left behind", bz.proc, None)

print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
