#!/usr/bin/env python3
"""The alert texts are free text, and the config file used to be *sourced* by
bash. It is parsed now, but both writers still have to quote correctly, and
nothing in a config file may ever be executed.

These are the cases that would bite.
"""
import importlib.util, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
SB = tempfile.mkdtemp()
shutil.copy(os.path.join(APP, "lib.sh"), SB)

spec = importlib.util.spec_from_file_location("st", os.path.join(APP, "settings.py"))
st = importlib.util.module_from_spec(spec); spec.loader.exec_module(st)
st.CONFIG = os.path.join(SB, "config")
# The bash side sources lib.sh, which settles its own config path on load and
# would migrate SB/config into it. Point that at the sandbox too.
os.environ["XDG_CONFIG_HOME"] = os.path.join(SB, "xdg-config")
os.environ["XDG_STATE_HOME"] = os.path.join(SB, "xdg-state")

fails = []
def ck(desc, got, want):
    if got == want:
        print(f"  ok   {desc}")
    else:
        print(f"  FAIL {desc}\n         got  {got!r}\n         want {want!r}")
        fails.append(desc)

CANARY = os.path.join(SB, "pwned")

NASTY = [
    ("plain", "Take a break!"),
    ("apostrophe", "Don't waste time"),
    ("double quotes", 'She said "get up" now'),
    ("both quotes", """it's a "break", ok?"""),
    ("dollar var", "Break for $HOME minutes"),
    ("command substitution", "hello $(touch %s) world" % CANARY),
    ("backticks", "hello `touch %s` world" % CANARY),
    ("semicolon", "break; touch %s" % CANARY),
    ("backslash", r"a back\slash and \t"),
    ("newline escape", r"line one\nline two"),
    ("unicode", "Take a break — stretch 🚶 now"),
    ("percent and brace", "100% done {ok} [fine]"),
    ("leading hash", "# not a comment"),
    ("equals sign", "a=b=c"),
    ("empty-ish", "   "),
]

print("=== python writes -> bash reads -> value comes back intact ===")
for desc, text in NASTY:
    st.write_config({"BREAK_TITLE": text, "BREAK_MESSAGE": text})
    out = subprocess.run(
        ["bash", "-c",
         'CONFIG="$1"; . "$2/lib.sh"; CONFIG="$1"; load_config; printf "%s" "$BREAK_MESSAGE"',
         "_", st.CONFIG, SB],
        capture_output=True, text=True)
    if out.returncode != 0:
        print(f"  FAIL {desc}: bash could not read the config\n{out.stderr}")
        fails.append(desc); continue
    ck(desc, out.stdout, text)

ck("nothing was executed while reading", os.path.exists(CANARY), False)

print("=== and settings.py reads its own file back ===")
for desc, text in NASTY:
    st.write_config({"BREAK_TITLE": text})
    ck("re-read " + desc, st.read_config().get("BREAK_TITLE"), text)

print("=== lib.sh's own save_config quotes just as safely ===")
danger = "x $(touch %s) `touch %s` 'q' \"d\"" % (CANARY, CANARY)
out = subprocess.run(
    ["bash", "-c",
     'CONFIG="$1"; . "$2/lib.sh"; CONFIG="$1"; load_config; '
     'BREAK_MESSAGE="$DANGER"; save_config; '
     'unset BREAK_MESSAGE; load_config; printf "%s" "$BREAK_MESSAGE"',
     "_", st.CONFIG, SB],
    env={**os.environ, "DANGER": danger}, capture_output=True, text=True)
ck("save_config round trip", out.stdout, danger)
ck("save_config executed nothing", os.path.exists(CANARY), False)

print("=== a blank heading falls back rather than an empty alert ===")
st.write_config({"BREAK_TITLE": "", "WALK_TITLE": ""})
out = subprocess.run(
    ["bash", "-c",
     'CONFIG="$1"; . "$2/lib.sh"; CONFIG="$1"; load_config; '
     'printf "%s|%s" "$BREAK_TITLE" "$WALK_TITLE"',
     "_", st.CONFIG, SB],
    capture_output=True, text=True)
ck("empty headings replaced", out.stdout, "Take a break!|Walk time is up")

print("=== the config file is written private ===")
st.write_config({"BREAK_TITLE": "x"})
ck("mode 0600", oct(os.stat(st.CONFIG).st_mode & 0o777), "0o600")

shutil.rmtree(SB, ignore_errors=True)
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
