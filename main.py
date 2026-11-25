import glob
import json
import os
import shutil
import signal

import decky

# Steam launch options point at this wrapper, kept outside the plugin folder so the game
# still starts (without a splash) if the plugin is ever removed.
LAUNCHER = os.path.join(decky.DECKY_USER_HOME, ".local", "share", "wow-splash", "launch.sh")
# Before 1.5 the plugin, its wrapper and its folders had a longer name.
OLD_NAME = "decky-wow-splash"
OLD_LAUNCHER = os.path.join(decky.DECKY_USER_HOME, ".local", "share", OLD_NAME, "launch.sh")
SETTINGS = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json")

LAUNCHER_SCRIPT = """#!/bin/bash
# WoW Splash launch wrapper. Steam launch options: "<this file>" <appid> %command%
# While the plugin is installed: shows the splash and starts Battle.net through the plugin's
# wow-splash.bat (in "launch" mode it also makes Battle.net start WoW). Without the plugin it
# just runs the shortcut as it is.
DIR="{plugin}/splash"
APPID=0
if [[ "$1" =~ ^[0-9]+$ ]]; then APPID="$1"; shift; fi
if [ -f "$DIR/splash.py" ]; then
  MODE=$(env -u LD_PRELOAD -u PYTHONPATH -u PYTHONHOME /usr/bin/python3 -I -c '
import json, sys
try:
    print(json.load(open(sys.argv[1]))["apps"][sys.argv[2]].get("mode", "launch"))
except Exception:
    print("launch")' "{settings}/settings.json" "$APPID")
  # Swap the program Proton runs ("proton waitforexitandrun <exe> [args]") for our bat,
  # when this is a Proton launch and Battle.net is installed in its prefix.
  PFX="$STEAM_COMPAT_DATA_PATH/pfx"
  if [ -n "$STEAM_COMPAT_DATA_PATH" ] && [ -f "$PFX/drive_c/Program Files (x86)/Battle.net/Battle.net Launcher.exe" ]; then
    ARGS=("$@")
    for ((i = 1; i < ${{#ARGS[@]}} - 1; i++)); do
      if [ "${{ARGS[i]}}" = waitforexitandrun ] && [[ "${{ARGS[i-1]}}" == */proton ]]; then
        cmp -s "$DIR/wow-splash.bat" "$PFX/drive_c/wow-splash.bat" || cp "$DIR/wow-splash.bat" "$PFX/drive_c/wow-splash.bat"
        ARGS=("${{ARGS[@]:0:i+1}}" "$PFX/drive_c/wow-splash.bat")
        if [ "$MODE" = launch ]; then
          ARGS+=(launch)
          # The bat waits while this file exists; the splash removes it once Battle.net has
          # no update/repair running (a launch request cancels a running update).
          WAIT="$PFX/drive_c/wow-splash-wait"
          : > "$WAIT"
          export WOW_SPLASH_WAIT="$WAIT"
        fi
        set -- "${{ARGS[@]}}"
        break
      fi
    done
  fi
  WOW_SPLASH_SETTINGS="{settings}" WOW_SPLASH_DATA="{data}" WOW_SPLASH_MODE="$MODE" \\
    env -u LD_PRELOAD -u PYTHONPATH -u PYTHONHOME /usr/bin/python3 "$DIR/splash.py" "$APPID" >/dev/null 2>&1 &
fi
exec "$@"
"""


def load_settings():
    try:
        with open(SETTINGS) as f:
            data = json.load(f)
        if isinstance(data.get("apps"), dict):
            return data
    except (OSError, ValueError, AttributeError):
        pass
    return {"apps": {}}


def app_mode(app):
    """"launch" (the plugin makes Battle.net start WoW) or "splash" (splash until Battle.net
    is loaded). Settings from 1.2 had auto: true/false instead."""
    if app.get("mode") in ("launch", "splash"):
        return app["mode"]
    return "splash" if app.get("auto") is False else "launch"


def save_settings(data):
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    tmp = SETTINGS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, SETTINGS)


def write_launcher():
    text = LAUNCHER_SCRIPT.format(
        plugin=decky.DECKY_PLUGIN_DIR,
        settings=decky.DECKY_PLUGIN_SETTINGS_DIR,
        data=decky.DECKY_PLUGIN_RUNTIME_DIR,
    )
    try:
        with open(LAUNCHER) as f:
            if f.read() == text:
                return
    except OSError:
        pass
    os.makedirs(os.path.dirname(LAUNCHER), exist_ok=True)
    with open(LAUNCHER, "w") as f:
        f.write(text)
    os.chmod(LAUNCHER, 0o755)
    decky.logger.info(f"wrote {LAUNCHER}")


def migrate_old_dirs():
    """Carry settings, timings and the launch log over from the old plugin name. The old
    wrapper is kept as a forwarder until the panel has moved every shortcut to the new one."""
    home = os.path.join(decky.DECKY_USER_HOME, "homebrew")
    for kind, new in (("settings", decky.DECKY_PLUGIN_SETTINGS_DIR), ("data", decky.DECKY_PLUGIN_RUNTIME_DIR)):
        old = os.path.join(home, kind, OLD_NAME)
        if not os.path.isdir(old) or os.path.abspath(old) == os.path.abspath(new):
            continue
        os.makedirs(new, exist_ok=True)
        for f in os.listdir(old):
            if not os.path.exists(os.path.join(new, f)):
                shutil.copy2(os.path.join(old, f), os.path.join(new, f))
        shutil.rmtree(old, ignore_errors=True)
        decky.logger.info(f"moved {old} -> {new}")
    if os.path.isfile(OLD_LAUNCHER):
        with open(OLD_LAUNCHER, "w") as f:
            f.write(f'#!/bin/bash\nexec "{LAUNCHER}" "$@"\n')


def splash_pids():
    pids = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) == os.getpid():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                args = f.read().split(b"\0")
        except OSError:
            continue
        if any(a.endswith(b"/splash/splash.py") for a in args[1:3]):
            pids.append(int(pid))
    return pids


# Where a shortcut's Proton prefix can be: the main Steam library or one on an SD card / drive.
COMPATDATA = [
    os.path.join(decky.DECKY_USER_HOME, ".local", "share", "Steam", "steamapps", "compatdata"),
    "/run/media/*/steamapps/compatdata",
    "/run/media/*/*/steamapps/compatdata",
]
# Inside a Wine drive_c: what makes a prefix a WoW Forever one.
WOW_MARKERS = [
    ("Program Files (x86)", "World of Warcraft", "_forever_", "Wow.exe"),
    ("Program Files (x86)", "Battle.net", "Battle.net Launcher.exe"),
    ("Program Files", "World of Warcraft", "_forever_", "Wow.exe"),
]


def drive_c_of(path):
    """The Wine drive_c a path lies in, or None."""
    parts = os.path.normpath(path).split(os.sep)
    if "drive_c" in parts:
        return os.sep.join(parts[: len(parts) - parts[::-1].index("drive_c")])
    return None


def is_wow_shortcut(appid, exe, startdir):
    """True if the shortcut runs WoW Forever / Battle.net: its exe or start dir is inside a
    WoW install, or its Proton prefix (compatdata/<appid>) has one. Name doesn't matter."""
    exe, startdir = (exe or "").strip().strip('"'), (startdir or "").strip().strip('"')
    if os.path.basename(exe).lower() in ("wow.exe", "battle.net launcher.exe", "battle.net.exe"):
        return True
    roots = {drive_c_of(p) for p in (exe, startdir) if p}
    for pattern in COMPATDATA:
        roots.update(glob.glob(os.path.join(pattern, str(appid), "pfx", "drive_c")))
    for root in filter(None, roots):
        if any(os.path.isfile(os.path.join(root, *m)) for m in WOW_MARKERS):
            return True
    return False


def read(path, limit=None):
    try:
        with open(path, errors="replace") as f:
            return f.read(limit)
    except OSError:
        return None


class Plugin:
    async def get_info(self):
        apps = {k: {"mode": app_mode(v)} for k, v in load_settings()["apps"].items()}
        return {"launcher": LAUNCHER, "apps": apps}

    async def wow_shortcuts(self, shortcuts: list):
        """Of [{appid, exe, startdir}], the appids that point at WoW Forever / Battle.net."""
        found = []
        for sc in shortcuts:
            try:
                if is_wow_shortcut(int(sc["appid"]), sc.get("exe"), sc.get("startdir")):
                    found.append(int(sc["appid"]))
            except (KeyError, ValueError, OSError) as e:
                decky.logger.warning(f"wow_shortcuts: {sc}: {e}")
        return found

    async def drop_old_launcher(self):
        """Called once no shortcut uses the old wrapper path any more."""
        shutil.rmtree(os.path.dirname(OLD_LAUNCHER), ignore_errors=True)
        return True

    async def set_mode(self, appid: int, mode: str):
        data = load_settings()
        data["apps"][str(appid)] = {"mode": "splash" if mode == "splash" else "launch"}
        save_settings(data)
        return (await self.get_info())["apps"]

    async def splash_running(self):
        return bool(splash_pids())

    async def close_splash(self):
        """Stop a running splash (it restores gamescope's focus on SIGTERM)."""
        pids = splash_pids()
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        decky.logger.info(f"close_splash: {pids}")
        return len(pids)

    async def bug_report(self):
        """System info and the last launch's record, for a GitHub issue."""
        osr = dict(l.split("=", 1) for l in (read("/etc/os-release") or "").splitlines() if "=" in l)
        last = read(os.path.join(decky.DECKY_PLUGIN_RUNTIME_DIR, "last-launch.json"))
        try:
            last = json.loads(last) if last else None
            if last:
                last["log"] = last.get("log", [])[-40:]
        except ValueError:
            pass
        controller = any("28DE:00001205" in (read(f"/sys/class/hidraw/{d}/device/uevent") or "").upper()
                         for d in (os.listdir("/sys/class/hidraw") if os.path.isdir("/sys/class/hidraw") else []))
        return {
            "plugin": decky.DECKY_PLUGIN_VERSION,
            "loader": decky.DECKY_VERSION,
            "os": f"{osr.get('PRETTY_NAME', '?').strip(chr(34))} {osr.get('VERSION_ID', '')} build {osr.get('BUILD_ID', '?')}".strip(),
            "xdotool": bool(shutil.which("xdotool")),
            "deck_controller": controller,
            "settings": load_settings()["apps"],
            "last_launch": last,
        }

    async def _main(self):
        migrate_old_dirs()
        data = load_settings()   # 1.2 settings (auto: true/false) -> mode
        if any("mode" not in v for v in data["apps"].values()):
            data["apps"] = {k: {"mode": app_mode(v)} for k, v in data["apps"].items()}
            save_settings(data)
        try:
            write_launcher()
        except OSError as e:
            decky.logger.error(f"can't write {LAUNCHER}: {e}")

    async def _unload(self):
        pass

    async def _uninstall(self):
        # The launcher stays: shortcuts may still point at it, and it just starts the game.
        pass
