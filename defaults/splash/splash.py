#!/usr/bin/env python3
"""WoW Forever launch splash (Decky plugin "WoW Splash").

Started by the plugin's launch wrapper (Steam launch options: `launch.sh <appid> %command%`).
Covers the Proton console / Battle.net windows until WoW's own window is up. Steps aside
for Battle.net windows that need the player (login, update, EULA, Install, Play) and comes
back when Wow.exe starts. The game folder (for gx.log) is found from the running Wow.exe,
so WoW can be installed anywhere. Art is bundled in art/. Holding View + Menu on the
Deck's controller closes the splash (read from its hidraw device).

Progress is stage based (processes / log lines / windows seen), interpolated with the
average timings of the last 5 launches, and smoothed so the bar never stalls.

Gaming Mode: a normal fullscreen window with its own STEAM_GAME id (see SPLASH_APPID). gamescope would focus
each newly mapped launcher window (every focus change = a fade), so FocusPin keeps the
splash as gamescope's focus (window pin + first app id, on Steam's root :0; event driven,
no polling). Steam's values are restored after.
Desktop Mode: an override-redirect popup re-raised every frame (Wine draws its own tiny
override-redirect popups, which would otherwise end up on top).

No live log file; at exit a short record of the launch goes to last-launch.json (for bug
reports). `--preview` fakes every probe for a desktop test (prints its log to the terminal).
"""
import ctypes
import ctypes.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("GDK_BACKEND", "x11")
import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkX11", "3.0")
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib, GdkX11  # noqa: E402
import cairo  # noqa: E402

APPID = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 0
# gamescope draws an override-redirect popup over the focus window when their app ids
# match (Wine's tiny "Battle.net" popups). The splash gets its own id so none qualify;
# the focus pin matches by window id, so it still keeps the splash in front.
SPLASH_APPID = (APPID + 1) & 0xFFFFFFFF
TIMEOUT = 150      # step aside for good if WoW isn't running by then (not counting time aside)
LOGIN_GRACE = 6    # auto-login flashes the login window ~3s; only step aside if it stays
PLAY_GRACE = 2     # manual mode: a big Battle.net window up this long = waiting for Play
GONE_GRACE = 5     # Battle.net and the game both gone this long -> the launch was closed
DATA_DIR = os.environ.get("WOW_SPLASH_DATA") or os.path.expanduser("~/.local/share/decky-wow-splash")
SETTINGS = os.path.join(os.environ.get("WOW_SPLASH_SETTINGS") or DATA_DIR, "settings.json")
TIMINGS = os.path.join(DATA_DIR, f"timings-{APPID}.json")
REPORT = os.path.join(DATA_DIR, "last-launch.json")
ART = os.path.join(os.path.dirname(os.path.abspath(__file__)), "art")
STUCK_GRACE = 20   # auto mode: a big Battle.net window up this long = it needs the player
CLOSE_HOLD = 1.5   # hold View + Menu this long to close the splash
WOW_WINDOW = "^World of Warcraft$"
LOGIN_WINDOW = "Battle.net Login|^Log In$|Login$"
BNET_CLASS = "battle\\.net"          # Wine's WM_CLASS = exe name; xdotool matches case-insensitively
MIN_W, MIN_H = 300, 200               # smaller Battle.net windows are popups/tooltips


def app_settings():
    """This shortcut's options from the plugin: {"auto": bool} (Battle.net starts the game)."""
    try:
        with open(SETTINGS) as f:
            return json.load(f).get("apps", {}).get(str(APPID), {})
    except (OSError, ValueError, AttributeError):
        return {}


# Milestones in order: (key, status text shown while waiting for the NEXT one,
# default seconds from Play; replaced by the average of recent launches).
MILESTONES = [
    ("start",  "Starting…",                    0),
    ("wine",   "Starting Battle.net…",         3),    # explorer.exe
    ("bnet",   "Launching World of Warcraft…", 7),    # Battle.net.exe / Agent.exe
    ("wow",    "Loading World of Warcraft…",   17),   # Wow.exe
    ("gfx",    "Opening World of Warcraft…",   24),   # gx.log: graphics device created
    ("window", "Ready",                        25),   # WoW window visible -> close splash
]
KEYS = [k for k, _, _ in MILESTONES]
WOW = KEYS.index("wow")
BNET = KEYS.index("bnet")

GAMING_MODE = bool(os.environ.get("GAMESCOPE_WAYLAND_DISPLAY")) or \
    os.environ.get("XDG_CURRENT_DESKTOP", "").lower() == "gamescope"
STEAM_DISPLAY = os.environ.get("SPLASH_STEAM_DISPLAY", ":0")


LOG = []   # this launch's lines, written once at exit (last-launch.json)


def log(*a):
    line = f"{time.monotonic() - START:5.1f}s " + " ".join(str(x) for x in a)
    LOG.append(line)
    del LOG[:-80]
    if any(a.startswith("--preview") for a in sys.argv):
        print(time.strftime("%H:%M:%S"), line, flush=True)


START = time.monotonic()


# ---------- probes (cheap: /proc, one file, one xdotool call) ----------
def procs():
    """Names of the launch-relevant processes running: explorer.exe, Agent.exe,
    Battle.net.exe and Wow.exe. Also remembers the game's pid in procs.wow_pid."""
    found = set()
    procs.wow_pid = None
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/comm") as f:
                comm = f.read().strip()
            if comm in ("explorer.exe", "Agent.exe", "Wow.exe"):
                found.add(comm)
                if comm == "Wow.exe":
                    procs.wow_pid = pid
            elif comm == "CrBrowserMain" or comm.startswith("Battle.net"):
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    if b"Battle.net.exe" in f.read():
                        found.add("Battle.net.exe")
        except OSError:
            pass
    return found


procs.wow_pid = None


def visible_windows(regex, by="--name"):
    try:
        out = subprocess.run(["xdotool", "search", "--onlyvisible", by, regex],
                             capture_output=True, text=True, timeout=2).stdout
        return [int(w) for w in out.split()]
    except Exception:
        return []


def big_bnet_windows():
    """Visible Battle.net windows of a real size (login, main, update, EULA...)."""
    ids = visible_windows(BNET_CLASS, "--classname")
    big = []
    for w in ids:
        try:
            out = subprocess.run(["xdotool", "getwindowgeometry", "--shell", str(w)],
                                 capture_output=True, text=True, timeout=2).stdout
            g = dict(l.split("=", 1) for l in out.split() if "=" in l)
            if int(g.get("WIDTH", 0)) >= MIN_W and int(g.get("HEIGHT", 0)) >= MIN_H:
                big.append(w)
        except Exception:
            pass
    return big


def game_dir(pid):
    """Unix folder of the running Wow.exe (`.../_forever_`): its cwd, else its Windows path mapped through
    the Wine prefix (WINEPREFIX / STEAM_COMPAT_DATA_PATH from its environment)."""
    try:
        cwd = os.readlink(f"/proc/{pid}/cwd")
        if os.path.isdir(os.path.join(cwd, "Logs")) or os.path.isfile(os.path.join(cwd, "Config.wtf")):
            return cwd
    except OSError:
        pass
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            exe = f.read().split(b"\0")[0].decode(errors="replace")
        with open(f"/proc/{pid}/environ", "rb") as f:
            env = dict(kv.split(b"=", 1) for kv in f.read().split(b"\0") if b"=" in kv)
    except OSError:
        return None
    if exe.startswith("/"):
        return os.path.dirname(exe)
    if len(exe) < 3 or exe[1] != ":":
        return None
    prefix = env.get(b"WINEPREFIX", b"").decode()
    if not prefix and env.get(b"STEAM_COMPAT_DATA_PATH"):
        prefix = os.path.join(env[b"STEAM_COMPAT_DATA_PATH"].decode(), "pfx")
    if not prefix:
        return None
    drive = os.path.join(prefix, "dosdevices", exe[0].lower() + ":")
    if not os.path.isdir(drive):
        drive = os.path.join(prefix, "drive_" + exe[0].lower())
    return os.path.join(drive, *exe[3:].split("\\")[:-1])


def gfx_ready(since):
    """gx.log from this launch says the graphics device is up (written live, unlike
    General.log). Folder not found: the window milestone covers it."""
    pid = procs.wow_pid
    d = gfx_ready.dirs.get(pid) if pid else None
    if pid and pid not in gfx_ready.dirs:
        d = gfx_ready.dirs[pid] = game_dir(pid)
        log("game folder", d)
    if not d:
        return False
    gx = os.path.join(d, "Logs", "gx.log")
    try:
        if os.stat(gx).st_mtime < since:
            return False
        with open(gx, errors="replace") as f:
            return "Device Create Successful" in f.read()
    except OSError:
        return False


gfx_ready.dirs = {}


# ---------- X properties (ctypes Xlib, no extra packages) ----------
XA_CARDINAL = 6
_x11 = ctypes.cdll.LoadLibrary(ctypes.util.find_library("X11"))
_x11.XOpenDisplay.restype = ctypes.c_void_p
_x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
_x11.XDefaultRootWindow.restype = ctypes.c_ulong
_x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
_x11.XInternAtom.restype = ctypes.c_ulong
_x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
_x11.XChangeProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
                                 ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
_x11.XDeleteProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong]
_x11.XGetWindowProperty.argtypes = [
    ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long, ctypes.c_long, ctypes.c_int,
    ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
    ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_void_p)]
_x11.XFree.argtypes = [ctypes.c_void_p]
_x11.XFlush.argtypes = [ctypes.c_void_p]


def get_cardinal(dpy, win, name):
    atom = _x11.XInternAtom(dpy, name.encode(), 0)
    typ, fmt, n, after = ctypes.c_ulong(), ctypes.c_int(), ctypes.c_ulong(), ctypes.c_ulong()
    data = ctypes.c_void_p()
    if _x11.XGetWindowProperty(dpy, win, atom, 0, 1, 0, XA_CARDINAL, ctypes.byref(typ),
                               ctypes.byref(fmt), ctypes.byref(n), ctypes.byref(after),
                               ctypes.byref(data)) != 0:
        return None
    value = ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))[0] if data and n.value else None
    if data:
        _x11.XFree(data)
    return value


def set_cardinal(dpy, win, name, value):
    """Set a 32-bit CARDINAL property, or delete it when value is None."""
    atom = _x11.XInternAtom(dpy, name.encode(), 0)
    if value is None:
        _x11.XDeleteProperty(dpy, win, atom)
    else:
        _x11.XChangeProperty(dpy, win, atom, XA_CARDINAL, 32, 0, (ctypes.c_ulong * 1)(value), 1)
    _x11.XFlush(dpy)


XA_CARDINAL_LIST_MAX = 64
PROPERTY_NOTIFY = 28
PROPERTY_CHANGE_MASK = 1 << 22
_x11.XSelectInput.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_long]
_x11.XConnectionNumber.argtypes = [ctypes.c_void_p]
_x11.XPending.argtypes = [ctypes.c_void_p]
_x11.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]


def get_cardinals(dpy, win, name):
    """A CARDINAL[] property as a list, or None if it isn't set."""
    atom = _x11.XInternAtom(dpy, name.encode(), 0)
    typ, fmt, n, after = ctypes.c_ulong(), ctypes.c_int(), ctypes.c_ulong(), ctypes.c_ulong()
    data = ctypes.c_void_p()
    if _x11.XGetWindowProperty(dpy, win, atom, 0, XA_CARDINAL_LIST_MAX, 0, XA_CARDINAL,
                               ctypes.byref(typ), ctypes.byref(fmt), ctypes.byref(n),
                               ctypes.byref(after), ctypes.byref(data)) != 0:
        return None
    vals = None
    if data and typ.value == XA_CARDINAL:
        arr = ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))
        vals = [arr[i] & 0xFFFFFFFF for i in range(n.value)]
    if data:
        _x11.XFree(data)
    return vals


def set_cardinals(dpy, win, name, values):
    """Set a CARDINAL[] property, or delete it when values is None."""
    atom = _x11.XInternAtom(dpy, name.encode(), 0)
    if values is None:
        _x11.XDeleteProperty(dpy, win, atom)
    else:
        _x11.XChangeProperty(dpy, win, atom, XA_CARDINAL, 32, 0,
                             (ctypes.c_ulong * len(values))(*values), len(values))
    _x11.XFlush(dpy)


class FocusPin:
    """Keeps gamescope's focus on the splash, via two properties on Steam's root (:0):
      GAMESCOPECTRL_BASELAYER_WINDOW  window id gamescope focuses first (matched by id only,
                                      so the game display's xid works)
      GAMESCOPECTRL_BASELAYER_APPID   app ids gamescope falls back to when that is 0
    Steam resets both when launcher windows open. The splash's app id goes first in the
    list too, so a reset never moves focus. Root PropertyNotify events (no polling) put
    our values back the moment Steam writes; Steam's latest values are restored on release."""
    WIN = "GAMESCOPECTRL_BASELAYER_WINDOW"
    APPS = "GAMESCOPECTRL_BASELAYER_APPID"
    MAX_FIXES = 20     # per 2 s; if Steam keeps fighting back, stop instead of looping

    def __init__(self, display_name):
        self.display_name = display_name
        self.dpy = None
        self.active = False
        self.xid = None
        self.steam_win = None    # Steam's own values, restored on release
        self.steam_apps = None
        self.fixes = []

    def _open(self):
        if self.dpy is None:
            dpy = _x11.XOpenDisplay(self.display_name.encode())
            if not dpy:
                raise RuntimeError(f"can't open display {self.display_name}")
            self.dpy, self.root = dpy, _x11.XDefaultRootWindow(dpy)
            self.atoms = {_x11.XInternAtom(dpy, a.encode(), 0) for a in (self.WIN, self.APPS)}
            self.ev = (ctypes.c_long * 24)()
            _x11.XSelectInput(dpy, self.root, PROPERTY_CHANGE_MASK)
            _x11.XFlush(dpy)
            GLib.io_add_watch(_x11.XConnectionNumber(dpy), GLib.IO_IN, self._on_x)
        return self.dpy, self.root

    def _ours(self):
        return [SPLASH_APPID] + [a for a in (self.steam_apps or []) if a != SPLASH_APPID]

    def _apply(self):
        dpy, root = self.dpy, self.root
        set_cardinal(dpy, root, self.WIN, self.xid)
        set_cardinals(dpy, root, self.APPS, self._ours())

    def pin(self, xid):
        try:
            dpy, root = self._open()
            if not self.active:
                self.steam_win = get_cardinal(dpy, root, self.WIN)
                self.steam_apps = get_cardinals(dpy, root, self.APPS)
                log("steam focus before: window", self.steam_win, "apps", self.steam_apps)
            self.active, self.xid = True, xid
            self._apply()
            log("focus pinned")
        except Exception as e:
            log("focus pin error:", e)

    def _on_x(self, *_):
        """X events on Steam's root: re-pin right away if Steam changed our values."""
        changed = False
        while _x11.XPending(self.dpy):
            _x11.XNextEvent(self.dpy, self.ev)
            if (self.ev[0] & 0xFFFFFFFF) == PROPERTY_NOTIFY and self.ev[5] in self.atoms:
                changed = True
        if changed and self.active:
            self._hold()
        return True

    def _hold(self):
        try:
            dpy, root = self.dpy, self.root
            win = get_cardinal(dpy, root, self.WIN)
            apps = get_cardinals(dpy, root, self.APPS)
            bad = []
            if win != self.xid:
                self.steam_win = win
                bad.append(f"window={win}")
            if not apps or apps[0] != SPLASH_APPID:
                self.steam_apps = apps
                bad.append(f"apps={apps}")
            if not bad:
                return
            now = time.monotonic()
            self.fixes = [t for t in self.fixes if now - t < 2] + [now]
            if len(self.fixes) > self.MAX_FIXES:
                log("steam keeps resetting focus; no longer re-pinning")
                self.active = False
                return
            log("steam changed", ", ".join(bad), "-> re-pin")
            self._apply()
        except Exception as e:
            log("focus hold error:", e)

    def release(self):
        """Restore Steam's values. Safe to call repeatedly."""
        if not self.active and self.xid is None:
            return
        try:
            set_cardinal(self.dpy, self.root, self.WIN, self.steam_win)
            set_cardinals(self.dpy, self.root, self.APPS, self.steam_apps)
            log("focus released")
        except Exception as e:
            log("focus release error:", e)
        self.active, self.xid = False, None


class NoPin:
    def pin(self, xid): pass
    def release(self): pass


class CloseCombo:
    """Watches the Steam Deck controller (Valve 28de:1205, its 64-byte input reports) for
    View + Menu held CLOSE_HOLD seconds. Reads queued reports every 100 ms; read-only,
    Steam keeps working as usual. Absent controller / no access: does nothing."""
    VIEW, MENU = 0x10, 0x40        # report byte 9 (hid-steam: BTN_SELECT, BTN_START)

    def __init__(self, on_close):
        self.on_close = on_close
        self.fds = []
        self.since = None
        for dev in sorted(os.listdir("/sys/class/hidraw")) if os.path.isdir("/sys/class/hidraw") else []:
            try:
                with open(f"/sys/class/hidraw/{dev}/device/uevent") as f:
                    if "28DE:00001205" not in f.read().upper():
                        continue
                self.fds.append(os.open(f"/dev/{dev}", os.O_RDONLY | os.O_NONBLOCK))
            except OSError:
                pass
        log("controller devices", len(self.fds))
        if self.fds:
            GLib.timeout_add(100, self.tick)

    def available(self):
        return bool(self.fds)

    def held(self):
        pressed = None
        for fd in self.fds:
            try:
                while True:
                    r = os.read(fd, 64)
                    if len(r) >= 10 and r[0] == 0x01 and r[2] == 0x09:   # Deck state report
                        pressed = (r[9] & (self.VIEW | self.MENU)) == (self.VIEW | self.MENU)
            except BlockingIOError:
                pass
            except OSError:
                pass
        return pressed

    def tick(self):
        h = self.held()
        if h is None:        # no new report: keep the last state
            h = self.since is not None
        if not h:
            self.since = None
        else:
            self.since = self.since or time.monotonic()
            if time.monotonic() - self.since >= CLOSE_HOLD:
                self.close()
                self.on_close()
                return False
        return True

    def close(self):
        for fd in self.fds:
            try:
                os.close(fd)
            except OSError:
                pass
        self.fds = []


def write_report(why, splash):
    """One small JSON record of this launch, overwritten each time (used by Report a bug)."""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(REPORT, "w") as f:
            json.dump({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "appid": APPID,
                       "gaming_mode": GAMING_MODE, "auto": splash.auto if splash else None,
                       "result": why, "reached": splash.reached if splash else {},
                       "log": LOG}, f, indent=1)
    except OSError:
        pass


# ---------- progress model ----------
def load_timings():
    """Expected seconds-from-Play per milestone: defaults, averaged with recent runs,
    kept strictly increasing."""
    t = {k: d for k, _, d in MILESTONES}
    try:
        with open(TIMINGS) as f:
            runs = json.load(f)
        for k in t:
            vals = [r[k] for r in runs if k in r]
            if vals:
                t[k] = sum(vals) / len(vals)
    except (OSError, ValueError):
        pass
    t["start"] = 0
    for prev, k in zip(KEYS, KEYS[1:]):
        t[k] = max(t[k], t[prev] + 0.5)
    return t


def save_timings(reached):
    try:
        with open(TIMINGS) as f:
            runs = json.load(f)
    except (OSError, ValueError):
        runs = []
    runs.append(reached)
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(TIMINGS, "w") as f:
            json.dump(runs[-5:], f, indent=1)
    except OSError as e:
        log("can't save timings:", e)


# ---------- window ----------
class Splash(Gtk.Window):
    def __init__(self):
        super().__init__(title="WoW Forever Splash",
                         type=Gtk.WindowType.TOPLEVEL if GAMING_MODE else Gtk.WindowType.POPUP)
        self.focus = FocusPin(STEAM_DISPLAY) if GAMING_MODE else NoPin()
        self.t0 = time.monotonic()
        self.wall0 = time.time()
        self.t = load_timings()
        self.stage, self.stage_at = 0, 0.0
        self.reached = {}
        self.calibrate = True          # save timings unless the login window paused us
        self.auto = app_settings().get("auto", False)   # Battle.net starts the game by itself
        self.seen = {}                 # aside reason -> since when its window is up
        self.aside_at = None           # set while hidden (login window / waiting for Play)
        self.gone_since = None         # Battle.net and the game both gone since
        self.result = "closed"
        self.ticks = 0
        self.shown = 0.0               # smoothed percentage drawn on screen
        self.done = False
        self.drawn_key = None          # what the bar strip last showed
        log("expected", {k: round(v, 1) for k, v in self.t.items()})
        log("gaming mode", GAMING_MODE, "display", os.environ.get("DISPLAY"), "appid", APPID,
            "auto", self.auto)

        self.hero = GdkPixbuf.Pixbuf.new_from_file(os.path.join(ART, "hero.jpg"))
        self.logo = GdkPixbuf.Pixbuf.new_from_file(os.path.join(ART, "logo.png"))
        self.bg_cache = None  # (w, h, surface)

        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_accept_focus(False)
        if GAMING_MODE:
            self.set_default_size(1280, 800)
            self.fullscreen()
        else:
            scr = Gdk.Screen.get_default()
            self.move(0, 0)
            self.set_default_size(scr.get_width(), scr.get_height())
        self.area = Gtk.DrawingArea()
        self.area.connect("draw", self.on_draw)
        self.add(self.area)
        self.connect("realize", self.on_realize)
        self.connect("destroy", Gtk.main_quit)

        self.combo = CloseCombo(lambda: self.finish("closed with View + Menu"))
        GLib.timeout_add(33, self.tick_anim)
        GLib.timeout_add(500, self.tick_state)

    def xid(self):
        return self.get_window().get_xid()

    def on_realize(self, *_):
        xdpy = GdkX11.X11Display.get_xdisplay(self.get_display())
        try:
            set_cardinal(ctypes.c_void_p(hash(xdpy)), self.xid(), "STEAM_GAME", SPLASH_APPID)
        except Exception as e:
            log("STEAM_GAME prop error:", e)
        self.focus.pin(self.xid())

    def elapsed(self):
        return time.monotonic() - self.t0

    # ----- state -----
    def reach(self, key):
        idx = KEYS.index(key)
        if idx <= self.stage:
            return
        now = self.elapsed()
        for k in KEYS[1:idx + 1]:          # skipped milestones count as reached now
            self.reached.setdefault(k, round(now, 1))
        self.stage, self.stage_at = idx, now
        log("milestone", key, f"{now:.1f}s")

    def update_milestones(self):
        """Returns False once the launch is over without WoW: the game closed after
        starting, or Battle.net was closed before it started it."""
        p = procs()
        if "explorer.exe" in p:
            self.reach("wine")
        if "Battle.net.exe" in p or "Agent.exe" in p:
            self.reach("bnet")
        if "Wow.exe" not in p:
            if self.stage >= WOW:
                return False
            if self.stage >= BNET and not p & {"Battle.net.exe", "Agent.exe"}:
                self.gone_since = self.gone_since or time.monotonic()
                return time.monotonic() - self.gone_since < GONE_GRACE
            self.gone_since = None
            return True
        self.reach("wow")
        if gfx_ready(self.wall0):
            self.reach("gfx")
        if visible_windows(WOW_WINDOW):
            self.reach("window")
        return True

    def window_up(self, reason, regex, grace):
        """True once a window matching regex has been visible for `grace` seconds."""
        if visible_windows(regex):
            self.seen.setdefault(reason, time.monotonic())
            return time.monotonic() - self.seen[reason] > grace
        self.seen.pop(reason, None)
        return False

    def update_aside(self):
        """Hide while Battle.net needs the player: its login window, or any big Battle.net
        window (main window waiting for Play, update, EULA, Install...) that stays up:
        right away unless Battle.net starts the game by itself, else after STUCK_GRACE.
        That time isn't load time. Back as soon as the game starts."""
        why = None
        if BNET <= self.stage < WOW:
            if self.window_up("login", LOGIN_WINDOW, LOGIN_GRACE):
                why = "login"
            elif self.window_up_ids("bnet", big_bnet_windows(), STUCK_GRACE if self.auto else PLAY_GRACE):
                why = "battle.net window"
        if why:
            self.calibrate = False
        if why and self.aside_at is None:
            log(why, "-> hide")
            self.focus.release()
            self.hide()
            self.aside_at = time.monotonic()
        elif not why and self.aside_at is not None:
            log("back -> show")
            self.show_all()
            self.focus.pin(self.xid())
            self.t0 += time.monotonic() - self.aside_at
            self.aside_at = None

    def window_up_ids(self, reason, ids, grace):
        if ids:
            self.seen.setdefault(reason, time.monotonic())
            return time.monotonic() - self.seen[reason] > grace
        self.seen.pop(reason, None)
        return False

    def tick_state(self):
        if self.done:
            return False
        self.ticks += 1
        if self.aside_at is not None and self.ticks % 4:
            return True     # aside (maybe for a long install/update): check every 2 s
        if not self.update_milestones():
            self.finish("WoW closed" if self.stage >= WOW else "Battle.net closed")
        else:
            self.update_aside()
            if KEYS[self.stage] == "window":
                if self.calibrate:
                    save_timings(self.reached)
                self.finish("WoW window open")
            elif self.stage < WOW and self.aside_at is None and self.elapsed() > TIMEOUT:
                self.finish("timeout before WoW started, stepping aside")
        return not self.done

    def finish(self, why):
        if self.done:
            return
        log("finish:", why)
        self.result = why
        write_report(why, self)
        self.focus.release()
        self.done = True
        self.shown = 100.0
        self.area.queue_draw()
        GLib.timeout_add(150, Gtk.main_quit)

    # ----- animation -----
    def target_pct(self):
        if self.stage + 1 >= len(KEYS):
            return 100.0
        a, b = self.t[KEYS[self.stage]], self.t[KEYS[self.stage + 1]]
        frac = min(0.95, (self.elapsed() - self.stage_at) / max(0.5, b - a))
        return (a + frac * (b - a)) / self.t[KEYS[-1]] * 100

    def tick_anim(self):
        """Smooths the bar; redraws only the bar strip, and only when what it shows changes."""
        if self.done:
            return False
        win = self.get_window()
        if not GAMING_MODE and self.aside_at is None and win:
            win.raise_()
        self.shown += (self.target_pct() - self.shown) * 0.15
        w, h = self.area.get_allocated_width(), self.area.get_allocated_height()
        bx, by, bw, bh, text_y, _ = self.layout(w, h)
        key = (int(bw * min(100, self.shown) / 100), self.stage, w, h)
        if key != self.drawn_key:
            self.drawn_key = key
            top = int(text_y - h * 0.045)
            self.area.queue_draw_area(int(bx) - 2, top, int(bw) + 4, int(by + bh + 2) - top)
        return True

    def layout(self, w, h):
        """Bar x, y, width, height, text baseline, % font size."""
        bw, bh = w * 0.5, max(6, h * 0.009)
        bx, by = (w - bw) / 2, h * 0.84
        return bx, by, bw, bh, by - h * 0.018, h * 0.03

    # ----- drawing -----
    def background(self, w, h):
        """Hero art (cover-scaled), darkening gradient and logo; cached per size."""
        if self.bg_cache and self.bg_cache[:2] == (w, h):
            return self.bg_cache[2]
        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, w, h)
        cr = cairo.Context(surf)
        cr.set_source_rgb(0, 0, 0)
        cr.paint()

        def paint_pixbuf(pb, scale, x, y):
            cr.save()
            cr.translate(x, y)
            cr.scale(scale, scale)
            Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
            cr.paint()
            cr.restore()

        hw, hh = self.hero.get_width(), self.hero.get_height()
        s = max(w / hw, h / hh)
        paint_pixbuf(self.hero, s, (w - hw * s) / 2, (h - hh * s) / 2)

        g = cairo.LinearGradient(0, 0, 0, h)
        g.add_color_stop_rgba(0, 0, 0, 0, 0.35)
        g.add_color_stop_rgba(0.55, 0, 0, 0, 0.45)
        g.add_color_stop_rgba(1, 0, 0, 0, 0.92)
        cr.set_source(g)
        cr.paint()

        lw, lh = self.logo.get_width(), self.logo.get_height()
        s = min(w * 0.42 / lw, h * 0.48 / lh)
        paint_pixbuf(self.logo, s, (w - lw * s) / 2, h * 0.36 - lh * s / 2)

        self.bg_cache = (w, h, surf)
        return surf

    def on_draw(self, widget, cr):
        w, h = widget.get_allocated_width(), widget.get_allocated_height()
        cr.set_source_surface(self.background(w, h), 0, 0)
        cr.paint()

        bx, by, bw, bh, text_y, pct_size = self.layout(w, h)

        def pill(x, y, ww, hh):
            r = hh / 2
            cr.new_sub_path()
            cr.arc(x + ww - r, y + r, r, -1.5708, 0)
            cr.arc(x + ww - r, y + hh - r, r, 0, 1.5708)
            cr.arc(x + r, y + hh - r, r, 1.5708, 3.1416)
            cr.arc(x + r, y + r, r, 3.1416, 4.7124)
            cr.close_path()
            cr.fill()

        cr.set_source_rgba(1, 1, 1, 0.15)
        pill(bx, by, bw, bh)
        g = cairo.LinearGradient(bx, 0, bx + bw, 0)
        g.add_color_stop_rgb(0, 0.95, 0.62, 0.15)
        g.add_color_stop_rgb(1, 1.0, 0.85, 0.40)
        cr.set_source(g)
        pill(bx, by, max(bh, bw * self.shown / 100), bh)

        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(pct_size)
        pct = f"{min(100, int(self.shown))}%"
        cr.set_source_rgb(1, 0.9, 0.6)
        cr.move_to(bx + bw - cr.text_extents(pct).x_advance, text_y)
        cr.show_text(pct)

        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(h * 0.024)
        cr.set_source_rgba(1, 1, 1, 0.85)
        cr.move_to(bx, text_y)
        cr.show_text(MILESTONES[self.stage][1])

        if self.combo.available():
            cr.set_font_size(h * 0.018)
            cr.set_source_rgba(1, 1, 1, 0.35)
            hint = "Hold View + Menu to close"
            cr.move_to((w - cr.text_extents(hint).x_advance) / 2, by + bh + h * 0.06)
            cr.show_text(hint)
        return True


def fake_probes():
    """--preview: a 15 s fake launch on the desktop, without touching real timings.
    --preview-play also fakes Battle.net waiting for Play from 6 s to 12 s."""
    global procs, visible_windows, gfx_ready, big_bnet_windows, TIMINGS, REPORT
    t0 = time.monotonic()
    el = lambda: time.monotonic() - t0  # noqa: E731
    play = "--preview-play" in sys.argv
    delay = lambda: 6 if play and el() > 9 else 0  # noqa: E731
    order = ["explorer.exe", "Agent.exe", "Wow.exe"]
    procs = lambda: set(order[:min(2, int(el() / 3))] if play and el() < 12 else order[:int((el() - delay()) / 3)])  # noqa: E731,E501
    gfx_ready = lambda since: el() - delay() > 12  # noqa: E731
    visible_windows = lambda rx, by="--name": [1] if rx == WOW_WINDOW and el() - delay() > 15 else []  # noqa: E731,E501
    big_bnet_windows = lambda: [1] if play and 6 < el() < 12 else []  # noqa: E731
    TIMINGS = os.path.join(tempfile.gettempdir(), "wow-splash-preview-timings.json")
    REPORT = os.path.join(tempfile.gettempdir(), "wow-splash-preview-report.json")


def main():
    if "--preview" in sys.argv or "--preview-play" in sys.argv:
        fake_probes()
    splash = Splash()
    splash.show_all()
    signal.signal(signal.SIGTERM, lambda *_: Gtk.main_quit())  # runs on the next GLib tick
    try:
        Gtk.main()
    finally:
        splash.focus.release()   # never leave gamescope pinned to a dead window
        if not splash.done:
            write_report("stopped (SIGTERM / Close splash)", splash)


if __name__ == "__main__":
    main()
