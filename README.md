# WoW Splash

![WoW Splash](assets/thumbnail.jpg)

A Steam Deck plugin for playing
**World of Warcraft Forever** on the Steam Deck. It launches the game straight from your Steam
library and shows a full-screen loading screen the whole time, so you never see the Proton
console, the Battle.net windows or the flicker between them.

## Features

- **Launch WoW directly:** press Play in Steam and you land in WoW. The plugin starts
  Battle.net and tells it to start WoW Forever. You don't need to touch the Battle.net window.
- **The real loading steps, not a fake timer:** Starting Proton → Launching Battle.net →
  Signing in to Battle.net → Waiting for World of Warcraft to start → Loading World of Warcraft.
  The progress bar is timed from your last 5 launches.
- **Steps aside when Battle.net needs you:** login screen, update, license, install. It comes
  back when the game starts, so a fresh install that isn't signed in yet works too.
- **Never traps you:** hold **View + Menu** for 1.5 s, or use **Close splash** in the plugin
  menu.
- Works in Gaming Mode and Desktop Mode. No root access needed.

## Install

Needs the Steam Deck plugin loader ([get it here](https://decky.xyz)). In Desktop Mode, open Konsole and run:

```sh
curl -fsSL https://raw.githubusercontent.com/AstroPhyzix/wow-splash/main/install.sh | sh
```

It asks for your sudo password (the plugin folder belongs to root). If you never set one,
run `passwd` first. Run the same line again to update. To remove it:

```sh
curl -fsSL https://raw.githubusercontent.com/AstroPhyzix/wow-splash/main/install.sh | sh -s -- --uninstall
```

You can also download `wow-splash.zip` from
[Releases](https://github.com/AstroPhyzix/wow-splash/releases) and install it from the plugin
loader's settings (Developer mode → Install plugin from ZIP file).

## Setup

1. Install Battle.net in a Proton prefix and add it to Steam as a non-Steam game. Any name
   works: the plugin finds the shortcut by checking its program and Proton prefix for
   Battle.net or WoW Forever.
2. Install WoW Forever from Battle.net once and sign in with "Keep me logged in".
3. Open the Quick Access menu → plug icon → **WoW Splash** and turn on **Splash screen**.

## How it works

Turning the splash on adds a small wrapper in front of the shortcut's launch options (your
other options are kept):

```
"/home/deck/.local/share/wow-splash/launch.sh" <appid> %command%
```

When you press Play:

1. **The wrapper** reads the shortcut's mode and starts the splash. It then has Proton run the
   plugin's `wow-splash.bat` in the shortcut's prefix instead of the shortcut's own program.
   The bat starts `Battle.net Launcher.exe`. In *Launch WoW directly* mode it also sends
   `Battle.net.exe --exec="launch WoWF"` every few seconds until `Wow.exe` is running, because
   Battle.net ignores that command while it is still starting.
2. **The splash** (`splash.py`, GTK) follows the launch from what it can see: processes
   (`explorer.exe`, `Battle.net.exe`, `Wow.exe`), Battle.net's windows, WoW's `Logs/gx.log`
   (graphics device ready) and finally the WoW window. It closes the moment that window opens,
   or once Battle.net is ready in splash-only mode.
3. **In Gaming Mode**, gamescope would switch focus to every new launcher window, which makes
   the screen flash. The splash keeps itself in front by pinning gamescope's focus on Steam's
   X display, and puts Steam's values back when it's done.

Turning the splash off removes the wrapper. The wrapper lives outside the plugin folder: if you
uninstall the plugin, the shortcut still starts the way it did before.

Files: `main.py` (backend: writes the wrapper, stores settings, closes the splash, collects
bug-report info), `src/index.tsx` (Quick Access panel), `defaults/splash/` (splash, launch bat,
art).

## Report a problem

1. Open the Quick Access menu → plug icon → **WoW Splash** → **Report a problem**.
2. A GitHub "new issue" page opens. It is pre-filled with your plugin, plugin loader and SteamOS versions,
   your splash settings and a short log of your last launch.
3. Describe what you saw (for example "the splash stayed up" or "Battle.net showed through"),
   check the text, and submit. You need a GitHub account. Nothing is sent until you submit.

You can also [open an issue](https://github.com/AstroPhyzix/wow-splash/issues/new)
yourself. If you do, say which mode you use and what you saw on screen.

## Requirements

SteamOS 3 with the plugin loader. Uses the system `python3`, GTK 3, PyGObject, pycairo and
`xdotool`, all part of SteamOS. Battle.net must be installed in the default folder
(`C:\Program Files (x86)\Battle.net`) of the shortcut's Proton prefix. If it isn't found, the
shortcut runs as-is and only the splash is shown.

## Build

```
pnpm i
./package.sh        # -> out/wow-splash-v<version>.zip
```

Install the zip from the plugin loader's settings (Developer → Install plugin from ZIP).

Test the splash on the desktop with a fake launch:

```
python3 defaults/splash/splash.py 0 --preview                 # Launch WoW directly
python3 defaults/splash/splash.py 0 --preview --splash-only   # Splash only
```

## Credits

Artwork from [SteamGridDB](https://www.steamgriddb.com/). World of Warcraft and Battle.net are
trademarks of Blizzard Entertainment; this plugin is not affiliated with or endorsed by Blizzard.

## License

[BSD-3-Clause](LICENSE), based on the plugin loader's official plugin template.
