#!/usr/bin/env python3
"""BackAtIt — settings window.

Replaces the old yad form, which could not do three things this needs:
a counter that ticks while the window is open, section headings with an
explanation under each control, and dependent fields that grey themselves out
when the thing they belong to is switched off.

Whether the reminder is currently running is read from what the daemon
publishes in its state directory, not recomputed here — so there is only one
copy of the "is it active right now" logic, and it lives in the daemon.
"""

import os
import re
import subprocess
import sys
import time
from datetime import date, timedelta

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

# The name the desktop knows us by. It must match the .desktop filename and
# the installed icon name, or the dock cannot tie a running window back to the
# application and shows a generic icon instead.
APP_ID = "backatit"

APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Settings live in the standard per-user place rather than beside the program,
# which would be shared and read-only once this is installed system-wide.
CONFIG_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "backatit")
CONFIG = os.path.join(CONFIG_DIR, "config")
STATE_DIR = os.path.join(
    os.environ.get("XDG_RUNTIME_DIR", "/tmp/backatit-%d" % os.getuid()), "backatit"
)
STATS_FILE = os.path.join(
    os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")),
    "backatit", "stats.tsv",
)
AUTOSTART = os.path.expanduser("~/.config/autostart/backatit.desktop")


def about_info():
    """Who made this, from about.conf beside the program. Kept in one file so
    the About card, the LICENSE and the package metadata cannot disagree."""
    info = {"APP_NAME": "BackAtIt", "APP_VERSION": "1.0",
            "APP_AUTHOR": "", "APP_EMAIL": "", "APP_URL": "",
            "APP_LICENSE": "MIT"}
    try:
        with open(os.path.join(APP_DIR, "about.conf")) as fh:
            for line in fh:
                m = re.match(r'^\s*([A-Z_]+)="?([^"\n]*)"?\s*$', line)
                if m and m.group(1) in info:
                    info[m.group(1)] = m.group(2)
    except OSError:
        pass
    return info

MANUAL_FLAG = os.path.join(STATE_DIR, "manual_on")
PAUSE_FILE = os.path.join(STATE_DIR, "paused_on")
DAEMON_PID = os.path.join(STATE_DIR, "daemon.pid")
NEXT_EPOCH = os.path.join(STATE_DIR, "next_epoch")
PHASE_FILE = os.path.join(STATE_DIR, "phase")

MIN_M, MAX_M = 0.5, 240.0

# Column layout. HELP_CHARS caps how wide the explanatory text asks to be,
# which is what decides how narrow a single column can get.
MAX_COLS = 3
COL_MIN = 460          # a column narrower than this starts to look cramped
COL_GAP = 20
HELP_CHARS = 46
LABEL_CHARS = 26

CSS = b"""
/* Every colour here is derived from the theme's own foreground colour rather
   than hard-coded, so the window sits correctly in a light or a dark desktop
   theme without needing to know which one is in use. */

.topbar        { border-bottom: 1px solid alpha(currentColor, 0.10);
                 padding-bottom: 10px; }

.card          { background-color: alpha(currentColor, 0.035);
                 border: 1px solid alpha(currentColor, 0.10);
                 border-radius: 12px;
                 padding: 14px 16px;
                 box-shadow: 0 1px 2px rgba(0,0,0,0.05); }

.actionbar     { border-top: 1px solid alpha(currentColor, 0.10);
                 padding-top: 14px; }

.section       { font-size: 12pt; font-weight: 700; }
.status        { font-weight: 700; }
.counter       { font-size: 17pt; font-weight: 800;
                 font-feature-settings: "tnum"; }
.muted         { font-size: 10pt; opacity: 0.62; }
.go            { font-weight: 700; padding: 5px 16px; }


.guide-step    { padding: 2px 0; }
.chart-key     { font-size: 9pt; opacity: 0.75; }
.msg-ok        { color: #2ec27e; font-weight: 700; }
.msg-dirty     { color: #e5a50a; }
.app-name      { font-weight: 700; }
.bar-seg       { border-radius: 2px; }
.bar-track     { background-color: alpha(currentColor, 0.09);
                 border-radius: 3px; }
.bar-taken     { background-color: #2ec27e; }
.bar-snoozed   { background-color: #e5a50a; }
.bar-skipped   { background-color: alpha(currentColor, 0.30); }
"""


# ---------------------------------------------------------------- config file

def read_config():
    vals = {}
    try:
        with open(CONFIG) as fh:
            for line in fh:
                m = re.match(r"^\s*([A-Z_][A-Z0-9_]*)=(.*?)\s*$", line)
                if not m:
                    continue
                v = m.group(2)
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    quote = v[0]
                    v = v[1:-1]
                    if quote == "'":
                        v = v.replace("'\\''", "'")
                vals[m.group(1)] = v
    except OSError:
        pass
    return vals


def write_config(updates):
    """Update values in place, leaving comments and unknown keys untouched.

    The canonical file layout is written by save_config() in lib.sh; editing
    lines rather than regenerating the file means the two cannot drift apart.
    """
    try:
        with open(CONFIG) as fh:
            lines = fh.readlines()
    except OSError:
        lines = []

    def fmt(v):
        """Quote for a file that bash sources.

        Single quotes, not double: the alert messages are free text, and in
        double quotes something like $(...) or a backtick would be executed
        the moment the daemon read the config. Inside single quotes nothing
        is expanded, so an embedded quote is the only thing to escape.
        """
        if isinstance(v, float):
            return "%g" % v
        s = str(v)
        if re.fullmatch(r"[0-9]+(\.[0-9]+)?", s):
            return s
        return "'%s'" % s.replace("'", "'\\''")

    seen = set()
    for i, line in enumerate(lines):
        m = re.match(r"^\s*([A-Z_][A-Z0-9_]*)=", line)
        if m and m.group(1) in updates:
            key = m.group(1)
            lines[i] = "%s=%s\n" % (key, fmt(updates[key]))
            seen.add(key)
    for key, val in updates.items():
        if key not in seen:
            lines.append("%s=%s\n" % (key, fmt(val)))

    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    tmp = CONFIG + ".tmp"
    with open(tmp, "w") as fh:
        fh.writelines(lines)
    os.chmod(tmp, 0o600)      # your settings are nobody else's business
    os.replace(tmp, CONFIG)


def num(vals, key, default):
    try:
        v = float(str(vals.get(key, default)).replace(",", "."))
    except ValueError:
        return float(default)
    return min(max(v, MIN_M), MAX_M)


def flag(vals, key, default="1"):
    return str(vals.get(key, default)) == "1"


# ----------------------------------------------------------------- app state

def read(path):
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return ""


def daemon_running():
    pid = read(DAEMON_PID)
    if not pid.isdigit():
        return False
    try:
        with open("/proc/%s/cmdline" % pid, "rb") as fh:
            return b"alarmd.sh" in fh.read()
    except OSError:
        return False


def paused_today():
    return read(PAUSE_FILE) == date.today().isoformat()


def stats_today():
    counts = {"taken": 0, "snoozed": 0, "skipped": 0}
    today = date.today().isoformat()
    try:
        with open(STATS_FILE) as fh:
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) == 2 and parts[0] == today and parts[1] in counts:
                    counts[parts[1]] += 1
    except OSError:
        pass
    return counts


def mmss(seconds):
    """Units are spelled out: a bare "17:29" reads like a clock time, which is
    the opposite of what this number means."""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return "%dh %02dm" % (h, m)
    if m:
        return "%dm %02ds" % (m, s)
    return "%ds" % s


def human_minutes(m):
    if m < 1:
        return "%d seconds" % round(m * 60)
    if m == int(m):
        return "%d minute%s" % (int(m), "" if m == 1 else "s")
    return "%g minutes" % m


def stats_range(days):
    """Counts per day for the last `days` days, oldest first."""
    today = date.today()
    keys = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    data = {k: {"taken": 0, "snoozed": 0, "skipped": 0} for k in keys}
    try:
        with open(STATS_FILE) as fh:
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) == 2 and parts[0] in data and parts[1] in data[parts[0]]:
                    data[parts[0]][parts[1]] += 1
    except OSError:
        pass
    return [(k, data[k]) for k in keys]


SERIES = (("taken", "Taken", "bar-taken"),
          ("snoozed", "Snoozed", "bar-snoozed"),
          ("skipped", "Skipped", "bar-skipped"))


def swatch(css_class, size=11):
    box = Gtk.Box()
    box.get_style_context().add_class(css_class)
    box.get_style_context().add_class("bar-seg")
    box.set_size_request(size, size)
    box.set_valign(Gtk.Align.CENTER)
    return box


class BarChart(Gtk.Box):
    """One horizontal bar per day, stacked left to right.

    Horizontal on purpose: with vertical bars a 30-day span needed 30 columns
    of width, which pushed the whole window wider the moment you switched
    period. Laid out as rows, the width never changes — a longer span just
    grows downwards into the scroll area.

    Built from ordinary boxes with a CSS colour rather than drawn with cairo:
    PyGObject can only hand a cairo context to a draw handler when
    python3-gi-cairo is installed, and it is not here.
    """

    MIN_TRACK = 140          # keep a bar readable in a narrow column

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self.rows = []

    def set_rows(self, rows):
        for child in self.get_children():
            self.remove(child)
        self.rows = rows
        if not rows:
            return

        top = max(1, max(sum(c.values()) for _, c in rows))
        thick = 22 if len(rows) <= 10 else 15

        for day, counts in rows:
            d = date.fromisoformat(day)
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

            label = Gtk.Label(label=d.strftime("%a %d"), xalign=0)
            label.get_style_context().add_class("chart-key")
            label.set_width_chars(6)
            row.pack_start(label, False, False, 0)

            # A homogeneous grid one column per break: the segments then keep
            # their proportions while the whole track stretches to whatever
            # width the column has. Fixed pixel widths could not do both.
            track = Gtk.Grid()
            track.set_column_homogeneous(True)
            track.set_hexpand(True)
            track.set_valign(Gtk.Align.CENTER)
            track.set_size_request(self.MIN_TRACK, thick)
            track.get_style_context().add_class("bar-track")

            col = 0
            for key, _label, css in SERIES:
                v = counts[key]
                if not v:
                    continue
                seg = Gtk.Box()
                seg.get_style_context().add_class(css)
                seg.get_style_context().add_class("bar-seg")
                seg.set_size_request(-1, thick)
                track.attach(seg, col, 0, v, 1)
                col += v
            if col < top:
                # An empty tail keeps every row the same number of columns, so
                # a short day is short rather than stretched to full width.
                rest = Gtk.Box()
                rest.set_size_request(-1, thick)
                track.attach(rest, col, 0, top - col, 1)
            row.pack_start(track, True, True, 0)

            total = sum(counts.values())
            tot = Gtk.Label(label=str(total) if total else "", xalign=1)
            tot.get_style_context().add_class("chart-key")
            tot.set_width_chars(2)
            row.pack_start(tot, False, False, 0)

            row.set_tooltip_text("%s — %d taken, %d snoozed, %d skipped"
                                 % (d.strftime("%a %d %b"), counts["taken"],
                                    counts["snoozed"], counts["skipped"]))
            self.pack_start(row, False, False, 0)
        self.show_all()


# ------------------------------------------------------------------- widgets

class Window(Gtk.Window):
    def __init__(self):
        super().__init__(title="BackAtIt")
        self.set_default_size(1120, 700)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_icon_name(APP_ID)
        self.connect("destroy", Gtk.main_quit)

        # A header bar of our own, so the name sits at the top left instead of
        # centred the way the window manager would draw it. The centre slot is
        # given an empty widget, or GTK puts the title back into it.
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.set_custom_title(Gtk.Label())
        name = Gtk.Label(label="BackAtIt")
        name.get_style_context().add_class("app-name")
        # The header bar has less padding than the content below it, so the
        # name would start 10px to the left of the tabs and the cards.
        name.set_margin_start(10)
        header.pack_start(name)
        self.set_titlebar(header)

        self.cfg = read_config()
        # Not packed anywhere: they hold the wording that the tooltip shows.
        self.lbl_status = Gtk.Label()
        self.lbl_detail = Gtk.Label()
        self.sections = []          # every section, in creation order
        self.tabs = []              # [{name, sections, columns, scroller}]
        self._tab = None
        self._ncols = 0
        self._reflowing = False
        self._dirty = False
        self._clear_msg = None
        self._pending = None      # (wanted_state, give_up_at) while the daemon catches up

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(outer)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(120)

        self._build_settings()      # fills self.tabs via _new_tab/_section
        self._build_stats()
        self._build_guide()

        outer.pack_start(self._topbar(), False, False, 0)
        outer.pack_start(self.stack, True, True, 0)
        outer.pack_start(self._action_bar(), False, False, 0)

        self._reflow(1)
        self.connect("size-allocate", self._on_size_allocate)

        self._sync_sensitivity()
        self.refresh_status()
        GLib.timeout_add_seconds(1, self.refresh_status)

    # -- tabs --------------------------------------------------------
    def _new_tab(self, name):
        """Start a new tab. Sections created after this land in it."""
        columns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=COL_GAP)
        # Equal columns. This was briefly unsafe when the stats chart was drawn
        # as vertical bars: it needed 630px for 30 days and dragged every other
        # column up with it. Horizontal bars need 396px whatever the period, so
        # even columns no longer inflate the window.
        columns.set_homogeneous(True)
        columns.set_margin_start(16); columns.set_margin_end(16)
        columns.set_margin_top(16); columns.set_margin_bottom(16)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.add(columns)

        page = {"name": name, "sections": [], "columns": columns, "scroller": scroller}
        self.tabs.append(page)
        self._tab = page
        self.stack.add_titled(scroller, name.lower().replace(" ", "-"), name)
        return page

    # -- responsive columns ------------------------------------------
    def _columns_for(self, width):
        usable = width - 36 + COL_GAP          # window margins, plus one gutter
        return max(1, min(MAX_COLS, usable // (COL_MIN + COL_GAP)))

    def _on_size_allocate(self, _widget, alloc):
        """Re-column only when the count actually changes.

        The work happens on an idle callback rather than here: adding and
        removing children during a size allocation re-enters this handler,
        and GTK warns and flickers if you do it inline.
        """
        want = self._columns_for(alloc.width)
        if want != self._ncols and not self._reflowing:
            self._reflowing = True
            GLib.idle_add(self._do_reflow, want)

    def _do_reflow(self, ncols):
        self._reflowing = False
        self._reflow(ncols)
        return False

    def _reflow(self, ncols):
        if ncols == self._ncols:
            return
        self._ncols = ncols
        for page in self.tabs:
            self._reflow_page(page, ncols)

    def _reflow_page(self, page, ncols):
        # Never ask for more columns than the tab has sections, or a tab with
        # one group would sit in a narrow strip with dead space beside it.
        ncols = max(1, min(ncols, len(page["sections"])))

        for sec in page["sections"]:
            parent = sec.get_parent()
            if parent is not None:
                parent.remove(sec)
        for col in page["columns"].get_children():
            page["columns"].remove(col)

        cols = []
        for _ in range(ncols):
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
            col.set_valign(Gtk.Align.START)
            page["columns"].pack_start(col, True, True, 0)
            cols.append([col, 0])

        # Greedily drop each section into the shortest column so the sides end
        # up roughly level instead of one running far past the other.
        for sec in page["sections"]:
            height = sec.get_preferred_height()[1]
            target = min(cols, key=lambda c: c[1])
            target[0].pack_start(sec, False, False, 0)
            target[1] += height

        page["columns"].show_all()
        self._sync_sensitivity()

        # Everything has just moved, so an old scroll offset now points at
        # something unrelated — usually leaving the first heading half cut off.
        GLib.idle_add(page["scroller"].get_vadjustment().set_value, 0)

    # -- top bar -----------------------------------------------------
    def _topbar(self):
        """Tabs on the left, live state on the right — the way a desktop app
        puts its navigation and its status. Built after the stack exists,
        because the switcher has to be bound to it."""
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        bar.get_style_context().add_class("topbar")
        bar.set_margin_start(16); bar.set_margin_end(16)
        bar.set_margin_top(10); bar.set_margin_bottom(10)

        switcher = Gtk.StackSwitcher(stack=self.stack)
        switcher.set_halign(Gtk.Align.START)
        switcher.set_valign(Gtk.Align.CENTER)
        bar.pack_start(switcher, False, False, 0)

        right = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        right.set_halign(Gtk.Align.END)
        right.set_valign(Gtk.Align.CENTER)

        # The counter alone says whether it is running — if it is ticking, it
        # is on. The wording is still there on hover for anyone who wants it.
        self.lbl_counter = Gtk.Label(xalign=1)
        self.lbl_counter.get_style_context().add_class("counter")
        self.lbl_counter.set_width_chars(8)
        right.pack_start(self.lbl_counter, False, False, 2)

        self.btn_go = Gtk.Button(label="Start reminders")
        self.btn_go.get_style_context().add_class("go")
        self.btn_go.get_style_context().add_class("suggested-action")
        self.btn_go.set_valign(Gtk.Align.CENTER)
        self.btn_go.connect("clicked", self.on_toggle_running)
        right.pack_start(self.btn_go, False, False, 0)

        self.lbl_counter.set_has_tooltip(True)

        bar.pack_end(right, False, False, 0)
        return bar

    # -- settings ----------------------------------------------------
    @staticmethod
    def _wrap(label, chars):
        """Let a label wrap AND cap the width it asks for.

        set_line_wrap alone is not enough: without a max width the label still
        requests its full natural width, which widened the whole form past the
        window and clipped the left-hand text.
        """
        label.set_line_wrap(True)
        label.set_max_width_chars(chars)
        label.set_xalign(0)

    def _section(self, title, blurb="", extra=None):
        """One self-contained group. Returned so its rows can be added to it,
        and kept in self.sections so it can be moved between columns.
        `extra` rides along on the right of the title, for a legend or similar.
        """
        sec = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        sec.get_style_context().add_class("card")
        sec.set_valign(Gtk.Align.START)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        head.set_margin_bottom(2)
        lbl = Gtk.Label(xalign=0, label=title)
        lbl.get_style_context().add_class("section")
        head.pack_start(lbl, False, False, 0)
        if extra is not None:
            extra.set_valign(Gtk.Align.CENTER)
            head.pack_end(extra, False, False, 0)
        sec.pack_start(head, False, False, 0)
        if blurb:
            sub = Gtk.Label(xalign=0, label=blurb)
            sub.get_style_context().add_class("muted")
            self._wrap(sub, HELP_CHARS)
            sub.set_margin_bottom(4)
            sec.pack_start(sub, False, False, 0)

        self.sections.append(sec)
        if self._tab is not None:
            self._tab["sections"].append(sec)
        return sec

    def _row(self, box, label, widget, help_text="", indent=0):
        """Label above, field below, explanation under that.

        Stacked rather than side by side so the field gets the column's full
        width, and so a long label never squeezes the control it belongs to.
        The whole group is returned, so greying it out dims the label and the
        explanation along with the field.
        """
        group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        group.set_margin_start(indent)
        group.set_margin_top(10)

        lbl = Gtk.Label(xalign=0, label=label)
        self._wrap(lbl, HELP_CHARS)
        lbl.set_margin_bottom(3)
        group.pack_start(lbl, False, False, 0)

        widget.set_hexpand(True)
        group.pack_start(widget, False, False, 0)

        if help_text:
            h = Gtk.Label(xalign=0, label=help_text)
            h.get_style_context().add_class("muted")
            self._wrap(h, HELP_CHARS)
            group.pack_start(h, False, False, 0)

        box.pack_start(group, False, False, 0)
        return group

    def _spin(self, value):
        sp = Gtk.SpinButton.new_with_range(MIN_M, MAX_M, 0.5)
        sp.set_digits(1)
        sp.set_value(value)
        sp.set_width_chars(6)
        sp.set_hexpand(True)
        return sp

    def _minutes(self, box, label, key, default, help_text, indent=0):
        """A minutes spinner plus a live '= 30 seconds' echo underneath, so a
        fractional value never has to be decoded in your head."""
        sp = self._spin(num(self.cfg, key, default))
        echo = Gtk.Label(xalign=0)
        echo.get_style_context().add_class("muted")
        self._wrap(echo, HELP_CHARS)

        def update(*_):
            echo.set_text("%s  ·  %s" % (human_minutes(sp.get_value()), help_text))

        sp.connect("value-changed", update)
        update()
        group = self._row(box, label, sp, indent=indent)
        group.pack_start(echo, False, False, 0)
        return sp, group, echo

    def _check(self, box, label, active, help_text="", indent=0):
        cb = Gtk.CheckButton(label=label)
        cb.set_active(active)
        cb.set_margin_start(indent)
        cb.set_margin_top(6)
        self._wrap(cb.get_child(), HELP_CHARS)
        cb.get_child().set_margin_start(4)
        box.pack_start(cb, False, False, 0)
        if help_text:
            h = Gtk.Label(xalign=0, label=help_text)
            h.get_style_context().add_class("muted")
            self._wrap(h, HELP_CHARS)
            h.set_margin_start(indent + 26)
            box.pack_start(h, False, False, 0)
        return cb

    def _text(self, box, label, value, help_text, lines=3):
        """A small multi-line field, for wording that runs to a sentence."""
        view = Gtk.TextView()
        view.set_wrap_mode(Gtk.WrapMode.WORD)
        view.set_left_margin(6); view.set_right_margin(6)
        view.set_top_margin(4); view.set_bottom_margin(4)
        view.get_buffer().set_text(value)
        frame = Gtk.ScrolledWindow()
        frame.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        frame.set_shadow_type(Gtk.ShadowType.IN)
        frame.set_size_request(-1, 24 * lines)
        frame.add(view)
        self._row(box, label, frame, help_text)
        return view

    @staticmethod
    def _text_value(view):
        buf = view.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        # The config is one line per setting, so store a break as the two
        # characters \n; alert.py turns them back into real line breaks.
        return text.replace("\n", "\\n").strip()

    def _sound(self, box, label, path, help_text):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn = Gtk.FileChooserButton(title=label, action=Gtk.FileChooserAction.OPEN)
        btn.set_width_chars(12)
        btn.set_hexpand(True)
        if os.path.exists(path):
            btn.set_filename(path)
        flt = Gtk.FileFilter(); flt.set_name("Sound files")
        for pat in ("*.oga", "*.ogg", "*.wav", "*.mp3", "*.flac"):
            flt.add_pattern(pat)
        btn.add_filter(flt)
        play = Gtk.Button.new_from_icon_name("media-playback-start-symbolic", Gtk.IconSize.BUTTON)
        play.set_tooltip_text("Play this sound")
        play.connect("clicked", lambda *_: self._play(btn.get_filename()))
        row.pack_start(btn, True, True, 0)
        row.pack_start(play, False, False, 0)
        self._row(box, label, row, help_text)
        return btn

    def _build_settings(self):
        c = self.cfg

        self._new_tab("Timing")
        sec = self._section("How often", "The main rhythm of your work day.")
        self.sp_interval, _, _ = self._minutes(
            sec, "Break every", "INTERVAL_MIN", 30,
            "how long you work before being told to get up")
        self.sp_snooze, _, _ = self._minutes(
            sec, "Snooze length", "SNOOZE_MIN", 5,
            "how long the Snooze button puts the break off for")

        sec = self._section("After the break",
                            "A second alert that tells you the walk is over and brings you back.")
        self.cb_walk = self._check(
            sec, "Tell me when the walk is over", flag(c, "WALK_ENABLED"),
            "Without this, the break alert is the only one you get.")
        self.sp_walk, self.row_walk, self.echo_walk = self._minutes(
            sec, "Break length", "WALK_MIN", 1,
            "how long the break itself lasts before it calls you back",
            indent=26)
        self.sp_cap, self.row_cap, self.echo_cap = self._minutes(
            sec, "Nag me at most every", "BUZZ_GAP_CAP_MIN", 15,
            "the back-to-work alarm waits longer each time; this is the longest it waits",
            indent=26)

        sec = self._section("Before the break", "Avoid being ambushed mid-sentence.")
        self.cb_warn = self._check(
            sec, "Warn me that a break is coming", flag(c, "WARN_ENABLED"),
            "A quiet desktop notification shortly before the alert appears.")
        self.sp_warn, self.row_warn, self.echo_warn = self._minutes(
            sec, "Warn me this far ahead", "WARN_LEAD_MIN", 2,
            "how much notice you get", indent=26)

        self._new_tab("When it runs")
        sec = self._section("When you are away")
        self.cb_idle = self._check(
            sec, "Skip the break if I am already away from the computer",
            flag(c, "IDLE_SKIP"),
            "No point alarming an empty room. The timer just starts again.")
        self.sp_idle, self.row_idle, self.echo_idle = self._minutes(
            sec, "Count me away after", "IDLE_MIN", 5,
            "no mouse or keyboard for this long means you are already on a break",
            indent=26)

        sec = self._section("Daily schedule",
                            "Runs on its own between set hours — this window does not have to be open.")
        self.cb_sched = self._check(
            sec, "Run automatically between set hours", flag(c, "SCHEDULE_ENABLED", "0"))
        self.e_start = Gtk.Entry(text=c.get("SCHEDULE_START", "09:00"))
        self.e_start.set_width_chars(6); self.e_start.set_max_length(5)
        self.e_start.set_hexpand(True)
        self.e_end = Gtk.Entry(text=c.get("SCHEDULE_END", "18:00"))
        self.e_end.set_width_chars(6); self.e_end.set_max_length(5)
        self.e_end.set_hexpand(True)
        times = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        times.pack_start(self.e_start, True, True, 0)
        times.pack_start(Gtk.Label(label="to"), False, False, 0)
        times.pack_start(self.e_end, True, True, 0)
        self.row_times = self._row(
            sec, "Between these hours", times,
            "24-hour clock, like 09:00 and 18:30. Crossing midnight works (22:00 to 02:00).",
            indent=26)
        off = {d for d in c.get("DAYS_OFF", "").split(",") if d}
        if not off and flag(c, "WEEKDAYS_ONLY", "0"):
            off = {"6", "7"}                       # carried over from the old setting
        self.day_toggles = []
        days_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        days_box.get_style_context().add_class("linked")
        for i, name in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"), 1):
            t = Gtk.ToggleButton(label=name)
            t.set_active(str(i) in off)
            self.day_toggles.append((i, t))
            days_box.pack_start(t, True, True, 0)
        self.row_days = self._row(
            sec, "Days off", days_box,
            "Switch on the days you want left alone — any combination, not just "
            "the weekend. Leave them all off to run every day.",
            indent=26)

        sec = self._section("Startup")
        self.cb_autostart = self._check(
            sec, "Start automatically when I log in", os.path.exists(AUTOSTART),
            "Keep this on if you use the schedule — it cannot fire if the "
            "background app is not running.")

        quit_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        quit_row.set_margin_top(10)
        qb = Gtk.Button(label="Quit background app")
        qb.set_tooltip_text("Stops everything until you open this window again.")
        qb.connect("clicked", self.on_quit_daemon)
        quit_row.pack_start(qb, False, False, 0)
        sec.pack_start(quit_row, False, False, 0)

        self._new_tab("Alerts")
        sec = self._section("What the alerts say",
                            "Your own wording, if you would rather be nagged "
                            "differently.")
        self.e_break_title = Gtk.Entry(text=c.get("BREAK_TITLE", "Take a break!"))
        self.e_break_title.set_width_chars(12)
        self._row(sec, "Break heading", self.e_break_title,
                  "The big line on the alert that tells you to get up.")
        self.tv_break_msg = self._text(
            sec, "Break message",
            c.get("BREAK_MESSAGE",
                  "Have a little walk. Stretch your body and relax a bit, "
                  "then start again."),
            "The smaller line underneath it.")

        self.e_walk_title = Gtk.Entry(text=c.get("WALK_TITLE", "Walk time is up"))
        self.e_walk_title.set_width_chars(12)
        self._row(sec, "Back-to-work heading", self.e_walk_title,
                  "Shown when the walk is over and it wants you back.")
        self.tv_walk_msg = self._text(
            sec, "Back-to-work message",
            c.get("WALK_MESSAGE", "Time to get back to work."),
            "Press Test below to see your wording on the real alert.")

        sec = self._section("Sounds",
                            "The two alerts sound different on purpose.")
        self.fc_sound = self._sound(
            sec, "Break sound",
            c.get("SOUND", "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga"),
            "Played when it is time to get up.")
        self.fc_walk_sound = self._sound(
            sec, "Back-to-work sound",
            c.get("WALK_SOUND", "/usr/share/sounds/freedesktop/stereo/complete.oga"),
            "Deliberately different, so you can tell the two apart from another room.")
        sec = self._section("The alert window")
        self.cb_loop = self._check(
            sec, "Keep the break alarm sounding until I answer it", flag(c, "LOOP_SOUND"),
            "It goes quiet after 90 seconds either way; the window stays put.")
        self.cb_full = self._check(
            sec, "Full-screen alerts", flag(c, "FULLSCREEN"),
            "Covers the screen so the alert cannot hide behind your work. "
            "The keyboard is ignored either way, so typing can never dismiss it.")

        tests = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        tests.set_margin_top(8)
        for label, which in (("Test break alert", "break"),
                             ("Test back-to-work alert", "walk")):
            b = Gtk.Button(label=label)
            b.connect("clicked", self.on_test, which)
            tests.pack_start(b, False, False, 0)
        sec.pack_start(tests, False, False, 0)

        for cb in (self.cb_walk, self.cb_warn, self.cb_idle, self.cb_sched):
            cb.connect("toggled", lambda *_: self._sync_sensitivity())
        self._connect_dirty()

    def _prose(self, sec, markup):
        lbl = Gtk.Label(xalign=0)
        lbl.set_markup(markup)
        lbl.get_style_context().add_class("guide-step")
        self._wrap(lbl, HELP_CHARS + 8)
        sec.pack_start(lbl, False, False, 0)
        return lbl

    def _build_guide(self):
        """A tab that explains the thing, so the settings do not have to be
        reverse-engineered from their labels."""
        self._new_tab("Guide")

        sec = self._section("How a break cycle works")
        self._prose(sec,
            "<b>1.</b>  You work for the break interval — <i>Timing → Break every</i>.\n"
            "<b>2.</b>  Shortly before it is due, a notification warns you, so a "
            "break never lands mid-sentence.\n"
            "<b>3.</b>  A full-screen alert appears and the alarm sounds. The "
            "keyboard is ignored, so carrying on typing cannot dismiss it, and "
            "the buttons stay dead for three seconds.\n"
            "<b>4.</b>  Click <b>I took my break!</b> and walk away.\n"
            "<b>5.</b>  When the walk is up, a second alert calls you back and "
            "keeps buzzing — a minute of alarm, then a longer and longer silence "
            "— until you click <b>I'm back at work</b>.\n"
            "<b>6.</b>  The next work block begins.")
        self._prose(sec,
            "\nThe countdown restarts when you <i>answer</i>, not when the alert "
            "appeared. However long it sits there, you still get a full work "
            "block afterwards.")

        sec = self._section("Setting it up, step by step")
        self._prose(sec,
            "<b>1.</b>  <b>Timing</b> — set <i>Break every</i> to your work block "
            "and <i>Snooze length</i> to how long “not yet” should buy you.\n"
            "<b>2.</b>  Decide whether you want the walk stage. If you do, set "
            "<i>Walk length</i>, and <i>Nag me at most every</i> for how "
            "persistent the call back should be.\n"
            "<b>3.</b>  <b>When it runs</b> — tick <i>Run automatically between "
            "set hours</i> for your working day, and leave <i>Start "
            "automatically when I log in</i> on so it is there without you "
            "thinking about it.\n"
            "<b>4.</b>  <b>Alerts</b> — pick the two sounds and press "
            "<b>Test break alert</b> to see exactly what will interrupt you.\n"
            "<b>5.</b>  Press <b>Save</b>, then <b>Start reminders</b> at the top "
            "right. The counter starts ticking.")

        sec = self._section("Reading the top right")
        self._prose(sec,
            "The counter is the honest answer to “is this actually on?”. If it "
            "is ticking down, the background app is alive and a break is coming.\n\n"
            "<b>Running</b> — counting down to the next break.\n"
            "<b>Alert on screen</b> — an alert is up, waiting for you.\n"
            "<b>Off for today</b> — you stopped it; a schedule resumes tomorrow.\n"
            "<b>Not running</b> — the background app is stopped. Press "
            "<b>Start reminders</b>.\n\n"
            "The line underneath counts today's breaks: taken, snoozed, and "
            "skipped because you were already away.")

        info = about_info()
        sec = self._section("About %s" % info["APP_NAME"])
        who = info["APP_AUTHOR"] or "not set — see about.conf"
        self._prose(sec,
            "<b>%s %s</b>\n\n"
            "This started with back pain. Sitting through long stretches of "
            "work without moving does that, and every break reminder I tried "
            "was far too easy to wave away — a little notification in the "
            "corner, dismissed without reading it, another hour gone.\n\n"
            "So this one is harder to ignore. It takes over the screen, and it "
            "ignores the keyboard completely, so carrying on typing cannot "
            "dismiss it by accident. Then it calls you back when the break is "
            "over, because that is the half most timers forget.\n\n"
            "Everything about it bends to how you work: the timings, the "
            "wording of both alerts, the sounds, your schedule and your days "
            "off.\n\n"
            "<b>Made by</b>  %s%s\n"
            "<b>Licence</b>  %s — free to use, change and share, including "
            "commercially. The only condition is that the copyright notice "
            "stays with it.\n%s"
            % (info["APP_NAME"], info["APP_VERSION"],
               GLib.markup_escape_text(who),
               ("  &lt;%s&gt;" % GLib.markup_escape_text(info["APP_EMAIL"]))
               if info["APP_EMAIL"] else "",
               info["APP_LICENSE"],
               ("<b>Home</b>  %s" % GLib.markup_escape_text(info["APP_URL"]))
               if info["APP_URL"] else ""))

        sec = self._section("Worth knowing")
        self._prose(sec,
            "<b>Turning it off.</b>  Every alert has a small <i>Turn off "
            "reminders</i> button. It does not wipe your setup — it stops today "
            "only, and a schedule runs again tomorrow.\n\n"
            "<b>Already away.</b>  If you have not touched the mouse or keyboard "
            "for a while when a break falls due, you are clearly already having "
            "one, so it stays quiet and counts it as skipped.\n\n"
            "<b>Fractions are allowed.</b>  Every minutes box takes halves — "
            "<b>0.5</b> is thirty seconds. Useful for trying things out.\n\n"
            "<b>Nothing is hidden.</b>  Widen the window and the groups spread "
            "into two or three columns; narrow it and they stack.")

    def _build_stats(self):
        self._new_tab("Stats")
        self._stats_days = 7
        self._stats_stamp = None

        legend = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        for _k, label, css in SERIES:
            item = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
            item.pack_start(swatch(css), False, False, 0)
            lab = Gtk.Label(label=label)
            lab.get_style_context().add_class("chart-key")
            item.pack_start(lab, False, False, 0)
            legend.pack_start(item, False, False, 0)

        sec = self._section("Breaks per day", extra=legend)
        period = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        period.get_style_context().add_class("linked")
        period.set_halign(Gtk.Align.START)
        period.set_margin_bottom(6)
        self._period_btns = []
        first = None
        for days, label in ((7, "Last 7 days"), (30, "Last 30 days")):
            b = Gtk.RadioButton.new_with_label_from_widget(first, label)
            if first is None:
                first = b
            b.set_mode(False)                      # draw as a button, not a radio dot
            b.connect("toggled", self._on_period, days)
            self._period_btns.append((days, b))
            period.pack_start(b, False, False, 0)
        sec.pack_start(period, False, False, 0)

        self.chart = BarChart()
        sec.pack_start(self.chart, False, False, 0)

        sec = self._section("Totals")
        self.lbl_totals = Gtk.Label(xalign=0)
        self._wrap(self.lbl_totals, HELP_CHARS + 8)
        sec.pack_start(self.lbl_totals, False, False, 0)

        self.lbl_today = Gtk.Label(xalign=0)
        self.lbl_today.get_style_context().add_class("muted")
        self._wrap(self.lbl_today, HELP_CHARS + 8)
        self.lbl_today.set_margin_top(8)
        sec.pack_start(self.lbl_today, False, False, 0)

        note = Gtk.Label(xalign=0)
        note.get_style_context().add_class("muted")
        self._wrap(note, HELP_CHARS + 8)
        note.set_margin_top(8)
        note.set_text("Counted when you answer an alert. \u201cSkipped\u201d means a "
                      "break fell due while you were already away from the keyboard.")
        sec.pack_start(note, False, False, 0)

        sec = self._section("History")
        where = Gtk.Label(xalign=0)
        where.get_style_context().add_class("muted")
        self._wrap(where, HELP_CHARS + 8)
        where.set_text("Kept in %s, which survives logging out." % STATS_FILE)
        sec.pack_start(where, False, False, 0)

        clear = Gtk.Button(label="Clear history")
        clear.set_halign(Gtk.Align.START)
        clear.set_margin_top(10)
        clear.set_tooltip_text("Start the counts again from zero.")
        clear.connect("clicked", self.on_clear_stats)
        sec.pack_start(clear, False, False, 0)

    def _on_period(self, btn, days):
        if btn.get_active():
            self._stats_days = days
            self._stats_stamp = None       # force a redraw
            self._refresh_stats_if_changed()

    def _refresh_stats_if_changed(self):
        """Re-read the tally only when the file actually changed, so the
        one-second status tick does not redraw a chart for nothing."""
        try:
            stamp = (os.path.getmtime(STATS_FILE), self._stats_days)
        except OSError:
            stamp = (0, self._stats_days)
        if stamp == self._stats_stamp:
            return
        self._stats_stamp = stamp

        rows = stats_range(self._stats_days)
        self.chart.set_rows(rows)

        totals = {k: sum(c[k] for _, c in rows) for k, _l, _c in SERIES}
        active = [c for _, c in rows if sum(c.values())]
        avg = (sum(totals.values()) / len(active)) if active else 0
        self.lbl_totals.set_markup(
            "Over the last %d days: <b>%d</b> taken, <b>%d</b> snoozed, "
            "<b>%d</b> skipped.\nThat is %s breaks on each of the %d days you "
            "were at the desk."
            % (self._stats_days, totals["taken"], totals["snoozed"],
               totals["skipped"], ("%.1f" % avg).rstrip("0").rstrip("."),
               len(active)))
        t = stats_today()
        self.lbl_today.set_text(
            "Today so far: %d taken, %d snoozed, %d skipped."
            % (t["taken"], t["snoozed"], t["skipped"]))

    def _action_bar(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bar.get_style_context().add_class("actionbar")
        bar.set_margin_start(16); bar.set_margin_end(16)
        bar.set_margin_top(10); bar.set_margin_bottom(12)

        self.lbl_saved = Gtk.Label(xalign=0)
        bar.pack_start(self.lbl_saved, True, True, 0)

        close = Gtk.Button(label="Close")
        close.connect("clicked", self.on_close)
        bar.pack_start(close, False, False, 0)

        save = Gtk.Button(label="Save")
        save.connect("clicked", self.on_save)
        bar.pack_start(save, False, False, 0)

        save_close = Gtk.Button(label="Save and close")
        save_close.get_style_context().add_class("suggested-action")
        save_close.connect("clicked", self.on_save_close)
        bar.pack_start(save_close, False, False, 0)
        return bar

    # -- telling you what happened -----------------------------------
    def _message(self, text, style=""):
        for name in ("msg-ok", "msg-dirty"):
            self.lbl_saved.get_style_context().remove_class(name)
        if style:
            self.lbl_saved.get_style_context().add_class(style)
        self.lbl_saved.set_text(text)

    def _set_dirty(self, dirty):
        """Say plainly whether what is on screen has been written yet."""
        self._dirty = dirty
        if self._clear_msg:
            GLib.source_remove(self._clear_msg)
            self._clear_msg = None
        if dirty:
            self._message("Unsaved changes", "msg-dirty")
        else:
            self._message("\u2713 Saved at %s" % time.strftime("%H:%M:%S"), "msg-ok")
            self._clear_msg = GLib.timeout_add_seconds(8, self._fade_message)

    def _fade_message(self):
        self._clear_msg = None
        if not self._dirty:
            self._message("")
        return False

    def _connect_dirty(self):
        """Anything you can change should say so. Connected after the initial
        values are in place, so loading the config does not look like an edit."""
        mark = lambda *_: self._set_dirty(True)
        for sp in (self.sp_interval, self.sp_snooze, self.sp_walk, self.sp_cap,
                   self.sp_warn, self.sp_idle):
            sp.connect("value-changed", mark)
        for cb in (self.cb_walk, self.cb_warn, self.cb_idle, self.cb_sched,
                   self.cb_loop, self.cb_full, self.cb_autostart):
            cb.connect("toggled", mark)
        for entry in (self.e_start, self.e_end,
                      self.e_break_title, self.e_walk_title):
            entry.connect("changed", mark)
        for view in (self.tv_break_msg, self.tv_walk_msg):
            view.get_buffer().connect("changed", mark)
        for chooser in (self.fc_sound, self.fc_walk_sound):
            chooser.connect("file-set", mark)
        for _day, toggle in self.day_toggles:
            toggle.connect("toggled", mark)

    # -- behaviour ---------------------------------------------------
    def _sync_sensitivity(self):
        """Grey out whatever belongs to a switched-off option, so the window
        shows what is actually in effect rather than a wall of live controls."""
        for widget in (self.row_walk, self.echo_walk, self.row_cap, self.echo_cap):
            widget.set_sensitive(self.cb_walk.get_active())
        for widget in (self.row_warn, self.echo_warn):
            widget.set_sensitive(self.cb_warn.get_active())
        for widget in (self.row_idle, self.echo_idle):
            widget.set_sensitive(self.cb_idle.get_active())
        for widget in (self.row_times, self.row_days):
            widget.set_sensitive(self.cb_sched.get_active())

    def _is_active(self):
        return bool(read(PHASE_FILE))

    def refresh_status(self):
        running = daemon_running()
        phase = read(PHASE_FILE)
        nxt = read(NEXT_EPOCH)
        active = bool(phase)

        waiting = False
        if self._pending:
            wanted, deadline = self._pending
            if active == wanted or time.time() > deadline:
                self._pending = None
            else:
                active, waiting = wanted, True
                phase, nxt = "", ""

        if waiting:
            self.lbl_status.set_text("Starting" if active else "Stopping")
            self.lbl_detail.set_text("just a moment")
            self.lbl_counter.set_text("\u2026")
        elif not running:
            self.lbl_status.set_text("Not running")
            self.lbl_detail.set_text("background app stopped")
            self.lbl_counter.set_text("—")
        elif paused_today():
            self.lbl_status.set_text("Off for today")
            self.lbl_detail.set_text("any schedule resumes tomorrow")
            self.lbl_counter.set_text("—")
        elif phase == "alert":
            self.lbl_status.set_text("Alert on screen")
            self.lbl_detail.set_text("waiting for you to answer it")
            self.lbl_counter.set_text("—")
        elif active and nxt.isdigit():
            left = int(nxt) - int(time.time())
            self.lbl_status.set_text("Running")
            self.lbl_detail.set_text(
                "walk ends in" if phase == "walk" else "next break in")
            self.lbl_counter.set_text(mmss(left) if left > 0 else "now")
        elif active:
            self.lbl_status.set_text("Running")
            self.lbl_detail.set_text("starting the countdown…")
            self.lbl_counter.set_text("—")
        else:
            self.lbl_status.set_text("Off")
            if self.cb_sched.get_active():
                self.lbl_detail.set_text(
                    "waiting for the schedule (%s to %s)"
                    % (self.e_start.get_text(), self.e_end.get_text()))
            else:
                self.lbl_detail.set_text("press Start to begin")
            self.lbl_counter.set_text("—")

        tip = self.lbl_status.get_text()
        detail = self.lbl_detail.get_text()
        if detail:
            tip = "%s — %s" % (tip, detail)
        self.lbl_counter.set_tooltip_text(tip)

        self.btn_go.set_label("Stop reminders" if active else "Start reminders")
        ctx = self.btn_go.get_style_context()
        ctx.remove_class("suggested-action" if active else "destructive-action")
        ctx.add_class("destructive-action" if active else "suggested-action")

        self._refresh_stats_if_changed()
        return True

    def _values(self):
        return {
            "INTERVAL_MIN": self.sp_interval.get_value(),
            "SNOOZE_MIN": self.sp_snooze.get_value(),
            "WALK_ENABLED": int(self.cb_walk.get_active()),
            "WALK_MIN": self.sp_walk.get_value(),
            "BUZZ_GAP_CAP_MIN": self.sp_cap.get_value(),
            "WARN_ENABLED": int(self.cb_warn.get_active()),
            "WARN_LEAD_MIN": self.sp_warn.get_value(),
            "IDLE_SKIP": int(self.cb_idle.get_active()),
            "IDLE_MIN": self.sp_idle.get_value(),
            "SCHEDULE_ENABLED": int(self.cb_sched.get_active()),
            "SCHEDULE_START": self.e_start.get_text().strip(),
            "SCHEDULE_END": self.e_end.get_text().strip(),
            "DAYS_OFF": ",".join(str(i) for i, t in self.day_toggles if t.get_active()),
            # Retire the old key explicitly, or lib.sh would migrate it back
            # every time you cleared every day off.
            "WEEKDAYS_ONLY": 0,
            "BREAK_TITLE": self.e_break_title.get_text().strip(),
            "BREAK_MESSAGE": self._text_value(self.tv_break_msg),
            "WALK_TITLE": self.e_walk_title.get_text().strip(),
            "WALK_MESSAGE": self._text_value(self.tv_walk_msg),
            "SOUND": self.fc_sound.get_filename() or "",
            "WALK_SOUND": self.fc_walk_sound.get_filename() or "",
            "LOOP_SOUND": int(self.cb_loop.get_active()),
            "FULLSCREEN": int(self.cb_full.get_active()),
        }

    def _save(self):
        """Returns False if something was rejected, so "Save and close" knows
        not to close over the top of a complaint."""
        ok = True
        vals = self._values()
        for key in ("SCHEDULE_START", "SCHEDULE_END"):
            if not re.fullmatch(r"([01]?[0-9]|2[0-3]):[0-5][0-9]", vals[key]):
                self._error("Schedule times must look like 09:00 or 18:30.\n\n"
                            "“%s” is not a valid time, so the schedule was left "
                            "as it was." % vals[key])
                vals.pop("SCHEDULE_START"); vals.pop("SCHEDULE_END")
                ok = False
                break
        for key in ("SOUND", "WALK_SOUND"):
            if not vals[key] or not os.path.exists(vals[key]):
                vals.pop(key)
        for key, fallback in (("BREAK_TITLE", "Take a break!"),
                              ("WALK_TITLE", "Walk time is up")):
            if not vals[key]:
                vals[key] = fallback
        write_config(vals)
        self._set_autostart(self.cb_autostart.get_active())
        self.cfg = read_config()
        self._set_dirty(False)
        return ok

    def _error(self, text):
        dlg = Gtk.MessageDialog(transient_for=self, modal=True,
                                message_type=Gtk.MessageType.WARNING,
                                buttons=Gtk.ButtonsType.OK, text="BackAtIt")
        dlg.format_secondary_text(text)
        dlg.run(); dlg.destroy()

    def _set_autostart(self, on):
        if on:
            os.makedirs(os.path.dirname(AUTOSTART), exist_ok=True)
            with open(AUTOSTART, "w") as fh:
                fh.write(
                    "[Desktop Entry]\nType=Application\n"
                    "Name=BackAtIt (background)\n"
                    "Comment=Keeps the break schedule running\n"
                    "Exec=%s/alarmd.sh\nIcon=alarm-clock\nTerminal=false\n"
                    "NoDisplay=true\nX-GNOME-Autostart-enabled=true\n" % APP_DIR)
        elif os.path.exists(AUTOSTART):
            os.remove(AUTOSTART)

    def _play(self, path):
        if path and os.path.exists(path):
            subprocess.Popen(["pw-play", path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _in_schedule(self):
        """Is the daily schedule what is keeping it running right now?

        Asked of lib.sh rather than recomputed here: the rules cover windows
        that cross midnight and per-day exclusions, and a second copy of that
        logic would eventually disagree with the daemon's.
        """
        return subprocess.call(
            ["bash", "-c", '. "$1/lib.sh"; load_config; in_schedule', "_", APP_DIR],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0

    def _daemon(self, action):
        """Reuse start_daemon/stop_daemon from lib.sh rather than reimplement
        them. Stopping in particular has to kill the daemon's sleeping child
        and wait for the process to really be gone, and that logic should
        exist in exactly one place."""
        subprocess.call(
            ["bash", "-c", '. "$1/lib.sh"; %s' % action, "_", APP_DIR],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # -- buttons -----------------------------------------------------
    def on_save(self, _btn):
        self._save()

    def on_save_close(self, _btn):
        if self._save():
            Gtk.main_quit()

    def on_close(self, _btn):
        """Closing with edits in hand should not throw them away silently."""
        if self._dirty:
            dlg = Gtk.MessageDialog(
                transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.NONE, text="Close without saving?")
            dlg.format_secondary_text("Your changes have not been written yet.")
            dlg.add_button("Back", Gtk.ResponseType.CANCEL)
            dlg.add_button("Discard", Gtk.ResponseType.CLOSE)
            dlg.add_button("Save and close", Gtk.ResponseType.OK)
            answer = dlg.run()
            dlg.destroy()
            if answer == Gtk.ResponseType.CANCEL:
                return
            if answer == Gtk.ResponseType.OK and not self._save():
                return
        Gtk.main_quit()

    def on_toggle_running(self, _btn):
        starting = not self._is_active()

        if starting:
            # Saved first, because the daemon works from the config file: press
            # Start with an edited interval unsaved and it would quietly count
            # down the old one. Stopping needs no such thing.
            self._save()
            if os.path.exists(PAUSE_FILE):
                os.remove(PAUSE_FILE)
            open(MANUAL_FLAG, "w").close()
            self._daemon("start_daemon")
        else:
            if os.path.exists(MANUAL_FLAG):
                os.remove(MANUAL_FLAG)
            # Only mute the schedule when the schedule is what would otherwise
            # keep going. Ending an ad-hoc session hours outside your working
            # window should not silently cancel that window for the day.
            if self.cb_sched.get_active() and self._in_schedule():
                with open(PAUSE_FILE, "w") as fh:
                    fh.write(date.today().isoformat())

        # The daemon otherwise notices at its next tick, up to five seconds
        # later, and the button sits there looking as though nothing happened.
        self._daemon("poke_daemon")

        # Show the new state at once and let the daemon confirm it. The
        # deadline matters: if the daemon disagrees — a schedule that says
        # otherwise, say — the button must go back to the truth rather than
        # keep a comfortable lie on screen.
        self._pending = (starting, time.time() + 5)
        self.refresh_status()
        GLib.timeout_add(200, self._recheck)

    def _recheck(self):
        self.refresh_status()
        return False

    def on_clear_stats(self, _btn):
        dlg = Gtk.MessageDialog(
            transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL, text="Clear the break history?")
        dlg.format_secondary_text(
            "Every day's counts go back to zero.\n\n"
            "A copy is kept as %s.bak, so this is recoverable if you change "
            "your mind." % STATS_FILE)
        answer = dlg.run()
        dlg.destroy()
        if answer != Gtk.ResponseType.OK:
            return
        try:
            if os.path.exists(STATS_FILE):
                os.replace(STATS_FILE, STATS_FILE + ".bak")
            os.makedirs(os.path.dirname(STATS_FILE), exist_ok=True)
            open(STATS_FILE, "w").close()
        except OSError as exc:
            self._error("Could not clear the history:\n%s" % exc)
            return
        self._stats_stamp = None
        self._refresh_stats_if_changed()

    def on_test(self, _btn, which):
        subprocess.Popen([os.path.join(APP_DIR, "alertctl.sh"), which])

    def on_quit_daemon(self, _btn):
        self._daemon("stop_daemon")
        for path in (MANUAL_FLAG, PHASE_FILE, NEXT_EPOCH):
            if os.path.exists(path):
                os.remove(path)
        self.refresh_status()


def main():
    # Set before any window exists: this becomes the Wayland app_id and the
    # X11 WM_CLASS, which is what a dock matches against backatit.desktop.
    GLib.set_prgname(APP_ID)
    Gdk.set_program_class("BackAtIt")
    Gtk.Window.set_default_icon_name(APP_ID)

    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    win = Window()
    win.show_all()
    win._sync_sensitivity()
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
