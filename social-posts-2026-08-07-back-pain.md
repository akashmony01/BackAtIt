---
title: Social Posts - My Back Was Killing Me, So I Built Something I Couldn't Ignore
date: 2026-08-07
---

## Twitter Thread

*Post in order, top to bottom. Replace [blog] and [repo] in the last tweet with
real URLs — publish the post first, or the link goes nowhere. All seven are
under 280 characters.*

**1 —**
My back had been aching for weeks from sitting too long, so I built a reminder to make me stand up.

The reminder worked perfectly from day one.

I still never stood up.

Turns out I'd misdiagnosed my own problem — and the real bug wasn't in the code. 🧵

**2 —**
I assumed the reminders weren't reaching me. They were reaching me perfectly.

I was dismissing them *below the level of conscious thought* — one keystroke, gone, never registered.

I'd spent weeks fixing a delivery problem when I had an attention problem.

**3 —**
Claude wrote this to read a number from a system response:

```
[[ $reply =~ ([0-9]+) ]]
```

The reply was `(uint64 44793,)`.

It matched the **64 in the type name**. Not the value.

A whole feature silently did nothing for days. No crash. No log. Just a confident wrong answer.

**4 —**
The fix wasn't "make it louder."

It was making the alert refuse the keyboard entirely:

```python
window.connect("key-press-event", lambda *_: True)
for b in buttons: b.set_can_focus(False)
```

A reminder always lands mid-sentence. If a keystroke can kill it, it will.

**5 —**
I learned that the dangerous bug isn't the one that crashes — it's the one that returns something *plausible*.

A regex matching the wrong digits. A counter printing "0" twice. A dropped config key.

They all looked like answers. So nothing complained. So nobody looked.

**6 —**
This taught me to measure before I fix.

I was certain saving settings was making a button sluggish. Claude measured it: **0.64ms**.

The real cause was a loop checking every 5 seconds. Waking it took the button from ~2700ms → 67ms.

I'd have "optimised" the wrong thing.

**7 —**
Three times a test went red and the product was fine — the *test harness* was broken.

Twice I nearly "fixed" working code to satisfy a lying test.

Check the harness before you believe the failure.

Write-up: [blog]
The app itself (Linux, MIT): [repo]

---

## LinkedIn Post

Today I turned a seventy-line shell script into something a stranger could actually install — and learned more from my own wrong assumptions than from the code.

The back story: I'd been sitting too long, my back hurt, and every break reminder I'd tried had failed. My diagnosis was that they weren't reaching me. I was wrong. They were reaching me perfectly — I was dismissing them below the level of conscious thought, one keystroke at a time, and never registering they'd appeared.

That reframe changed everything. If a reminder isn't firing, you fix the timer. If it fires and gets waved away automatically, no amount of volume helps — you have to make dismissal *require a decision*. The fix wasn't a louder alarm. It was an alert that refuses keyboard input entirely, so only a deliberate action can dismiss it.

Working with Claude on this was genuinely productive and genuinely humbling in both directions.

It caught things I'd never have found — but it also shipped a regex that matched the digits inside a type name rather than the value it was reading. An entire feature silently did nothing for days. No crash, no log, just a confident wrong answer. The same shape appeared twice more: a counter that printed "0" twice, a config key silently dropped.

Three separate times, a test suite went red and the product was fine — the test harness had mangled string escaping. Twice I nearly "fixed" working code to satisfy a broken test.

The lessons I'm taking forward:

→ The dangerous bug returns a plausible answer, not an error. Anything crossing a boundary — a subprocess, a config file, another language — is wrong until you've seen the actual value.

→ Measure before you fix. I was certain a disk write was my bottleneck. It was 0.64ms against a 5-second poll. Four orders of magnitude off.

→ When a test fails, verify the harness before you trust it.

→ Design for the moment the feature matters. An interruption tool has to work while you're mid-flow, because that's the only time it fires. Testing it while idle proves nothing.

Full reflection: [link]

---

## Reddit Post

**I spent weeks fixing the wrong problem, and the bug was in my head not my code**

My back had been hurting from sitting too long, so a while back I wrote a small script to remind me to stand up. Simple thing — sleep, play a sound, show a popup, repeat.

It worked. It fired every single time. I still never stood up.

My theory was that it needed to be louder. Longer sound, bigger window. I spent an embarrassing amount of time on that theory before I understood what was actually happening: the reminders were reaching me fine. I was dismissing them *without ever consciously registering they'd appeared*. A reminder always shows up mid-sentence, and if it can be dismissed with a keystroke, your next keystroke kills it and you never know.

That's a delivery problem versus an attention problem, and I'd been solving the wrong one.

The actual fix was making the alert refuse keyboard input entirely — only a deliberate mouse click dismisses it, and even then the buttons stay dead for a few seconds so a click already in flight can't land on them. Rude by design, because anything polite enough to ignore *gets* ignored.

I built the rest of it with Claude, which was useful and also a good lesson in not trusting confident output. At one point it wrote a regex to pull a number out of a system response — the response looked like `(uint64 44793,)` and the pattern matched the **64 in the type name**. An entire feature silently did nothing for days. It never crashed. It just returned a plausible number, every time, so nothing complained.

That kept happening in different costumes: a counter that printed "0" twice because of how `grep -c` handles exit codes, a config key silently dropped by a string comparison. All of them produced output that *looked* like an answer.

The other thing that caught me out: three separate times a test suite went red and the code was fine — the test harness itself had mangled string escaping. Twice I nearly "fixed" working software to satisfy a broken test.

Biggest takeaways, if they're useful to anyone else:

- The bug that survives longest is the one that returns something plausible, not the one that crashes
- Measure before you fix — I was certain a disk write was slow; it was 0.64ms against a 5-second poll
- When a test fails, check the harness before you believe it
- Design for the moment the feature actually matters, not the moment that's convenient to test

Full write-up here if you want the longer version: [link]
