# Changelog

Each `## <version>` section here becomes the notes of that version's GitHub
release, so write it for the people installing it.

## 2.1.1 — 2026-11-21

- **Download links that always work.** Each release now also carries
  `backatit.deb`, `backatit.rpm` and `backatit.tar.gz`, so the commands in the
  README fetch the newest version without being edited for every release.
- Uninstalling a home-directory install (`./install.sh --uninstall` or
  `./purge.sh`) refreshes the icon cache, so GTK apps no longer warn about a
  missing BackAtIt icon afterwards.
- The in-app guide describes away detection on every desktop, not GNOME only.
- Bug reports now have a form on GitHub that asks for the distribution,
  desktop and log lines needed to look into them.

**Downloads**
- `backatit.deb` — Ubuntu, Debian, Linux Mint, Pop!_OS
- `backatit.rpm` — Fedora, openSUSE
- `backatit.tar.gz` — everything else, install with `./install.sh`

## 2.1 — 2026-11-21

**Fixed**
- **The buttons on a locked break work.** While the screen was locked, the
  alarm's own Snooze and Turn off reminders buttons and the hold-to-unlock
  bar did not respond either, so a locked break could only be waited out.
  The lock now keeps everything outside the alarm blocked and lets the
  alarm's own buttons through.

**New defaults** (for new installs; an existing setup keeps its choices)
- **Lock the screen for the whole break** is on. Untick it in Timing for an
  alert you simply dismiss.
- **Start automatically when I log in** is switched on the first time you
  open BackAtIt, so reminders keep running after a reboot.

**Downloads**
- `backatit_2.1_all.deb` — Ubuntu, Debian, Linux Mint, Pop!_OS
- `backatit-2.1-1.noarch.rpm` — Fedora, openSUSE
- `backatit-2.1.tar.gz` — everything else, install with `./install.sh`

## 2.0 — 2026-11-15

BackAtIt now works on every mainstream Linux desktop — GNOME, KDE Plasma,
XFCE, Cinnamon, MATE and Budgie — not just GNOME, and comes as a package for
Fedora and openSUSE as well as Debian and Ubuntu.

**Fixed on KDE Plasma (and other non-GNOME desktops)**
- **The locked break really locks.** On KDE the input lock was never taken,
  so the "locked" break left the keyboard and mouse free. It now waits until
  the alert is actually on screen and then takes it: the Windows key,
  Alt+Tab and the mouse are all held for the whole break.
- **"Skip the break if I'm already away" works.** Idle time was only ever
  asked of GNOME, so on every other desktop it read zero and the break always
  fired. It now comes from whichever source your desktop has: GNOME's own,
  the Wayland idle protocol (KDE Plasma 6, Sway, Hyprland), X11 (XFCE, MATE,
  Cinnamon, Budgie on X11), or the login session as a last resort.

**Everywhere**
- **Notifications clear themselves.** They no longer pile up in your
  notification list: each one disappears after it is shown, and a new one
  replaces the last instead of stacking.
- Missing-dependency messages give the right install command for your
  distribution (apt, dnf, zypper or pacman).

**Downloads**
- `backatit_2.0_all.deb` — Ubuntu, Debian, Linux Mint, Pop!_OS
- `backatit-2.0-1.noarch.rpm` — Fedora, openSUSE
- `backatit-2.0.tar.gz` — everything else, install with `./install.sh`

Releases are now built and published automatically, after the full test
suite passes.

## 1.6 — 2026-08-26

- The bundled user guide is up to date again: it still used the app's old
  name and old file locations, and predated the screen lock.
- The hold-to-unlock duration, the alarm length on a locked break and the
  input lock's safety margin can be set in the config file.

## 1.5.1 — 2026-08-23

- Snooze is back on a locked break. Snoozing abandons the break that has
  started and puts the next one off by your snooze length.

## 1.5 — 2026-08-23

- Alerts size themselves to the screen they land on, with all buttons in one
  row at a matching size.
- Fixed a blank About card when about.conf contained `&` or angle brackets.
- Sound previews use whichever player is installed, not just PipeWire.
- A locked break killed from a console is no longer counted as completed.

## 1.4 — 2026-08-23

- Redrawn alerts: the time left is the largest thing on screen, with a
  progress bar, and the two alerts are colour-coded — amber to get up, green
  to come back.
- The three-second click delay only applies where a stray click would cost
  you something.

## 1.3 — 2026-08-23

- A locked break starts counting down straight away, with a short alarm
  burst instead of a long one.
- Unlocking early with the hold button only ends that break; cut-short
  breaks are counted separately.

## 1.2.1 — 2026-08-23

- Upgrading now really stops the running background app, so the new version
  takes effect immediately rather than at the next login.

## 1.2 — 2026-08-23

- Optional locked break: the alert stays up for the whole break, takes the
  mouse and keyboard and blanks other monitors. Hold the unlock button for
  five seconds to get out early.

## 1.1 — 2026-08-07

- Fixed stale state that could show an out-of-date countdown and refuse to
  start, and a Stop button that cancelled a daily schedule that was not
  running.

## 1.0 — 2026-08-06

- First release.
