#!/usr/bin/env python3
"""How long since you last touched the keyboard or mouse - on desktops where
GNOME's Mutter is not there to ask.

Two jobs, both standard library only:

  idle.py x11
      One-shot. Prints seconds idle from the X11 MIT-SCREEN-SAVER extension
      (XFCE, MATE, Cinnamon, Budgie and any other X11 session). Exits 1 when
      the extension is missing - which it is under XWayland, so a Wayland
      session cannot be misread through it.

  idle.py watch STATEFILE
      Long-running. Speaks the Wayland ext-idle-notify-v1 protocol (KDE
      Plasma 6, Sway, Hyprland and other newer compositors) and keeps
      STATEFILE saying either "active" or "idle <epoch you went idle>".
      The protocol only announces "went idle" / "came back", never a number,
      so it asks to be told after THRESHOLD seconds without input and works
      the start time back from that. Every reading above THRESHOLD is exact.
      Exits 3 when the compositor does not offer the protocol, and on its own
      when the daemon that started it goes away.

The Wayland side talks the wire protocol over the socket directly instead of
going through libwayland: it is a handful of fixed-format messages, and doing
it this way means nothing new to install.
"""
import os
import select
import signal
import socket
import struct
import sys
import time

THRESHOLD = 5            # seconds without input before the compositor tells us
UNSUPPORTED = 3          # exit code: this compositor has no idle protocol


# ----------------------------------------------------------------------- X11
def x11_idle_seconds():
    import ctypes
    import ctypes.util

    if not os.environ.get("DISPLAY"):
        return None
    x11_name = ctypes.util.find_library("X11")
    xss_name = ctypes.util.find_library("Xss")
    if not x11_name or not xss_name:
        return None
    x11 = ctypes.cdll.LoadLibrary(x11_name)
    xss = ctypes.cdll.LoadLibrary(xss_name)

    class Info(ctypes.Structure):
        _fields_ = [("window", ctypes.c_ulong), ("state", ctypes.c_int),
                    ("kind", ctypes.c_int), ("til_or_since", ctypes.c_ulong),
                    ("idle", ctypes.c_ulong), ("event_mask", ctypes.c_ulong)]

    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XDefaultRootWindow.restype = ctypes.c_ulong
    x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    xss.XScreenSaverQueryExtension.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
    xss.XScreenSaverAllocInfo.restype = ctypes.POINTER(Info)
    xss.XScreenSaverQueryInfo.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(Info)]
    x11.XFree.argtypes = [ctypes.c_void_p]

    dpy = x11.XOpenDisplay(None)
    if not dpy:
        return None
    try:
        ev, err = ctypes.c_int(), ctypes.c_int()
        # Ask first: querying a missing extension makes Xlib print a warning.
        if not xss.XScreenSaverQueryExtension(dpy, ctypes.byref(ev), ctypes.byref(err)):
            return None
        info = xss.XScreenSaverAllocInfo()
        if not info:
            return None
        try:
            if not xss.XScreenSaverQueryInfo(dpy, x11.XDefaultRootWindow(dpy), info):
                return None
            return info.contents.idle // 1000
        finally:
            x11.XFree(info)
    finally:
        x11.XCloseDisplay(dpy)


# ------------------------------------------------------------------- Wayland
def _string(s):
    data = s.encode() + b"\0"
    pad = (4 - len(data) % 4) % 4
    return struct.pack("<I", len(data)) + data + b"\0" * pad


class Wayland:
    """Just enough of a Wayland client to subscribe to idle notifications."""

    DISPLAY = 1

    def __init__(self, path):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
        self.buf = b""
        self.next_id = 2

    def new_id(self):
        n = self.next_id
        self.next_id += 1
        return n

    def send(self, obj, opcode, payload=b""):
        self.sock.sendall(struct.pack("<IHH", obj, opcode, 8 + len(payload)) + payload)

    def read(self, timeout=None):
        """Yield (object, opcode, body) for every complete message available.

        Raises EOFError when the compositor hangs up."""
        ready, _, _ = select.select([self.sock], [], [], timeout)
        if ready:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise EOFError
            self.buf += chunk
        while len(self.buf) >= 8:
            obj, opcode, size = struct.unpack("<IHH", self.buf[:8])
            if size < 8 or len(self.buf) < size:
                break
            body, self.buf = self.buf[8:size], self.buf[size:]
            yield obj, opcode, body

    def globals(self):
        """Every global the compositor advertises: {interface: (name, version)}."""
        registry, callback = self.new_id(), self.new_id()
        self.send(self.DISPLAY, 1, struct.pack("<I", registry))   # get_registry
        self.send(self.DISPLAY, 0, struct.pack("<I", callback))   # sync
        found = {}
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            for obj, opcode, body in self.read(1):
                if obj == registry and opcode == 0:                # global
                    name, length = struct.unpack("<II", body[:8])
                    iface = body[8:8 + length - 1].decode()
                    off = 8 + ((length + 3) & ~3)
                    version = struct.unpack("<I", body[off:off + 4])[0]
                    found[iface] = (name, version)
                elif obj == callback:                              # done
                    return registry, found
        raise TimeoutError("compositor did not answer")

    def bind(self, registry, name, iface, version):
        new = self.new_id()
        self.send(registry, 0, struct.pack("<I", name) + _string(iface)
                  + struct.pack("<II", version, new))
        return new


def write_state(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(text + "\n")
    os.replace(tmp, path)


def watch(state_path, parent=None, socket_path=None, threshold=THRESHOLD):
    if socket_path is None:
        display = os.environ.get("WAYLAND_DISPLAY")
        if not display:
            return UNSUPPORTED
        runtime = os.environ.get("XDG_RUNTIME_DIR", "")
        socket_path = display if display.startswith("/") else os.path.join(runtime, display)
    try:
        wl = Wayland(socket_path)
        registry, found = wl.globals()
    except (OSError, TimeoutError, EOFError):
        return UNSUPPORTED
    if "ext_idle_notifier_v1" not in found or "wl_seat" not in found:
        return UNSUPPORTED

    seat = wl.bind(registry, found["wl_seat"][0], "wl_seat", 1)
    nname, nversion = found["ext_idle_notifier_v1"]
    notifier = wl.bind(registry, nname, "ext_idle_notifier_v1", min(nversion, 2))
    notification = wl.new_id()
    # v2 has get_input_idle_notification, which ignores idle inhibitors: a
    # playing video holds the screen awake, but you are still not touching
    # anything - and that is the question being asked. v1 only has the
    # inhibitor-respecting request.
    opcode = 2 if nversion >= 2 else 1
    wl.send(notifier, opcode, struct.pack("<III", notification, int(threshold * 1000), seat))
    write_state(state_path, "active")

    try:
        while True:
            if parent is not None and os.getppid() != parent:
                break
            for obj, op, body in wl.read(10):
                if obj == notification and op == 0:      # idled
                    write_state(state_path, "idle %d" % int(time.time() - threshold))
                elif obj == notification and op == 1:    # resumed
                    write_state(state_path, "active")
                elif obj == Wayland.DISPLAY and op == 0:  # protocol error
                    return 1
    except (EOFError, OSError):
        pass
    finally:
        try:
            os.remove(state_path)
        except OSError:
            pass
    return 0


def main(argv):
    if len(argv) >= 2 and argv[1] == "x11":
        secs = x11_idle_seconds()
        if secs is None:
            return 1
        print(secs)
        return 0
    if len(argv) >= 3 and argv[1] == "watch":
        # Stopped with SIGTERM by the daemon: unwind so the state file is
        # removed rather than left claiming an idle that is no longer tracked.
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        return watch(argv[2], parent=os.getppid())
    print("usage: idle.py x11 | idle.py watch STATEFILE", file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv))
