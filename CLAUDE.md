# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

PySide6 GUI app that integrates Google Calendar, Gmail and an Obsidian vault to manage meeting notes and project tracking. It fetches meetings/emails, lets the user paste or import transcripts, corrects them with an LLM, processes them into structured Obsidian notes, and initializes project documents.

## Commands

```bash
# Install dependencies
uv sync

# Run the GUI app
uv run python src/gui/app.py
```

## Required Configuration

- `.env` — must contain `OBSIDIAN_VAULT_PATH=/path/to/vault` and `LLM_MODELH=<litellm model id>`
- `config/google_credentials.json` — OAuth2 credentials from Google Cloud Console (Calendar + Gmail API)
- `config/token.pickle` — auto-generated on first run after OAuth browser flow

## Note Lifecycle (filename suffixes)

| Fitxer | Estat |
|--------|-------|
| `YYMMDD_Títol.md` | Transcripció introduïda, sense corregir |
| `YYMMDD_Títol~.md` | Transcripció corregida |
| `YYMMDD_Títol*.md` | Processada (LLM analitzada o projecte inicialitzat) |

## Vault Structure (Obsidian)

```
Reunions/
  <Tipus>/           # e.g. Seguiment, Projectes, Puntual…
    <Subfolder>/
      Reunions/      # meeting notes live here
        YYMMDD_Títol.md
      Estat actual.md
      Històric.md
  Projectes/
    <NomProjecte>/
      <NomProjecte>.md   # project template note
      Reunions/
      Documentació/
  zConfig/
    Vocabulari.md          # vocabulary for corrections
    Canvis-Memoritzats.md  # memorized corrections
```

## GUI Wizard Flows (`src/gui/`)

| Botó | Wizard | Descripció |
|------|--------|------------|
| Entrar transcripcions | `wizard_transcripcio.py` | Selecciona reunió de Google Calendar, escull carpeta destí al vault, enganxa transcripció i desa la nota. |
| Entrar correus | `wizard_correus.py` | Importa fils de Gmail i els desa com a notes de correu al vault. |
| Entrar fitxers | `wizard_fitxers.py` | Copia fitxers externs a una carpeta del vault. |
| Correcció transcripcions | `wizard_correccio.py` | Batch: detecta errors de transcripció en notes sense corregir via LLM + vocabulari i mostra l'editor inline. |
| Processar reunions | `wizard_processar.py` (mode=`normal`) | Selecciona nota corregida, l'analitza amb LLM (DailyProcessor o MeetingAnalyzer), actualitza Estat actual i Històric. |
| Processar correus | `wizard_processar_correus.py` | Igual que processar reunions però per a notes de correu. |
| Processar curt reunions | `wizard_processar.py` (mode=`curt`) | Versió breu (resum de 2 línies per tema). |
| Crear un projecte nou | `wizard_nou_projecte.py` | Selecciona nota corregida + fitxers del vault + carpeta de projecte existent, omple `Data inici` i `## Resum` de la nota de projecte via LLM. Marca la reunió com a processada. |

## Architecture — Key Modules (`src/`)

**`calendar_matcher.py` — `CalendarMatcher`**
Google Calendar OAuth (credentials a `config/`). `_parse_event(event)` retorna `{title, start, end, duration, attendees}`.

**`gmail_fetcher.py` — `GmailFetcher`**
Accés a Gmail via la mateixa OAuth. `fetch_threads(date_from, date_to)` retorna fils de correu.

**`obsidian_writer.py` — `ObsidianWriter`**
Totes les operacions de lectura/escriptura al vault. Mètodes principals:
- `create_meeting_note` / `create_email_note` / `create_simple_note` — crea notes
- `find_corrected_notes` / `find_unprocessed_notes` / `find_uncorrected_notes` — cerca notes per estat
- `read_transcript` / `update_transcript` — llegeix/actualitza la secció `## Transcripció`
- `mark_as_corrected` / `mark_as_processed` — canvia el sufix del fitxer (`~` / `*`)
- `append_to_provider_note` / `append_to_historic` — afegeix contingut a notes existents
- `find_subfolders(type_folder)` — llista subcarpetes de `Reunions/<type_folder>/`
- `update_project_fields(note_path, data_inici, resum)` — omple `Data inici` i `## Resum` a una nota de projecte

**`transcript_corrector.py` — `TranscriptCorrector`**
Utilitza CrewAI + vocabulari de `zConfig/Vocabulari.md` i correccions memoritzades de `zConfig/Canvis-Memoritzats.md`. `detect(transcript)` retorna `(transcript_amb_memoritzades, llista_correccions_noves)`.

**`meeting_analyzer.py` — `MeetingAnalyzer` + `StateFileUpdater`**
`MeetingAnalyzer.analyze(topics, transcript)` retorna `MeetingAnalysisResult` (temes tractats + nous temes) via CrewAI. `StateFileUpdater.update(estat_path, result, date_label)` actualitza `Estat actual.md` i `Històric.md`.

**`daily_processor.py` — `DailyProcessor`**
Processa transcripcions de Daily Scrum via CrewAI. Retorna `DailyScrumResult` (participants amb ahir/avui + altres temes).

**`vocabulary_loader.py` — `VocabularyLoader`**
Llegeix `Vocabulari.md` i retorna el vocabulari com a dict.

**`semantic_*.py`**
Models i utilitats per a cerca semàntica (embeddings) sobre el vault.

**`gui/workers.py` — QThread Workers**
- `CalendarWorker` — carrega reunions de Google Calendar
- `GmailWorker` — carrega fils de Gmail
- `CorrectionDetectWorker` / `BatchCorrectionDetectWorker` — correcció de transcripcions
- `DailyProcessorWorker` — processa daily scrum
- `MeetingAnalyzerWorker` — analitza reunions de seguiment
- `SummaryWorker` — genera resums via litellm
- `ProjectInitWorker` — genera resum de projecte via litellm (transcripció + fitxers)

**`gui/widgets/`**
- `inline_correction_editor.py` — editor inline amb highlights de correccions i opció de memoritzar
- `transcript_editor.py` — editor de transcripció amb paste i net
