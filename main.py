import json
import os
import shutil
import signal

import decky

# Steam launch options point at this wrapper, kept outside the plugin folder so the game
# still starts (without a splash) if the plugin is ever removed.
LAUNCHER = os.path.join(decky.DECKY_USER_HOME, ".local", "share", "decky-wow-splash", "launch.sh")
SETTINGS = os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json")

LAUNCHER_SCRIPT = """#!/bin/bash
# WoW Splash (Decky plugin) launch wrapper. Steam launch options: "<this file>" <appid> %command%
# Shows the splash when the plugin is installed, and always starts the game.
SPLASH="{splash}"
APPID=0
if [[ "$1" =~ ^[0-9]+$ ]]; then APPID="$1"; shift; fi
if [ -f "$SPLASH" ]; then
  WOW_SPLASH_SETTINGS="{settings}" WOW_SPLASH_DATA="{data}" \\
    env -u LD_PRELOAD -u PYTHONPATH -u PYTHONHOME /usr/bin/python3 "$SPLASH" "$APPID" >/dev/null 2>&1 &
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


def save_settings(data):
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    tmp = SETTINGS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, SETTINGS)


def write_launcher():
    text = LAUNCHER_SCRIPT.format(
        splash=os.path.join(decky.DECKY_PLUGIN_DIR, "splash", "splash.py"),
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


def read(path, limit=None):
    try:
        with open(path, errors="replace") as f:
            return f.read(limit)
    except OSError:
        return None


class Plugin:
    async def get_info(self):
        return {"launcher": LAUNCHER, "apps": load_settings()["apps"]}

    async def set_auto(self, appid: int, auto: bool):
        data = load_settings()
        data["apps"].setdefault(str(appid), {})["auto"] = bool(auto)
        save_settings(data)
        return data["apps"]

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
            "decky": decky.DECKY_VERSION,
            "os": f"{osr.get('PRETTY_NAME', '?').strip(chr(34))} {osr.get('VERSION_ID', '')} build {osr.get('BUILD_ID', '?')}".strip(),
            "xdotool": bool(shutil.which("xdotool")),
            "deck_controller": controller,
            "settings": load_settings()["apps"],
            "last_launch": last,
        }

    async def _main(self):
        try:
            write_launcher()
        except OSError as e:
            decky.logger.error(f"can't write {LAUNCHER}: {e}")

    async def _unload(self):
        pass

    async def _uninstall(self):
        # The launcher stays: shortcuts may still point at it, and it just starts the game.
        pass
