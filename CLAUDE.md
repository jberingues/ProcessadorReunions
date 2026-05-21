# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

PySide6 GUI app that integrates Google Calendar, Gmail, **Plaud** (audio recordings + transcripcions via CLI) i un Obsidian vault per gestionar notes de reunions i seguiment de projectes. Carrega reunions/correus, baixa transcripcions de Plaud (o permet paste manual com a fallback), les corregeix amb un LLM, les processa en notes Obsidian estructurades i inicialitza documents de projectes.

## Commands

```bash
# Install dependencies
uv sync

# Run the GUI app
uv run python src/gui/app.py

# Run unit tests
uv run python -m unittest discover -s tests
```

## Required Configuration

- `.env` — must contain `OBSIDIAN_VAULT_PATH=/path/to/vault` and `LLM_MODELH=<litellm model id>`
- `config/google_credentials.json` — OAuth2 credentials from Google Cloud Console (Calendar + Gmail API)
- `config/token.pickle` — auto-generated on first run after OAuth browser flow
- **Plaud CLI**: `npm install -g @plaud-ai/cli` + un cop a la vida `plaud login` (OAuth al navegador). El binari ha d'estar al `PATH`.

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
| Entrar transcripcions | `wizard_transcripcio.py` | Pàgina 0 = `PairingView` (aparella reunions de Calendar amb gravacions de Plaud d'un dia). Itera sobre cada parell + cada gravació orfe: tria carpeta destí, descarrega transcripció de Plaud (o paste manual com a fallback), desa la nota. |
| Entrar correus | `wizard_correus.py` | Importa fils de Gmail i els desa com a notes de correu al vault. |
| Entrar fitxers | `wizard_fitxers.py` | Copia fitxers externs a una carpeta del vault. |
| Correcció transcripcions | `wizard_correccio.py` | Batch: detecta errors de transcripció en notes sense corregir via LLM + vocabulari i mostra l'editor inline. |
| Processar reunions | `wizard_processar.py` (mode=`normal`) | Selecciona nota corregida, l'analitza amb LLM (DailyProcessor o MeetingAnalyzer), actualitza Estat actual i Històric. |
| Processar correus | `wizard_processar_correus.py` | Igual que processar reunions però per a notes de correu. |
| Processar curt reunions | `wizard_processar.py` (mode=`curt`) | Versió breu (resum de 2 línies per tema). |
| Crear un projecte nou | `wizard_nou_projecte.py` | Selecciona nota corregida + fitxers del vault + carpeta de projecte existent, omple `Data inici` i `## Resum` de la nota de projecte via LLM. Marca la reunió com a processada. |

## Architecture — Key Modules (`src/`)

**`calendar_matcher.py` — `CalendarMatcher`**
Google Calendar OAuth (credentials a `config/`). `_parse_event(event)` retorna `{title, start, end, duration, attendees}`. El `start` és tz-aware (ISO de Google amb `Z` o offset).

**`gmail_fetcher.py` — `GmailFetcher`**
Accés a Gmail via la mateixa OAuth. `fetch_threads(date_from, date_to)` retorna fils de correu.

**`plaud_client.py` — `PlaudClient`**
Embolcall del CLI `plaud` (instal·lat globalment via npm). Mètodes:
- `is_authenticated()` — comprova `plaud me`.
- `list_for_date(date)` — `list[PlaudRecording]` per a un dia (filtra `today` o `recent -d N`).
- `get_file_metadata(id)` — dict clau-valor des de `plaud file <id>`.
- `get_start_at_utc(id)` — `datetime` tz-aware UTC (la constant `PLAUD_TIMEZONE = timezone.utc` documenta l'assumpció; verificat 2026-05-18).
- `get_transcript(id)` — text amb timestamps `[MM:SS - MM:SS] Speaker: …` (capçalera del CLI eliminada).
- Excepcions tipades: `PlaudCLINotInstalled`, `PlaudNotAuthenticated`, `PlaudError`.

**`meeting_recording_matcher.py`**
Funció pura `match(events, recordings)` → `MatchResult(pairs, unmatched_events, unmatched_recordings)`. Score combinat per parell: `0.85·temps + 0.15·durada`. Score temporal per trams (0-5 min = 1.0, 5-30 min lineal a 0.5, 30-60 min lineal a 0, >60 min = 0; offset 0 short-circuiteja a 0 ignorant la durada). Llindar AUTO ≥ 0.9, SUGGESTED ≥ 0.3. Assignació greedy 1:1. `PairStatus` = `AUTO` / `SUGGESTED` / `MANUAL` (l'últim només el produeix la UI, no el matcher).

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
- `PlaudListWorker` — llista gravacions Plaud d'un dia i resol `start_at` UTC per cadascuna. Signals: `progress(done, total)`, `finished(list)`, `error(str)`, `not_authenticated()`.
- `PlaudTranscriptWorker` — baixa transcripció d'una gravació. Signals: `finished(file_id, text)`, `error(file_id, msg)`, `not_authenticated()`. Inclou `file_id` per descartar resultats stale quan l'usuari avança ràpid.

**`gui/widgets/`**
- `inline_correction_editor.py` — editor inline amb highlights de correccions i navegació. Estats: `pending` (groc), `accepted` (verd), `rejected` (gris), `manual` (usuari ha editat), `not_found`. API pública: `get_final_text()`, `get_memorize_list()`, `get_accepted_words()`. El checkbox "Memoritzar" permet marcar correccions per desar a `semantic_memory.json`. **Acceptar/rebutjar/auto-acceptar reemplacen totes les ocurrències de paraula sencera** (case-sensitive + `FindWholeWords`) via `_replace_all_whole_word`, coherent amb `TranscriptCorrector.apply()`. Conseqüència: si dues correccions comparteixen el mateix `original`, acceptar-ne una marca l'altra com a `manual` (perquè el seu `original` ja no és al text).
- `correction_checklist.py` — llista de correccions amb checkboxes d'aprovació i opció de memoritzar.
- `transcript_editor.py` — editor de transcripció amb paste i net.
- `pairing_view.py` — `PairingView`: pàgina 0 del wizard de transcripcions. Selector de data, dues taules (Calendar / Plaud) carregades en paral·lel, auto-match via `MeetingRecordingMatcher`, llista de parells confirmats amb desfer i aparellament manual. Codi de color de fila: verd fosc (AUTO), taronja fosc (SUGGESTED), blau fosc (MANUAL), tots amb text blanc explícit per llegibilitat en macOS dark mode. API pública: `get_state()` → `(pairs, unmatched_events, unmatched_recordings)`.

## Wizard Transcripcio — Flux Detallat

**3 pàgines** (`QStackedWidget`) + iteració interna:

1. **PairingView** (pàg. 0) — selector de data, càrrega paral·lela de `CalendarWorker` + `PlaudListWorker`, auto-match, ajustament manual.
2. **En clicar Endavant**: es construeix la cua `work_queue = pairs + unmatched_recordings` (les reunions sense gravació es descarten). Comença la iteració.
3. Per cada item de la cua, **pàg. 1** mostra "Element X de Y — Títol" + arbre de carpetes. El tree mostra com a **seleccionables** només les carpetes que contenen una subcarpeta `Reunions/`; la resta apareixen en gris com a contenidors organitzatius. No es descendeix dins una carpeta amb `Reunions/` (és destinació final).
4. **Pàg. 2**: títol del item + barra de progrés mentre `PlaudTranscriptWorker` descarrega. Quan acaba, l'editor s'omple amb la transcripció (timestamps + parlants). L'usuari pot editar abans de desar.
5. **Desar** → `obsidian.create_simple_note(meeting_dict, text, target_dir)`. Per a parells `Pair`, `meeting_dict = pair.event`. Per a `PlaudRecording` orfes, es fabrica `{title: rec.name, start: rec.start_at, end: start+duration, attendees: []}`. Després s'avança automàticament al següent item.
6. Quan la cua és buida, la finestra es tanca (sense diàleg final).

**Protecció contra workers stale**: `PlaudTranscriptWorker` emet el `file_id` als signals; si l'usuari ha avançat ràpid abans que torni el worker, el resultat s'ignora.

**Enrere**: només actiu a la pàg. 2 (per re-triar carpeta sense reaparellar). No es pot tornar a la pàgina 0 un cop ha començat la iteració.

## Tests

Tests unitaris a `tests/` amb `unittest` (sense pytest). Cobreixen `plaud_client.py` (parsing del CLI + gestió d'errors) i `meeting_recording_matcher.py` (scoring + assignament).

```bash
uv run python -m unittest discover -s tests
```

**Regla**: cada vegada que s'afegeix funcionalitat nova, cal:
1. Escriure un test nou per aquella funcionalitat a `tests/`.
2. Executar tots els tests existents per verificar que no s'ha trencat res.

## Wizard Correccio — Flux Detallat

**3 pàgines** (`QStackedWidget`):

1. **Selecció** — taula de notes sense corregir, selecció múltiple.
2. **Batch processing** — per cada nota: crea `TranscriptCorrector` (amb `semantic_memory_path` i `threshold_auto`), carrega transcript i transcript de referència (nota processada més recent), construeix `SemanticContext` via `SemanticMemoryBuilder` + `SemanticContextRetriever`, llança `BatchCorrectionDetectWorker`. Notes sense correccions es marquen directament com a corregides (`~`).
3. **Revisió individual** — `InlineCorrectionEditor` per cada nota amb correccions detectades. En clicar "Desar": actualitza `semantic_memory.json` si hi ha memoritzacions, desa transcript corregit, marca com a corregida.
