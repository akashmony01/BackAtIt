<div align="center">

<img src="icons/hicolor/128x128/apps/backatit.png" width="96" alt="BackAtIt">

# BackAtIt

**Get up, walk it off, and actually get back at it.**

A break reminder for Linux that is genuinely hard to ignore — and, unusually,
one that also tells you when the break is over.

[![Latest release](https://img.shields.io/github/v/release/akashmony01/BackAtIt?label=download&style=for-the-badge)](https://github.com/akashmony01/BackAtIt/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/akashmony01/BackAtIt/total?style=for-the-badge)](https://github.com/akashmony01/BackAtIt/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue?style=for-the-badge)](LICENSE)

</div>

---

## Download

Grab the `.deb` from the [**latest release**](https://github.com/akashmony01/BackAtIt/releases/latest),
then:

```sh
sudo apt install ./backatit_1.0_all.deb
```

Or straight from the terminal, without opening a browser:

```sh
wget https://github.com/akashmony01/BackAtIt/releases/latest/download/backatit_1.0_all.deb
sudo apt install ./backatit_1.0_all.deb
```

<sub>That command names version 1.0 explicitly; check
[releases](https://github.com/akashmony01/BackAtIt/releases/latest) for the
current filename if a newer one is out.</sub>

Works on Debian, Ubuntu, Mint and anything else `apt`-based. `apt` pulls in
GTK and the other dependencies itself. Remove it later with
`sudo apt remove backatit`.

Not on a `.deb` distro, or would rather build it yourself? See
[Install](#install) below — it is a shell and Python app, so there is nothing
to compile.

---

## Why this exists

This started with back pain.

Sitting through long stretches of work without moving does that, and every
break reminder I tried was far too easy to wave away. A small notification in
the corner, dismissed without even reading it, and another hour gone.

So this one is harder to ignore. When a break is due it takes over the whole
screen and sounds an alarm, and it **ignores the keyboard completely** — so
carrying on typing cannot dismiss it by accident, which is exactly what
happens when an alert lands mid-sentence. You get up because getting up is
easier than arguing with it.

The other half is the part most timers forget: **coming back**. Once your
break is over a second alert calls you back to the desk and keeps nagging — a
burst of alarm, then a longer and longer silence — until you answer it. No
more twenty-minute "five minute" breaks.

Everything about it bends to how you actually work.

---

## Screenshots

| The break alert | Settings |
|---|---|
| <img src="screenshots/alert.png" alt="The full-screen break alert"> | <img src="screenshots/timing.png" alt="The Timing tab"> |

| Statistics | Built-in guide |
|---|---|
| <img src="screenshots/stats.png" alt="Breaks per day"> | <img src="screenshots/guide.png" alt="The Guide tab"> |

---

## What it does

- **Full-screen alerts** that cannot hide behind the window you are working in
- **Keyboard-proof** — nothing you type can dismiss an alert, and the buttons
  stay dead for three seconds so a click already in flight cannot either
- **Calls you back** when the break is over, and keeps nagging until you answer
- **Knows when you are away** and stays quiet instead of alarming an empty room
- **Daily schedule** with any combination of days off, not just weekends
- **Your words** — the heading and message of both alerts are editable
- **Your sounds** — a different one for each alert, so you can tell them apart
  from another room
- **Statistics** — breaks taken, snoozed and skipped, over the last week or month
- **Fractional minutes** — every timing accepts halves, down to 30 seconds

---

## Install

### From the package (Debian, Ubuntu, Mint)

Either download it from [releases](https://github.com/akashmony01/BackAtIt/releases/latest),
or build it yourself from a clone:

```sh
./build-deb.sh
sudo apt install ./backatit_1.0_all.deb
```

Remove it with `sudo apt remove backatit`.

### From source (any Linux)

```sh
./install.sh                 # just for you       (~/.local)
sudo ./install.sh --system   # for everyone       (/usr/local)
./install.sh --uninstall     # remove it again
```

`install.sh` checks what is missing first and prints the package names for
Debian, Ubuntu, Fedora and Arch.

### Requirements

| Needs | For |
|---|---|
| `bash`, `python3`, `python3-gi` + GTK 3 | the window and the alerts |
| `pw-play` (PipeWire), `paplay` or `aplay` | the sound |
| `notify-send` (libnotify) | the heads-up notifications |
| `gdbus` (glib) | away detection — GNOME only |

On Debian or Ubuntu:

```sh
sudo apt install python3-gi gir1.2-gtk-3.0 libnotify-bin pipewire-bin
```

---

## How a cycle works

1. You work for the break interval.
2. Shortly before it is due, a notification warns you.
3. **"Take a break!"** appears full-screen with the alarm sounding.
4. You click *I took my break!* and walk away.
5. When the break is over, **"Walk time is up"** calls you back and keeps
   buzzing until you click *I'm back at work*.
6. The next work block begins.

The countdown restarts when you **answer**, not when the alert appeared — so
however long an alert sits there, you still get a full work block afterwards.

Step 5 is optional, as is almost everything else.

---

## Where things live

| What | Where |
|---|---|
| Settings | `~/.config/backatit/config` |
| Statistics | `~/.local/state/backatit/stats.tsv` |
| Runtime state | `$XDG_RUNTIME_DIR/backatit/` (cleared at logout) |

Installing, upgrading and removing never touch your settings or statistics.

A few advanced settings are only in the config file: `BUZZ_ON_MIN`,
`BUZZ_GAP_START_MIN` and `GRACE_SEC`. Editing that file by hand is safe — the
app changes values in place and leaves your comments alone.

---

## Working on it

| Script | Does |
|---|---|
| `./install.sh` | install or uninstall from source |
| `./build-deb.sh` | build a `.deb` (`VERSION=1.1 ./build-deb.sh`) |
| `./make-icons.sh` | regenerate icon sizes from `logo.png` |
| `./demo-stats.sh on` | fill the stats page with sample data (`off` restores) |
| `./purge.sh --dry-run` | list every trace of the app on the machine |

Your name, email and version live in `about.conf`, which the About card, the
package metadata and the licence all read from.

### Layout

```
alarm.sh       launcher — starts the background app, opens the window
alarmd.sh      the background app: timing, scheduling, firing alerts
settings.py    the settings window (GTK 3)
alert.py       the full-screen alert window
alertctl.sh    shows one alert on demand, for the Test buttons
lib.sh         shared shell helpers: config, schedule, sound, stats
```

---

## Portability

Written against the freedesktop desktop standards, so it should run on GNOME,
KDE, XFCE, Cinnamon and the rest. Two things are GNOME-specific and degrade
quietly elsewhere:

- **Away detection** asks GNOME's idle monitor. Off GNOME it reads zero, which
  means "you are here" — so breaks always fire and nothing is skipped.
- **The full-screen alert** prefers XWayland so it can stay on top. Under other
  compositors it still goes full screen.

It does **not** run on Windows. The background app is bash, sound goes through
PipeWire, away detection through D-Bus, and start-at-login through
`~/.config/autostart`. Porting means rewriting those four pieces.

---

## Licence

[MIT](LICENSE) — free to use, change and share, including commercially. The
only condition is that the copyright notice stays with it.
