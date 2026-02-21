# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

Fetches meetings from Google Calendar (last 7 days, with attendees) and creates structured Markdown notes in an Obsidian vault. The user selects a meeting interactively, pastes a transcript, and a note is saved to `<vault>/Reunions/<meeting_title>/<YYMMDD>_<meeting_title>.md`.

## Commands

```bash
# Install dependencies
uv sync

# Run the app
uv run python src/reunio_interactiva.py
```

The app is interactive: it lists recent meetings, prompts for a selection, then accepts a transcript via stdin (Ctrl+D to finish).

## Required Configuration

- `.env` — must contain `OBSIDIAN_VAULT_PATH=/path/to/vault`
- `config/google_credentials.json` — OAuth2 credentials from Google Cloud Console (Calendar API, read-only scope)
- `config/token.pickle` — auto-generated on first run after OAuth browser flow

## Architecture

Three modules in `src/`:

**`calendar_matcher.py` — `CalendarMatcher`**
Handles Google Calendar OAuth (credentials stored in `config/google_credentials.json`, token cached in `config/token.pickle`). Exposes `self.service` (the Google API client) and `_parse_event(event)` which normalises a raw Calendar API event into a dict: `{title, start, end, duration, attendees}`.

**`obsidian_writer.py` — `ObsidianWriter`**
Takes the parsed meeting dict and a transcript string, generates YAML frontmatter + Markdown, and writes to `<vault>/Reunions/<clean_title>/<YYMMDD>_<clean_title>.md`. Title sanitisation strips filesystem-unsafe characters and replaces spaces with underscores.

**`reunio_interactiva.py` — `ReunioInteractiva`**
Orchestrates the interactive CLI flow: list meetings → user selects → paste transcript → save. Only meetings with `attendees` in the Calendar API response are shown. The script must be run from inside `src/` (or via `uv run python src/...`) because imports are relative (`from calendar_matcher import ...`).
