#!/usr/bin/env python3
"""idle.py against a fake Wayland compositor on a private socket.

No desktop is needed and none is touched: the compositor here is a few dozen
lines that speak just enough of the protocol to advertise globals, accept the
idle subscription, and send "idled" / "resumed" when told to.
"""
import importlib.util, os, socket, struct, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("idlemod", os.path.join(HERE, "..", "idle.py"))
idlemod = importlib.util.module_from_spec(spec); spec.loader.exec_module(idlemod)

fails = []
def ck(d, got, want):
    if got == want: print(f"  ok   {d} -> {got!r}")
    else: print(f"  FAIL {d} -> got {got!r} want {want!r}"); fails.append(d)


def msg(obj, op, payload=b""):
    return struct.pack("<IHH", obj, op, 8 + len(payload)) + payload


def wl_global(registry, name, iface, version):
    return msg(registry, 0, struct.pack("<I", name) + idlemod._string(iface)
               + struct.pack("<I", version))


class FakeCompositor(threading.Thread):
    """Accepts one client and plays out a script once it has subscribed."""

    def __init__(self, path, globals_, script):
        super().__init__(daemon=True)
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(path); self.server.listen(1)
        self.globals = globals_
        self.script = script          # list of ("idled"|"resumed"|"close", delay)
        self.subscription = None      # (opcode, timeout_ms) the client asked for
        self.done = threading.Event()

    def run(self):
        conn, _ = self.server.accept()
        buf = b""; notif = None
        while notif is None:
            data = conn.recv(4096)
            if not data:
                return
            buf += data
            while len(buf) >= 8:
                obj, op, size = struct.unpack("<IHH", buf[:8])
                if len(buf) < size: break
                body, buf = buf[8:size], buf[size:]
                if obj == 1 and op == 1:          # get_registry
                    registry = struct.unpack("<I", body)[0]
                    for i, (iface, ver) in enumerate(self.globals, 1):
                        conn.sendall(wl_global(registry, i, iface, ver))
                elif obj == 1 and op == 0:        # sync
                    conn.sendall(msg(struct.unpack("<I", body)[0], 0, struct.pack("<I", 0)))
                elif op in (1, 2) and len(body) == 12:   # get_(input_)idle_notification
                    nid, timeout, _seat = struct.unpack("<III", body)
                    self.subscription = (op, timeout); notif = nid
        for event, delay in self.script:
            time.sleep(delay)
            if event == "close":
                break
            conn.sendall(msg(notif, 0 if event == "idled" else 1))
        time.sleep(0.2)
        conn.close(); self.server.close(); self.done.set()


def run_watch(globals_, script, threshold=5):
    tmp = tempfile.mkdtemp()
    sock, state = os.path.join(tmp, "wl"), os.path.join(tmp, "state")
    comp = FakeCompositor(sock, globals_, script); comp.start()
    seen = []
    def sample():
        last = None
        while not comp.done.is_set():
            try: cur = open(state).read().split()[0]
            except OSError: cur = None
            if cur != last and cur is not None: seen.append(cur); last = cur
            time.sleep(0.02)
    sampler = threading.Thread(target=sample, daemon=True); sampler.start()
    rc = idlemod.watch(state, socket_path=sock, threshold=threshold)
    comp.done.wait(5)
    return rc, seen, comp.subscription, os.path.exists(state)


print("=== v2 compositor: input-only idle, idled then resumed ===")
rc, seen, sub, left = run_watch(
    [("wl_compositor", 6), ("wl_seat", 9), ("ext_idle_notifier_v1", 2)],
    [("idled", 0.3), ("resumed", 0.3), ("close", 0.2)], threshold=7)
ck("exit code when the compositor hangs up", rc, 0)
ck("uses get_input_idle_notification on v2", sub[0], 2)
ck("asks for the threshold in ms", sub[1], 7000)
ck("state went active -> idle -> active", seen, ["active", "idle", "active"])
ck("state file removed on the way out", left, False)

print("=== v1 compositor: falls back to the plain request ===")
rc, seen, sub, left = run_watch(
    [("wl_seat", 5), ("ext_idle_notifier_v1", 1)],
    [("idled", 0.3), ("close", 0.2)])
ck("uses get_idle_notification on v1", sub[0], 1)
ck("state went active -> idle", seen, ["active", "idle"])

print("=== idle start time is worked back from the threshold ===")
tmp = tempfile.mkdtemp(); sock = os.path.join(tmp, "wl"); state = os.path.join(tmp, "state")
comp = FakeCompositor(sock, [("wl_seat", 5), ("ext_idle_notifier_v1", 2)],
                      [("idled", 0.2), ("close", 1.0)])
comp.start()
t = threading.Thread(target=idlemod.watch, args=(state,), kwargs={"socket_path": sock, "threshold": 30}, daemon=True)
t.start(); time.sleep(0.8)
since = int(open(state).read().split()[1])
ck("idle since ~30s before the event", abs((time.time() - since) - 30) <= 2, True)
t.join(5)

print("=== a compositor without the protocol ===")
tmp = tempfile.mkdtemp(); sock = os.path.join(tmp, "wl")
comp = FakeCompositor(sock, [("wl_seat", 5), ("org_kde_kwin_idle", 1)], [])
comp.start()
ck("reports unsupported", idlemod.watch(os.path.join(tmp, "s"), socket_path=sock), idlemod.UNSUPPORTED)
ck("no socket at all -> unsupported",
   idlemod.watch(os.path.join(tmp, "s"), socket_path=os.path.join(tmp, "nope")), idlemod.UNSUPPORTED)

print("=== x11 one-shot ===")
saved = os.environ.pop("DISPLAY", None)
ck("no DISPLAY -> no answer", idlemod.x11_idle_seconds(), None)
if saved is not None: os.environ["DISPLAY"] = saved
ck("usage error", idlemod.main(["idle.py"]), 64)

print("FAILURES:", fails or "none")
sys.exit(1 if fails else 0)
