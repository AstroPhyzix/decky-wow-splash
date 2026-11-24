# WoW Splash

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin that shows a full-screen
World of Warcraft loading screen while WoW starts on the Steam Deck. It hides the Proton console,
the Battle.net windows and the flicker between them, and closes the moment WoW's own window opens.

- Works with any WoW flavor (Retail, Classic, Forever, PTR, ...) wherever it is installed: the
  game folder is found from the running `Wow*.exe`.
- Uses your shortcut's own **hero** and **logo** artwork (set it in the game's Properties or with
  the SteamGridDB plugin); falls back to the art bundled with the plugin.
- A progress bar driven by what is really happening (Wine, Battle.net, Wow.exe, graphics device,
  game window), timed from your last 5 launches.
- Steps aside while the Battle.net login window is open, and, unless Battle.net starts the game by
  itself, while it waits for you to press **Play**. It comes back when the game starts.
- Gaming Mode and Desktop Mode.
- Stuck? Hold **View + Menu** on the Deck for 1.5 s, or use **Close splash** in the plugin menu.
- **Report a problem** opens a GitHub issue with your system info and the last launch filled in
  (you review it before submitting; nothing is sent automatically).

## First launch / not logged in

On a fresh install Battle.net shows its login window, may update itself, and may ask you to
install WoW. The splash steps aside for any real Battle.net window that stays open (the login
window after 6 s; others right away, or after 20 s if "Battle.net starts WoW by itself" is on)
and comes back once the game starts. Those launches aren't used for the progress timings.

## Use

1. Add Battle.net (or WoW) to Steam as a non-Steam game and run it with Proton.
2. Open the Quick Access menu → Decky → **WoW Splash**.
3. Turn the splash on for your shortcut. Shortcuts with "Warcraft", "WoW" or "Battle.net" in the
   name are listed; turn on **Show all non-Steam shortcuts** if yours has another name.
4. If your shortcut starts WoW automatically (e.g. a script that sends Battle.net
   `--exec="launch WoW"`), turn on **Battle.net starts WoW by itself**.

Turning it on adds a small wrapper to the shortcut's launch options:

```
"/home/deck/.local/share/decky-wow-splash/launch.sh" <appid> %command%
```

Your other launch options are kept. Turning it off removes the wrapper again. The wrapper lives
outside the plugin folder, so if you uninstall the plugin the game still starts (just without the
splash); turn the splash off first if you want clean launch options.

## Requirements

SteamOS 3 (uses the system `python3`, GTK 3, PyGObject, pycairo and `xdotool`, all part of SteamOS).
No root access needed.

## Build

```
pnpm i
./package.sh        # -> out/decky-wow-splash-v<version>.zip
```

Install the zip from Decky's settings (Developer → Install plugin from ZIP / URL).

Test the splash on the desktop with fake progress:

```
python3 defaults/splash/splash.py <appid> --preview
```

## How it works

- `main.py` writes the launch wrapper and stores per-shortcut options.
- `src/index.tsx` lists your shortcuts and edits their launch options.
- `defaults/splash/splash.py` is the splash itself (GTK). In Gaming Mode gamescope would switch
  focus to every new launcher window; the splash keeps itself in front by pinning gamescope's
  base-layer window and app id on Steam's X display, and puts Steam's values back when done.

## License

BSD-3-Clause, based on the [Decky plugin template](https://github.com/SteamDeckHomebrew/decky-plugin-template).
