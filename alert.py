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

Exit code = the code of the button that was clicked.
"""

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

CSS = b"""
.alert-bg      { background-color: #1b1b1f; }
.alert-title   { font-size: 40pt; font-weight: 800; color: #ffffff; }
.alert-body    { font-size: 17pt; color: #d7d7de; }
.alert-hint    { font-size: 12pt; color: #8b8b96; }
.alert-primary { font-size: 15pt; padding: 14px 34px; font-weight: 700; }
.alert-normal  { font-size: 14pt; padding: 12px 26px; }
.alert-quiet   { font-size: 11pt; padding: 6px 14px; color: #8b8b96; }
"""


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


class Alert(Gtk.Window):
    def __init__(self, args):
        super().__init__(title=args.title)
        self.result = args.default_code
        self.args = args
        self.buttons = []

        self.set_decorated(False)
        self.set_keep_above(True)
        self.stick()
        self.set_skip_taskbar_hint(False)
        if args.fullscreen:
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
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)
        box.set_margin_start(40)
        box.set_margin_end(40)

        title = Gtk.Label(label=args.title)
        title.get_style_context().add_class("alert-title")
        title.set_justify(Gtk.Justification.CENTER)
        box.pack_start(title, False, False, 0)

        body = Gtk.Label(label=args.message)
        body.get_style_context().add_class("alert-body")
        body.set_justify(Gtk.Justification.CENTER)
        body.set_line_wrap(True)
        body.set_line_wrap_mode(Pango.WrapMode.WORD)
        body.set_max_width_chars(52)
        box.pack_start(body, False, False, 0)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        row.set_halign(Gtk.Align.CENTER)
        row.set_margin_top(16)
        for spec in args.button:
            label, code, style = self._parse_button(spec)
            btn = Gtk.Button(label=label)
            btn.get_style_context().add_class(
                {"primary": "alert-primary", "quiet": "alert-quiet"}.get(style, "alert-normal")
            )
            # No widget may hold focus: that is what makes Space/Enter inert.
            btn.set_can_focus(False)
            btn.set_can_default(False)
            btn.set_sensitive(args.grace <= 0)
            btn.connect("clicked", self._on_click, code)
            self.buttons.append(btn)
            row.pack_start(btn, False, False, 0)
        box.pack_start(row, False, False, 0)

        self.hint = Gtk.Label(label="")
        self.hint.get_style_context().add_class("alert-hint")
        box.pack_start(self.hint, False, False, 0)

        self.add(box)

    @staticmethod
    def _parse_button(spec):
        """'Label|code|style' - style is optional."""
        parts = spec.split("|")
        label = parts[0]
        code = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        style = parts[2] if len(parts) > 2 else "normal"
        return label, code, style

    # -- behaviour ------------------------------------------------------
    def run(self):
        self.show_all()
        self.present()
        self.remaining = self.args.grace
        if self.remaining > 0:
            self._grace_tick()
            GLib.timeout_add_seconds(1, self._grace_tick)
        else:
            self.hint.set_text(self.args.hint)
        self.buzzer.start()
        Gtk.main()
        return self.result

    def _grace_tick(self):
        if self.remaining > 0:
            self.hint.set_text("buttons active in %d…" % self.remaining)
            self.remaining -= 1
            return True
        for btn in self.buttons:
            btn.set_sensitive(True)
        self.hint.set_text(self.args.hint)
        return False

    def _on_buzz(self):
        """Re-assert the window each time a new burst starts."""
        if self.get_window():
            self.set_keep_above(True)
            self.present()

    def _on_click(self, _btn, code):
        self.result = code
        self.buzzer.stop()
        Gtk.main_quit()


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
    args = p.parse_args()

    if not args.button:
        args.button = ["OK|0|primary"]
    # The config is one line per setting, so a line break is stored as the two
    # characters \n and turned back into a real one here.
    args.message = args.message.replace("\\n", "\n")
    args.title = args.title.replace("\\n", "\n")
    if args.buzz_mode == "off":
        args.sound = ""

    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )

    sys.exit(Alert(args).run())


if __name__ == "__main__":
    main()
