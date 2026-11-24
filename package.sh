#!/bin/bash
# Builds the frontend and packs the installable plugin zip into out/.
set -e
cd "$(dirname "$0")"
pnpm build
NAME=wow-splash
VER=$(python3 -c 'import json;print(json.load(open("package.json"))["version"])')
rm -rf out && mkdir -p "out/$NAME"
cp -r dist main.py plugin.json package.json LICENSE README.md "out/$NAME/"
cp -r defaults/. "out/$NAME/"
find "out/$NAME" -name __pycache__ -prune -exec rm -rf {} +
(cd out && zip -qr "$NAME-v$VER.zip" "$NAME" && cp "$NAME-v$VER.zip" "$NAME.zip")
echo "out/$NAME-v$VER.zip"
