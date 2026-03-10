#!/bin/bash
cd "$(dirname "$0")"
uv run python src/gui/app.py
osascript -e 'tell application "Terminal" to close (every window whose name contains "'$(basename "$0")'")'
