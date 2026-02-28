# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

Fetches meetings from Google Calendar (last 7 days, with attendees) and creates structured Markdown notes in an Obsidian vault. The user selects a meeting interactively, pastes a transcript, and a note is saved to `<vault>/Reunions/<meeting_title>/<YYMMDD>_<meeting_title>.md`.

## Commands

```bash
# Install dependencies
uv sync

# Run the GUI app
uv run python src/gui/app.py
```

The app opens a PySide6 GUI window with two wizard flows: "Entrar transcripcions" and "Processar reunions".

## Required Configuration

- `.env` — must contain `OBSIDIAN_VAULT_PATH=/path/to/vault`
- `config/google_credentials.json` — OAuth2 credentials from Google Cloud Console (Calendar API, read-only scope)
- `config/token.pickle` — auto-generated on first run after OAuth browser flow

## Architecture

Modules in `src/`:

**`calendar_matcher.py` — `CalendarMatcher`**
Handles Google Calendar OAuth (credentials stored in `config/google_credentials.json`, token cached in `config/token.pickle`). Exposes `self.service` (the Google API client) and `_parse_event(event)` which normalises a raw Calendar API event into a dict: `{title, start, end, duration, attendees}`.

**`obsidian_writer.py` — `ObsidianWriter`**
Takes the parsed meeting dict and a transcript string, generates YAML frontmatter + Markdown, and writes to `<vault>/Reunions/<clean_title>/<YYMMDD>_<clean_title>.md`. Title sanitisation strips filesystem-unsafe characters and replaces spaces with underscores.

**`gui/` — PySide6 GUI**
`app.py` is the entry point. `main_window.py` shows two buttons that open wizard dialogs: `wizard_transcripcio.py` (enter transcriptions) and `wizard_processar.py` (process meetings with corrections, analysis, summaries). Workers in `workers.py` run long operations in QThread. Custom widgets in `widgets/`.
