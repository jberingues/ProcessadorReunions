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
      semantic_memory.json   # memòria semàntica per sèrie de reunions
  Projectes/
    <NomProjecte>/
      <NomProjecte>.md   # project template note
      Reunions/
      Documentació/
  zConfig/
    Vocabulari.md          # vocabulary for corrections + secció "## Configuració"
    Canvis-Memoritzats.md  # memorized corrections (global)
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
- `find_corrected_notes` / `find_unprocessed_notes` / `find_uncorrected_notes` / `find_unprocessed_email_notes` — cerca notes per estat
- `read_transcript` / `update_transcript` — llegeix/actualitza la secció `## Transcripció`
- `read_email_body` — extreu cos d'una nota de correu
- `mark_as_corrected` / `mark_as_processed` — canvia el sufix del fitxer (`~` / `*`)
- `append_to_provider_note` / `append_to_historic` — afegeix contingut a notes existents
- `find_subfolders(type_folder)` — llista subcarpetes de `Reunions/<type_folder>/`
- `update_project_fields(note_path, data_inici, resum)` — omple `Data inici` i `## Resum` a una nota de projecte

**`transcript_corrector.py` — `TranscriptCorrector`**
Constructor: `(vocab, semantic_memory_path=None, model=None, threshold_auto=0.85)`.
- Carrega correccions memoritzades globals (`zConfig/Canvis-Memoritzats.md`) i locals (`semantic_memory.json` → `aliases`).
- `detect(transcript, reference_transcript=None, semantic_context=None)` retorna `(transcript_amb_memoritzades, llista_correccions_noves)`. Cada correcció: `{original, correccio, motiu, frase, confiança}`.

**`semantic_memory_builder.py` — `SemanticMemoryBuilder`**
Construeix i manté `semantic_memory.json` per sèrie de reunions.
- `build_if_stale(meeting_dir)` — reconstrueix si els `.md` processats son més recents que el JSON.
- Extreu temes de les notes, carrega projectes de `Vocabulari.md`, fusiona amb dades existents.

**`semantic_context_retriever.py` — `SemanticContextRetriever`**
- `load(meeting_dir)` — carrega `semantic_memory.json` i retorna un `SemanticContext` (o None si no existeix).

**`semantic_models.py`**
Models Pydantic: `SemanticMemory` (person, projects, technical_terms, aliases, recurring_topics) i `SemanticContext` (relevant_projects, likely_terms, topic_context, aliases).

**`semantic_memory.json`** — ubicació: `{meeting_dir}/semantic_memory.json`
```json
{
  "person": "Nom Persona",
  "projects": ["proj1"],
  "technical_terms": ["terme1"],
  "aliases": { "paraula_errònia": "terme_correcte" },
  "recurring_topics": ["tema1"]
}
```
S'actualitza **només** quan l'usuari activa el flag "Memoritzar" en una correcció: s'afegeix l'alias `original → correccio` i la paraula correcta a `technical_terms`.

**`meeting_analyzer.py` — `MeetingAnalyzer` + `StateFileUpdater`**
`MeetingAnalyzer.analyze(topics, transcript, brief=False)` retorna `MeetingAnalysisResult` (temes tractats + nous temes) via CrewAI. `StateFileUpdater.update(estat_path, result, date_label)` actualitza `Estat actual.md` i `Històric.md`.

**`daily_processor.py` — `DailyProcessor`**
Constructor: `(vocab, model=None)`. Processa transcripcions de Daily Scrum via CrewAI. `process(transcript, attendees)` retorna `DailyScrumResult` (participants amb ahir/avui + altres temes). `format_markdown(result, meeting_title, date_str)` genera el markdown.

**`vocabulary_loader.py` — `VocabularyLoader`**
Llegeix `Vocabulari.md` i retorna el vocabulari com a dict per seccions. `load_config()` retorna claus de la secció `## Configuració` (e.g. `threshold_auto`).

**`gui/workers.py` — QThread Workers**
- `CalendarWorker` — carrega reunions de Google Calendar
- `GmailWorker` — carrega fils de Gmail
- `CorrectionDetectWorker` — correcció d'una transcripció (single)
- `BatchCorrectionDetectWorker` — correcció batch; signals: `note_started(int)`, `note_finished(int, str, list)`, `note_error(int, str)`, `all_finished()`
- `DailyProcessorWorker` — processa daily scrum
- `MeetingAnalyzerWorker` — analitza reunions de seguiment (suporta `brief=True`)
- `SummaryWorker` — genera resums via litellm
- `ProjectInitWorker` — genera resum de projecte via litellm (transcripció + fitxers)

**`gui/widgets/`**
- `inline_correction_editor.py` — editor inline amb highlights de correccions i navegació. Estats: `pending` (groc), `accepted` (verd), `rejected` (gris), `manual` (usuari ha editat), `not_found`. API pública: `get_final_text()`, `get_memorize_list()`, `get_accepted_words()`. El checkbox "Memoritzar" permet marcar correccions per desar a `semantic_memory.json`.
- `correction_checklist.py` — llista de correccions amb checkboxes d'aprovació i opció de memoritzar.
- `transcript_editor.py` — editor de transcripció amb paste i net.

## Wizard Correccio — Flux Detallat

**3 pàgines** (`QStackedWidget`):

1. **Selecció** — taula de notes sense corregir, selecció múltiple.
2. **Batch processing** — per cada nota: crea `TranscriptCorrector` (amb `semantic_memory_path` i `threshold_auto`), carrega transcript i transcript de referència (nota processada més recent), construeix `SemanticContext` via `SemanticMemoryBuilder` + `SemanticContextRetriever`, llança `BatchCorrectionDetectWorker`. Notes sense correccions es marquen directament com a corregides (`~`).
3. **Revisió individual** — `InlineCorrectionEditor` per cada nota amb correccions detectades. En clicar "Desar": actualitza `semantic_memory.json` si hi ha memoritzacions, desa transcript corregit, marca com a corregida.
