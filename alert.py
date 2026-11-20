#!/usr/bin/env python3
"""The backatit alert window.

This replaces the old zenity/yad popup for two reasons:

  * yad's --fullscreen does not actually work on GNOME/Wayland here - it
    produced a small window instead of covering the screen.
  * yad has no way to ignore the keyboard, so a keystroke landing on the
    focused button dismissed the alarm the instant it appeared. That is the
    single most annoying failure mode, because it happens exactly when you
    are typing, which is exactly when you need the break.

So: keyboard input is swallowed entirely, no widget may take focus, and the
buttons stay insensitive for a short grace period with a visible countdown.
Only a deliberate mouse click gets through.

With --lock the window does not close when you answer it. It holds the whole
break in one process - prompt, then a live countdown, then the back-to-work
nag - so there is never a moment where the screen is free and you could just
sit back down. See the Lock class for what "locked" actually means and where
its limits are.

With --lock there is no "I took my break!" to press: the screen is already
locked, so waiting for a click before starting the clock is pure friction. The
window opens straight into the break countdown.

Exit codes:
     0  answered normally (with --lock, the whole cycle was completed)
    10  snoozed
    20  turned off during the break, which was therefore cut short
    21  unlocked early with the hold button; the break was cut short but
         reminders carry on as normal
    22  turned off once the break was over, so the break itself counts
"""

# Exit codes, named so the daemon's case arms and this file cannot drift.
DONE = 0
SNOOZED = 10
OFF_CUT_SHORT = 20
BYPASSED = 21
OFF_AFTER_BREAK = 22

import argparse
import shlex
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
# Pin these too: GTK 4 is installed as well, and without an explicit version
# its Gdk gets loaded first and the GTK 3 import then fails outright.
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

# Sizes are written for a 1080-tall screen and scaled from there, because a
# full-screen alert is exactly as tall as the monitor it lands on: a 62pt
# countdown that reads well on a desktop is most of a laptop panel. GTK 3 CSS
# has no media queries and no viewport units, so the scaling is done here and
# the sheet is generated once, before the window is shown - measuring the
# window afterwards would mean a visible resize every time an alert appears.
BASE_HEIGHT = 1080

CSS_TEMPLATE = """
/* Two screens, two accents: amber to get up, green to come back. From the
   other side of the room the colour arrives before the words do, which is the
   same reason the two alarm sounds are deliberately different. */

.alert-bg      { background-image: linear-gradient(160deg, #202027 0%%, #131317 100%%);
                 background-color: #17171c; }
.alert-title   { font-size: %(title)dpt; font-weight: 800; color: #ffffff; }
.alert-body    { font-size: %(body)dpt; color: #b4b4c0; }
.alert-hint    { font-size: %(hint)dpt; color: #76767f; }

/* Tabular figures, or the countdown jitters sideways every second. */
.alert-count   { font-size: %(count)dpt; font-weight: 800; color: #ffffff;
                 font-feature-settings: "tnum"; }

.alert-rule                 { border-radius: 2px; }
.alert-rule.accent-break    { background-color: #e5a50a; }
.alert-rule.accent-walk     { background-color: #2ec27e; }

/* Every button in a row shares a size and differs only in colour, so a row
   reads as one control rather than a jumble. background-image: none is not
   decoration - it strips the desktop theme's own button gradient, which
   otherwise sits on top of the accent colour. */
.alert-btn     { font-size: %(btn)dpt; font-weight: 600;
                 padding: %(pad_v)dpx %(pad_h)dpx;
                 border-radius: %(radius)dpx;
                 text-shadow: none; background-image: none;
                 /* Transparent rather than absent: the hold control has a
                    visible border, and without this it would stand 2px taller
                    than the button beside it in the same row. */
                 border: 1px solid transparent; }

.alert-primary.accent-break { background-color: #e5a50a; color: #291d00; }
.alert-primary.accent-walk  { background-color: #2ec27e; color: #04231a; }
.alert-primary              { font-weight: 700; }

.alert-normal  { background-color: alpha(#ffffff, 0.11); color: #e8e8ee; }
.alert-normal:hover { background-color: alpha(#ffffff, 0.17); }

/* Present enough to find, recessed enough that you do not drift into it. */
.alert-quiet   { background-color: alpha(#ffffff, 0.06); color: #9797a2; }
.alert-quiet:hover { background-color: alpha(#ffffff, 0.12); color: #d0d0d8; }

.alert-hold    { background-color: alpha(#ffffff, 0.06); color: #9797a2;
                 border: 1px solid alpha(#ffffff, 0.16); }
.alert-hold:hover { background-color: alpha(#ffffff, 0.12); color: #d0d0d8; }

.alert-progress trough   { min-height: %(prog_h)dpx; border-radius: %(prog_r)dpx;
                           border: none; background-color: alpha(#ffffff, 0.10); }
.alert-progress progress { min-height: %(prog_h)dpx; border-radius: %(prog_r)dpx;
                           border: none; background-color: #e5a50a; }

.alert-holdbar trough   { min-height: %(hold_h)dpx; border-radius: 2px;
                          border: none; background-color: alpha(#ffffff, 0.07); }
.alert-holdbar progress { min-height: %(hold_h)dpx; border-radius: 2px;
                          border: none; background-color: #9a9aa6; }
"""


def scale_for(height):
    """How much to shrink or grow everything, for a screen this tall.

    Clamped at both ends: below the floor the wording stops being readable
    across a room, and above the ceiling a very tall screen would blow the
    layout past its own edges.
    """
    return max(0.60, min(1.30, float(height or BASE_HEIGHT) / BASE_HEIGHT))


def css_for(height):
    k = scale_for(height)

    def s(value, floor):
        return max(floor, int(round(value * k)))

    return (CSS_TEMPLATE % {
        "title": s(40, 15), "count": s(62, 22), "body": s(16, 10),
        "hint": s(11, 8), "btn": s(13, 10),
        "pad_v": s(13, 6), "pad_h": s(26, 12), "radius": s(9, 4),
        "prog_h": s(9, 4), "prog_r": s(5, 2), "hold_h": s(4, 2),
    }).encode()


def target_height(args):
    """The height the alert is about to occupy.

    Full screen means the monitor it will open on; otherwise the window's own
    modest default, which wants the smaller end of the scale.
    """
    if not getattr(args, "fullscreen", False):
        return 640
    display = Gdk.Display.get_default()
    screen, count, primary = monitor_layout()
    if display is not None and count:
        return display.get_monitor(primary).get_geometry().height
    return BASE_HEIGHT


# The baseline sheet, for callers that do not scale (the tests build windows
# directly rather than going through main()).
CSS = css_for(BASE_HEIGHT)

# Options only main() knows about. The tests build an argparse.Namespace by
# hand rather than going through main(), so filling these in here keeps a new
# option from breaking every caller that does not know about it yet.
LOCK_DEFAULTS = {
    "lock": False, "all_monitors": False, "no_grab": False,
    "walk_seconds": 0, "walk_title": "", "walk_message": "", "walk_hint": "",
    "walk_sound": "", "walk_button": None,
    "hold_seconds": 5, "release_margin": 120,
}


def with_defaults(args):
    for key, val in LOCK_DEFAULTS.items():
        if not hasattr(args, key):
            setattr(args, key, [] if val is None else val)
    if args.walk_button is None:
        args.walk_button = []
    return args


def mmss(seconds):
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return "%d:%02d:%02d" % (h, m, s)
    return "%d:%02d" % (m, s)


class Buzzer:
    """Plays the alarm sound in a pattern, without ever blocking the UI.

    loop mode     - repeat until `max_sec`, then go quiet for good.
    backoff mode  - buzz for `on_sec`, fall silent for `gap`, buzz again, with
                    `gap` doubling each round up to `gap_cap`. Never gives up,
                    so it is still going when you come back to the desk.
    """

    def __init__(self, player, sound, mode, on_sec, gap_start, gap_cap, max_sec, on_buzz=None):
        self.player = player
        self.sound = sound
        self.mode = mode
        self.on_sec = max(1, on_sec)
        self.gap = max(1, gap_start)
        self.gap_cap = max(1, gap_cap)
        self.max_sec = max_sec
        self.on_buzz = on_buzz
        self.proc = None
        self.timers = set()
        self.elapsed = 0
        self.stopped = False

    # -- process helpers ------------------------------------------------
    def _spawn(self):
        if self.stopped or not self.sound:
            return
        try:
            self.proc = subprocess.Popen(
                self.player + [self.sound],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            self.proc = None

    def _kill(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except OSError:
                pass
        self.proc = None

    def _add(self, delay, fn, unit="s"):
        """Track the timer and forget it once it has fired for the last time,
        so stop() never tries to remove an id GLib has already reclaimed."""
        holder = {}

        def wrapper():
            keep = fn()
            if not keep:
                self.timers.discard(holder.get("id"))
            return keep

        tid = (GLib.timeout_add_seconds(delay, wrapper) if unit == "s"
               else GLib.timeout_add(delay, wrapper))
        holder["id"] = tid
        self.timers.add(tid)
        return tid

    # -- the pattern ----------------------------------------------------
    def start(self):
        if not self.sound:
            return
        self._begin_burst()

    def _begin_burst(self):
        if self.stopped:
            return False
        self.elapsed = 0
        if self.on_buzz:
            self.on_buzz()
        self._spawn()
        self._add(400, self._tick, unit="ms")
        return False

    def _tick(self):
        """Restart the clip when it ends, until this burst is over."""
        if self.stopped:
            return False
        if self.mode == "once":
            # Let the clip finish on its own; never repeat, never cut it short.
            if self.proc is None or self.proc.poll() is not None:
                self.proc = None
                return False
            return True
        self.elapsed += 0.4
        limit = self.max_sec if self.mode == "loop" else self.on_sec
        if self.elapsed >= limit:
            self._kill()
            if self.mode == "backoff":
                self._add(int(self.gap), self._begin_burst)
                self.gap = min(self.gap * 2, self.gap_cap)
            return False
        if self.proc is None or self.proc.poll() is not None:
            self._spawn()
        return True

    def stop(self):
        self.stopped = True
        for t in list(self.timers):
            GLib.source_remove(t)
        self.timers.clear()
        self._kill()


def monitor_layout():
    """(screen, monitor count, index of the primary) for the default display."""
    display = Gdk.Display.get_default()
    if display is None:
        return None, 0, 0
    screen = display.get_default_screen()
    count = display.get_n_monitors()
    primary = display.get_primary_monitor()
    index = 0
    if primary is not None:
        # Compare geometry rather than identity: get_monitor() hands back a
        # fresh wrapper each call, so `is` against get_primary_monitor() never
        # matches even when it is the same physical screen.
        want = primary.get_geometry()
        for i in range(count):
            got = display.get_monitor(i).get_geometry()
            if (got.x, got.y, got.width, got.height) == (want.x, want.y, want.width, want.height):
                index = i
                break
    return screen, count, index


class Blocker(Gtk.Window):
    """A plain dark window covering one of the *other* monitors.

    Deliberately blank. The alert itself says everything that needs saying,
    and repeating a 40pt heading across three screens is shouting.
    """

    def __init__(self, screen, monitor):
        super().__init__()
        self.set_decorated(False)
        self.set_keep_above(True)
        self.stick()
        self.set_skip_taskbar_hint(True)
        self.connect("delete-event", lambda *_: True)
        self.connect("key-press-event", lambda *_: True)
        self.connect("key-release-event", lambda *_: True)
        self.get_style_context().add_class("alert-bg")
        self.fullscreen_on_monitor(screen, monitor)
        self.show_all()
        self.present()


class Lock:
    """Exclusive claim on the mouse and keyboard, with its own way out.

    Covering the screen is not enough on its own: the desktop (GNOME, KDE,
    ...) handles Super and Alt-Tab before any application sees them, so a window that merely sits on
    top is one keypress away from being stepped around. Grabbing the seat
    takes those too.

    The safety timer is the point of this class. A grab held by a process that
    has wedged leaves the whole desktop with a dead keyboard and mouse, and the
    only way out is a text console. So the grab lets go on its own after a
    hard ceiling whatever else happens - the user-facing hold-to-unlock button
    only helps while this process is still answering, and a wedged one is not.
    """

    # owner_events=True: clicks on this app's own windows reach them as usual -
    # the Snooze and Turn off buttons and the hold-to-unlock bar - while every
    # click and key aimed anywhere else lands on the alert and goes nowhere.
    # With False, the windowing system hands EVERY event to the alert's
    # top-level window, so its own buttons (which sit in sub-windows of their
    # own) never saw a click and the locked break could not be snoozed,
    # turned off or unlocked at all.
    OWNER_EVENTS = True

    def __init__(self, ceiling_sec, enabled=True, seat=None):
        self._seat_override = seat      # tests pass a stand-in
        self.ceiling = max(1, int(ceiling_sec))
        self.enabled = enabled
        self.seat = None
        self.held = False
        self.last_status = None
        self._timer = None

    def take(self, gdk_window):
        if not self.enabled or self.held or gdk_window is None:
            return False
        seat = self._seat_override
        if seat is None:
            display = Gdk.Display.get_default()
            seat = display.get_default_seat() if display is not None else None
        if seat is None:
            return False
        try:
            status = seat.grab(gdk_window, Gdk.SeatCapabilities.ALL,
                               self.OWNER_EVENTS, None, None, None, None)
        except TypeError:
            # PyGObject builds disagree on whether the trailing user-data
            # argument is part of the signature.
            status = seat.grab(gdk_window, Gdk.SeatCapabilities.ALL,
                               self.OWNER_EVENTS, None, None, None)
        self.last_status = status.value_nick
        if status != Gdk.GrabStatus.SUCCESS:
            # Reported by the caller, which may still retry a not-viewable one.
            return False
        self.seat = seat
        self.held = True
        self._timer = GLib.timeout_add_seconds(self.ceiling, self._expire)
        return True

    def _expire(self):
        self._timer = None
        if self.held:
            print("backatit: safety timer released the input lock",
                  file=sys.stderr)
            self.release()
        return False

    def release(self):
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None
        if self.held and self.seat is not None:
            try:
                self.seat.ungrab()
            except Exception:
                pass
        self.held = False


class Alert(Gtk.Window):
    def __init__(self, args):
        args = with_defaults(args)
        super().__init__(title=args.title)
        self.result = args.default_code
        self.args = args
        self.buttons = []
        self.walk_buttons = []
        self.graced = []          # the buttons that wait out the grace period
        # Spacing and widths scale with the screen alongside the type; a fixed
        # 440px bar under a 22pt countdown looks wrong at both ends.
        self.k = scale_for(target_height(args))
        self.blockers = []
        self.phase = "prompt"
        self.walk_left = args.walk_seconds
        self._count_id = None
        self._hold_id = None
        self._hold_at = 0.0
        self._lock_started = False
        self._lock_tries = 0

        # The ceiling covers the whole locked stretch plus a margin, so a
        # slow-but-alive process is never cut loose early.
        self.lock = Lock(args.walk_seconds + args.release_margin,
                         enabled=args.lock and not args.no_grab)

        self.set_decorated(False)
        self.set_keep_above(True)
        self.stick()
        self.set_skip_taskbar_hint(False)
        screen, _count, primary = monitor_layout()
        if args.fullscreen:
            # Pin the content to the primary screen when the other monitors are
            # about to be blanked, or it may open on one of the blank ones.
            if args.lock and args.all_monitors and screen is not None:
                self.fullscreen_on_monitor(screen, primary)
            else:
                self.fullscreen()
        else:
            self.set_default_size(720, 420)
            self.set_position(Gtk.WindowPosition.CENTER_ALWAYS)

        # The window may not be closed by the window manager, only by a button.
        self.connect("delete-event", lambda *_: True)
        # Swallow every key. Nothing typed can reach a button, so the alarm
        # cannot be dismissed by carrying on typing.
        self.connect("key-press-event", lambda *_: True)
        self.connect("key-release-event", lambda *_: True)

        self._build(args)
        self.get_style_context().add_class("alert-bg")

        self.active_buttons = self.buttons
        self.active_hint = args.hint

        self.buzzer = Buzzer(
            player=shlex.split(args.player),
            sound=args.sound,
            mode=args.buzz_mode,
            on_sec=args.buzz_on,
            gap_start=args.gap_start,
            gap_cap=args.gap_cap,
            max_sec=args.sound_max,
            on_buzz=self._on_buzz,
        )

    # -- layout ---------------------------------------------------------
    def _build(self, args):
        """Heading, accent rule, then the time left as the largest thing on
        screen. The countdown is what you actually want from six feet away;
        the wording you have read a hundred times already."""
        def sp(value, floor=2):
            return max(floor, int(round(value * self.k)))

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)
        box.set_margin_start(sp(40)); box.set_margin_end(sp(40))

        self.lbl_title = Gtk.Label(label=args.title)
        self.lbl_title.get_style_context().add_class("alert-title")
        self.lbl_title.set_justify(Gtk.Justification.CENTER)
        self.lbl_title.set_line_wrap(True)
        self.lbl_title.set_max_width_chars(30)
        box.pack_start(self.lbl_title, False, False, 0)

        self.rule = Gtk.Box()
        self.rule.get_style_context().add_class("alert-rule")
        self.rule.set_halign(Gtk.Align.CENTER)
        self.rule.set_size_request(sp(76, 30), sp(4, 2))
        self.rule.set_margin_top(sp(18))
        box.pack_start(self.rule, False, False, 0)

        # Shown only while a locked break is running. set_no_show_all keeps
        # show_all() from ever revealing it in a plain alert.
        self.count_box = self._countdown_box(sp)
        self.count_box.set_no_show_all(True)
        box.pack_start(self.count_box, False, False, 0)

        self.lbl_body = Gtk.Label(label=args.message)
        self.lbl_body.get_style_context().add_class("alert-body")
        self.lbl_body.set_justify(Gtk.Justification.CENTER)
        self.lbl_body.set_line_wrap(True)
        self.lbl_body.set_line_wrap_mode(Pango.WrapMode.WORD)
        self.lbl_body.set_max_width_chars(52)
        self.lbl_body.set_margin_top(sp(24))
        box.pack_start(self.lbl_body, False, False, 0)

        self.row = self._button_row(args.button, self.buttons, args.grace, sp)
        self.row.set_margin_top(sp(30))
        # The way out rides in the same row as everything else, so the break
        # screen is one row of equal buttons rather than a stack of odds and
        # ends. It is hidden until a locked break actually starts.
        self.hold_cell = self._hold_cell(sp)
        self.hold_cell.set_no_show_all(True)
        self.row.pack_start(self.hold_cell, True, True, 0)
        box.pack_start(self.row, False, False, 0)

        self.walk_row = self._button_row(args.walk_button, self.walk_buttons,
                                         args.grace, sp)
        self.walk_row.set_no_show_all(True)
        self.walk_row.set_margin_top(sp(30))
        box.pack_start(self.walk_row, False, False, 0)

        self.hint = Gtk.Label(label="")
        self.hint.get_style_context().add_class("alert-hint")
        self.hint.set_margin_top(sp(24))
        box.pack_start(self.hint, False, False, 0)

        self.add(box)
        self._set_accent("break")

    def _set_accent(self, which):
        for widget in [self.rule] + self.buttons + self.walk_buttons:
            ctx = widget.get_style_context()
            ctx.remove_class("accent-break")
            ctx.remove_class("accent-walk")
        self.rule.get_style_context().add_class("accent-" + which)
        for btn in (self.walk_buttons if which == "walk" else self.buttons):
            if btn.get_style_context().has_class("alert-primary"):
                btn.get_style_context().add_class("accent-" + which)

    def _button_row(self, specs, into, grace, sp):
        """One row, every button the same size.

        Homogeneous, and each button sits in its own cell aligned to the top:
        the hold control carries a progress bar under it, and without the cells
        that extra height would shunt its neighbour out of line.
        """
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=sp(16))
        row.set_homogeneous(True)
        row.set_halign(Gtk.Align.CENTER)
        for spec in specs:
            label, code, style, instant = self._parse_button(spec)
            btn = Gtk.Button(label=label)
            ctx = btn.get_style_context()
            ctx.add_class("alert-btn")
            ctx.add_class({"primary": "alert-primary",
                           "quiet": "alert-quiet"}.get(style, "alert-normal"))
            # No widget may hold focus: that is what makes Space/Enter inert.
            btn.set_can_focus(False)
            btn.set_can_default(False)
            btn.set_sensitive(instant or grace <= 0)
            if not instant:
                self.graced.append(btn)
            btn.connect("clicked", self._on_click, code)
            into.append(btn)
            row.pack_start(self._cell(btn, sp), True, True, 0)
        return row

    @staticmethod
    def _cell(widget, sp):
        cell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=sp(6))
        cell.set_valign(Gtk.Align.START)
        widget.set_hexpand(True)
        cell.pack_start(widget, False, False, 0)
        return cell

    def _countdown_box(self, sp):
        """The time left, and a bar filling as the break is served. The bar is
        not decoration: it answers "nearly there or barely started" without
        making you read and subtract."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_halign(Gtk.Align.CENTER)
        box.set_margin_top(sp(28))

        self.lbl_count = Gtk.Label(label="")
        self.lbl_count.get_style_context().add_class("alert-count")
        box.pack_start(self.lbl_count, False, False, 0)

        self.progress = Gtk.ProgressBar()
        self.progress.get_style_context().add_class("alert-progress")
        self.progress.set_fraction(0.0)
        self.progress.set_size_request(sp(440, 180), -1)
        self.progress.set_halign(Gtk.Align.CENTER)
        self.progress.set_margin_top(sp(16))
        box.pack_start(self.progress, False, False, 0)
        return box

    def _hold_cell(self, sp):
        """The way out if you genuinely need the machine back."""
        self.btn_hold = Gtk.Button(
            label="Hold %ds to unlock" % self.args.hold_seconds)
        ctx = self.btn_hold.get_style_context()
        ctx.add_class("alert-btn")
        ctx.add_class("alert-hold")
        self.btn_hold.set_can_focus(False)
        self.btn_hold.set_can_default(False)
        # Press and release rather than "clicked": the whole point is that it
        # takes a sustained, deliberate hold, which a stray click is not. That
        # is also why it never waits out the grace period - it cannot be
        # triggered by accident in the first place.
        self.btn_hold.connect("button-press-event", self._hold_start)
        self.btn_hold.connect("button-release-event", self._hold_cancel)
        self.btn_hold.connect("leave-notify-event", self._hold_cancel)

        cell = self._cell(self.btn_hold, sp)
        self.hold_bar = Gtk.ProgressBar()
        self.hold_bar.get_style_context().add_class("alert-holdbar")
        self.hold_bar.set_fraction(0.0)
        cell.pack_start(self.hold_bar, False, False, 0)
        return cell

    @staticmethod
    def _parse_button(spec):
        """'Label|code|style|now' - style and the trailing 'now' are optional.

        The grace period guards against a mouse click already travelling when
        the alert appears; the keyboard is handled separately and completely,
        by swallowing it. So grace is worth having on a button that skips a
        break or ends the day, and is pure friction on one that only
        acknowledges a nag you were about to answer anyway. 'now' marks the
        latter kind, and it goes live the instant the alert does.
        """
        parts = spec.split("|")
        label = parts[0]
        code = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        style = parts[2] if len(parts) > 2 else "normal"
        instant = len(parts) > 3 and parts[3] == "now"
        return label, code, style, instant

    # -- behaviour ------------------------------------------------------
    def run(self):
        if self.args.lock:
            # Wait for the window to actually be on screen before grabbing.
            # Mutter has mapped it by the first idle tick after show(); KWin
            # has not, and a grab on an unmapped window is refused
            # (NOT_VIEWABLE) - which used to leave the whole locked break
            # running with no lock at all. Connected before show_all so the
            # map cannot slip past unobserved.
            self.connect("map-event", self._on_mapped)
        self.show_all()
        self.present()
        if self.args.lock and self.args.all_monitors:
            self._open_blockers()
        if self.args.lock:
            # Straight into the break. There is nothing to acknowledge: the
            # screen locked the moment this window appeared, so a button that
            # only starts the clock is friction with no purpose.
            self._enter_countdown()
        self._start_grace()
        self.buzzer.start()
        Gtk.main()
        self.lock.release()
        self._close_blockers()
        return self.result

    # A compositor can report the map a moment before the window is viewable
    # to the X server, so a refused grab is retried briefly before giving up.
    LOCK_RETRIES = 20
    LOCK_RETRY_MS = 100

    def _on_mapped(self, *_):
        if not self._lock_started:
            self._lock_started = True
            self._lock_tries = 0
            GLib.idle_add(self._take_lock)
        return False

    def _take_lock(self):
        # The walk stage hands the machine back, so a late map must not take
        # the lock again once the break is already over.
        if self.lock.held or self.phase == "walk":
            return False
        if self.lock.take(self.get_window()):
            print("backatit: input locked", file=sys.stderr)
            return False
        self._lock_tries += 1
        if (self.lock.enabled and self.lock.last_status == "not-viewable"
                and self._lock_tries < self.LOCK_RETRIES):
            GLib.timeout_add(self.LOCK_RETRY_MS, self._take_lock)
        elif self.lock.enabled:
            print("backatit: could not lock input (%s); the alert still covers "
                  "the screen" % self.lock.last_status, file=sys.stderr)
        return False

    def _open_blockers(self):
        screen, count, primary = monitor_layout()
        if screen is None:
            return
        for i in range(count):
            if i != primary:
                self.blockers.append(Blocker(screen, i))

    def _close_blockers(self):
        for win in self.blockers:
            win.destroy()
        self.blockers = []

    def _start_grace(self):
        """Only count down when something on screen is actually waiting."""
        self.remaining = self.args.grace
        waiting = [b for b in self.active_buttons if b in self.graced]
        if self.remaining > 0 and waiting:
            self._grace_tick()
            GLib.timeout_add_seconds(1, self._grace_tick)
        else:
            self.hint.set_text(self.active_hint)

    def _grace_tick(self):
        if self.remaining > 0:
            self.hint.set_text("buttons active in %d…" % self.remaining)
            self.remaining -= 1
            return True
        for btn in self.active_buttons:
            btn.set_sensitive(True)
        self.hint.set_text(self.active_hint)
        return False

    def _on_buzz(self):
        """Re-assert the window each time a new burst starts."""
        if self.get_window():
            self.set_keep_above(True)
            self.present()

    def _on_click(self, _btn, code):
        if self.args.lock and code == OFF_CUT_SHORT and self.phase == "walk":
            # By the walk stage the break has been served in full; only the
            # coming back was skipped, so it must not count as cut short.
            code = OFF_AFTER_BREAK
        self._finish(code)

    def _finish(self, code):
        self.result = code
        self.buzzer.stop()
        Gtk.main_quit()

    # -- the locked break -----------------------------------------------
    def _enter_countdown(self):
        """Begin the break itself.

        The alarm is left running: it stops on its own after --sound-max, which
        is deliberately short here. There is no click to silence it, and a
        one-minute break would otherwise be one minute of alarm.

        self.row is left showing too - under --lock it holds nothing but the
        quiet "Turn off reminders", which stays available throughout.
        """
        self.phase = "countdown"
        for widget in (self.count_box, self.hold_cell):
            widget.set_no_show_all(False)
            widget.show_all()
        self.walk_left = max(1, self.args.walk_seconds)
        self._count_tick()
        self._count_id = GLib.timeout_add_seconds(1, self._count_tick)

    def _count_tick(self):
        if self.phase != "countdown":
            self._count_id = None
            return False
        if self.walk_left <= 0:
            self._count_id = None
            self._enter_walk()
            return False
        self.lbl_count.set_text(mmss(self.walk_left))
        total = max(1, self.args.walk_seconds)
        self.progress.set_fraction(min(1.0, (total - self.walk_left) / total))
        self.walk_left -= 1
        return True

    def _enter_walk(self):
        """The walk is over. Let go of the machine, then start nagging.

        The lock exists to get you away from the desk, and that job is done
        the moment the countdown runs out - holding the mouse and keyboard
        hostage while it calls you back would keep the screen sealed for an
        open-ended stretch and buys nothing.
        """
        self.phase = "walk"
        self._hold_cancel()
        self.lock.release()
        self._close_blockers()

        self.count_box.hide()
        self.hold_cell.hide()
        self.row.hide()
        self._set_accent("walk")
        self.lbl_title.set_text(self.args.walk_title)
        self.lbl_body.set_text(self.args.walk_message)
        self.walk_row.set_no_show_all(False)
        self.walk_row.show_all()

        self.active_buttons = self.walk_buttons
        self.active_hint = self.args.walk_hint
        for btn in self.walk_buttons:
            btn.set_sensitive(btn not in self.graced or self.args.grace <= 0)

        self.buzzer = Buzzer(
            player=shlex.split(self.args.player),
            sound=self.args.walk_sound,
            mode="backoff",
            on_sec=self.args.buzz_on,
            gap_start=self.args.gap_start,
            gap_cap=self.args.gap_cap,
            max_sec=self.args.sound_max,
            on_buzz=self._on_buzz,
        )
        self._start_grace()
        self.buzzer.start()

    # -- hold to unlock --------------------------------------------------
    def _hold_start(self, *_):
        if self._hold_id is None:
            self._hold_at = 0.0
            self._hold_id = GLib.timeout_add(50, self._hold_tick)
        return False

    def _hold_cancel(self, *_):
        if self._hold_id is not None:
            GLib.source_remove(self._hold_id)
            self._hold_id = None
        self._hold_at = 0.0
        self.hold_bar.set_fraction(0.0)
        return False

    def _hold_tick(self):
        self._hold_at += 0.05 / max(0.5, float(self.args.hold_seconds))
        if self._hold_at >= 1.0:
            self.hold_bar.set_fraction(1.0)
            self._hold_id = None
            # Give the machine back and let the day carry on. This is for
            # needing your desk for five minutes, not for finishing early -
            # only "Turn off reminders" stops the next one from arriving.
            self._finish(BYPASSED)
            return False
        self.hold_bar.set_fraction(self._hold_at)
        return True


def main():
    # Same identity as the settings window, so the alert is recognised as this
    # application too rather than as a stray unnamed window.
    GLib.set_prgname("backatit")
    Gdk.set_program_class("BackAtIt")
    Gtk.Window.set_default_icon_name("backatit")

    p = argparse.ArgumentParser()
    p.add_argument("--title", default="Take a break!")
    p.add_argument("--message", default="")
    p.add_argument("--hint", default="")
    p.add_argument("--button", action="append", default=[],
                   help="Label|exitcode|style   (style: primary, normal, quiet)")
    p.add_argument("--default-code", type=int, default=0)
    p.add_argument("--grace", type=int, default=3,
                   help="seconds before the buttons become clickable")
    p.add_argument("--fullscreen", action="store_true")
    p.add_argument("--sound", default="")
    p.add_argument("--player", default="pw-play")
    p.add_argument("--buzz-mode", choices=("loop", "backoff", "once", "off"), default="loop")
    p.add_argument("--buzz-on", type=int, default=60)
    p.add_argument("--gap-start", type=int, default=120)
    p.add_argument("--gap-cap", type=int, default=900)
    p.add_argument("--sound-max", type=int, default=90)

    p.add_argument("--lock", action="store_true",
                   help="hold the whole break in this one window, and claim "
                        "the mouse and keyboard for its duration")
    p.add_argument("--all-monitors", action="store_true",
                   help="with --lock, blank every other monitor too")
    p.add_argument("--no-grab", action="store_true",
                   help="with --lock, do everything except claim input "
                        "(the tests run on a real desktop)")
    p.add_argument("--walk-seconds", type=int, default=0,
                   help="how long the locked break lasts")
    p.add_argument("--walk-title", default="Walk time is up")
    p.add_argument("--walk-message", default="")
    p.add_argument("--walk-hint", default="")
    p.add_argument("--walk-sound", default="")
    p.add_argument("--walk-button", action="append", default=[])
    p.add_argument("--hold-seconds", type=int, default=5,
                   help="how long the unlock button must be held down")
    p.add_argument("--release-margin", type=int, default=120,
                   help="how long past the end of the break the input lock "
                        "gives up on its own, if this process has wedged")
    args = p.parse_args()

    if not args.button:
        args.button = ["OK|0|primary"]
    if args.lock and not args.walk_button:
        args.walk_button = ["I'm back at work|0|primary"]
    # The config is one line per setting, so a line break is stored as the two
    # characters \n and turned back into a real one here.
    for field in ("message", "title", "walk_message", "walk_title"):
        setattr(args, field, getattr(args, field).replace("\\n", "\n"))
    if args.buzz_mode == "off":
        args.sound = ""

    provider = Gtk.CssProvider()
    provider.load_from_data(css_for(target_height(args)))
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )

    sys.exit(Alert(args).run())


if __name__ == "__main__":
    main()
