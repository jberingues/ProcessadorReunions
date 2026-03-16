#!/bin/bash
cd "$(dirname "$0")"
# Configura la finestra per tancar-se automàticament quan acabi l'app
osascript -e 'tell application "Terminal" to set shell exit action of current settings of front window to "close the window"' 2>/dev/null || true
uv run python src/gui/app.py
