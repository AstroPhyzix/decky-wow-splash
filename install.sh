#!/bin/sh
# WoW Splash installer. In Konsole (Desktop Mode):
#   curl -fsSL https://raw.githubusercontent.com/AstroPhyzix/wow-splash/main/install.sh | sh
# Uninstall:
#   curl -fsSL https://raw.githubusercontent.com/AstroPhyzix/wow-splash/main/install.sh | sh -s -- --uninstall
set -e
REPO=AstroPhyzix/wow-splash
NAME=wow-splash
OLD_NAME=decky-wow-splash   # folder name before 1.5
PLUGINS="$HOME/homebrew/plugins"

if [ ! -d "$PLUGINS" ]; then
  echo "The Steam Deck plugin loader isn't installed. Get it from https://decky.xyz first." >&2
  exit 1
fi
if ! passwd -S "$USER" 2>/dev/null | grep -q ' P '; then
  echo "This needs your sudo password. If you never set one, run 'passwd' first." >&2
fi

if [ "$1" = "--uninstall" ]; then
  sudo rm -rf "$PLUGINS/$NAME" "$PLUGINS/$OLD_NAME"
  sudo systemctl restart plugin_loader
  echo "WoW Splash removed. Your shortcuts still start the game (without a splash)."
  exit 0
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
echo "Downloading WoW Splash..."
curl -fL --progress-bar -o "$TMP/$NAME.zip" "https://github.com/$REPO/releases/latest/download/$NAME.zip"
python3 -m zipfile -e "$TMP/$NAME.zip" "$TMP"
[ -f "$TMP/$NAME/plugin.json" ] || { echo "Download looks broken, nothing changed." >&2; exit 1; }

sudo rm -rf "$PLUGINS/$NAME" "$PLUGINS/$OLD_NAME"
sudo cp -r "$TMP/$NAME" "$PLUGINS/$NAME"
sudo chown -R root:root "$PLUGINS/$NAME"
sudo systemctl restart plugin_loader
echo "WoW Splash $(python3 -c "import json;print(json.load(open('$TMP/$NAME/package.json'))['version'])") installed."
echo "In Gaming Mode: Quick Access (...) -> plug icon -> WoW Splash, then turn it on for your shortcut."
