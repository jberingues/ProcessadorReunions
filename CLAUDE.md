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

- `.env` — must contain `OBSIDIAN_VAULT_PATH=/path/to/vault` and `LLM_MODELH=<litellm model id>`. Opcional: `EMAIL_INCLUDE_SINCRO=true` per incloure les sèries de `Sincronització/` en l'arxivat de correus (vegeu "Wizard Correus").
- `config/google_credentials.json` — OAuth2 credentials from Google Cloud Console (Calendar + Gmail API)
- `config/token.pickle` — auto-generated on first run after OAuth browser flow. **Scopes**: `calendar.readonly`, `directory.readonly`, `gmail.readonly`, `gmail.labels` (definits a `calendar_matcher.py:SCOPES`). El split Gmail és intencionat: `gmail.readonly` per llegir fils/adjunts; `gmail.labels` només per crear/editar etiquetes (no aplicar-les a correus). Si afegeixes/canvies scopes, cal esborrar el token (`rm config/token.pickle`) i tornar a executar l'app per refer el flux OAuth amb els nous permisos.
- **Plaud CLI**: `npm install -g @plaud-ai/cli` + un cop a la vida `plaud login` (OAuth al navegador). El binari ha d'estar al `PATH`.

## Note Lifecycle (filename suffixes)

| Fitxer | Estat |
|--------|-------|
| `YYMMDD_Títol.md` | Transcripció introduïda, sense corregir |
| `YYMMDD_Títol~.md` | Transcripció corregida |
| `YYMMDD_Títol*.md` | Processada (LLM analitzada o projecte inicialitzat) |

## Vault Structure (Obsidian)

Estructura **homogènia**: totes les subcarpetes de sèrie tenen exactament el mateix patró (aplicat via migració one-shot el 2026-05). El nivell `<Tipus>/` es conserva com a contenidor organitzatiu, però **el codi de processat no el mira** — la branca de processat es decideix per l'opció del selector al wizard (vegeu "Wizard Processar — Flux Detallat").

```
Reunions/
  <Tipus>/                                # Seguiment / Sincronització / Proveïdors / Projectes / Reunions vàries
    <Subfolder>/                          # sèrie de reunions
      Reunions/
        YYMMDD_Títol.md                   # notes individuals (frontmatter sense `type:`)
      Temes oberts.md                     # només si la sèrie té reunions de "Resum+ordre dia"
      Ordre del dia propera reunió.md     # idem
      <Any> <Subfolder>.md                # resum anual: històric (Seguiment), daily (Sincro), resums (puntuals)
      Resum projecte <Subfolder>.md       # només a Projectes/<X>/
      Correus/  Fitxers/                  # opcionals
      semantic_memory.json                # memòria semàntica per sèrie
  zConfig/
    Vocabulari.md                         # vocabulari unificat: termes + aliases en sublistes + secció "## Configuració"
```

**Nom dels fitxers `<Any> <Subfolder>.md`**: el `<Subfolder>` s'obté de `series_name_for_file()` (vegeu `obsidian_writer.py`) — substitueix `_` per espais i treu claudàtors. E.g. `Reunions/Seguiment/Arnau Prunell/2026 Arnau Prunell.md`. Si una reunió és de 2025, el fitxer destí és `2025 <Subfolder>.md` (l'any ve del prefix YYMMDD de la nota, no de la data actual).

**Convenció de noms de subfolders dins `Seguiment/`**: sense prefix "Seguiment_" (ja eliminat el 2026-05 via migració one-shot). E.g. `Arnau Prunell/`, `Dani Catalina/`, no `Seguiment_Arnau_Prunell/`. Excepció: `Seguiment x/` (carpeta de proves on "Seguiment" forma part del nom). Els event titles de Calendar encara contenen "Seguiment_" — això causa que els fitxers individuals dins `Reunions/` es diguin `YYMMDD_Seguiment_<X>.md` (cosmètic, no afecta funcionament).

Subfolders amb prefix `x` (e.g. `xProjecte/`, `xProveïdor/`) són **plantilles** — el codi (i la migració) els salta.

## GUI Wizard Flows (`src/gui/`)

| Botó | Wizard | Descripció |
|------|--------|------------|
| Entrar transcripcions | `wizard_transcripcio.py` | Pàgina 0 = `PairingView` (aparella reunions de Calendar amb gravacions de Plaud d'un dia). Itera sobre cada parell + cada gravació orfe: tria carpeta destí, descarrega transcripció de Plaud (o paste manual com a fallback), desa la nota. |
| Entrar correus | `wizard_correus.py` | Arxivat automàtic de fils Gmail al vault segons etiquetes (vegeu "Wizard Correus — Flux Detallat"). |
| Entrar fitxers | `wizard_fitxers.py` | Copia fitxers externs a una carpeta del vault. |
| Correcció transcripcions | `wizard_correccio.py` | Batch: detecta errors de transcripció en notes sense corregir via LLM + vocabulari i mostra l'editor inline. |
| Processar reunions | `wizard_processar.py` | Selector per fila amb 4 opcions (`Resum`, `Resum+ordre dia`, `Resum+ordre dia (breu)`, `Sincro`); default segons path actual. Tots tres processats escriuen a `<Subfolder>/<Any> <Subfolder>.md`. Vegeu "Wizard Processar — Flux Detallat". |
| Processar correus | `wizard_processar_correus.py` | Igual que la versió anterior de "Processar reunions" — encara fa servir el model antic (`Estat actual.md`, `Històric.md`, `<NomProveïdor>.md`). **Pendent d'adaptar** al model homogeni. |
| Crear un projecte nou | `wizard_nou_projecte.py` | Selecciona nota corregida + fitxers del vault + carpeta de projecte existent, omple `Data inici` i `## Resum` de la nota de projecte via LLM. Marca la reunió com a processada. |

## Architecture — Key Modules (`src/`)

**`calendar_matcher.py` — `CalendarMatcher`**
Google Calendar OAuth (credentials a `config/`). `_parse_event(event)` retorna `{title, start, end, duration, attendees}`. El `start` és tz-aware (ISO de Google amb `Z` o offset).

**`gmail_fetcher.py` — `GmailFetcher`**
Embolcall sobre l'API Gmail (OAuth compartit amb Calendar):
- `list_user_labels()` / `create_label(name)` — gestió d'etiquetes user (idempotent).
- `list_thread_ids_for_day(target_day)` — IDs de fils amb missatges del dia indicat (`after:Y/M/D before:Y/M/(D+1)`, paginat).
- `peek_thread(id, labels_index)` — crida `format=minimal` per saber `{label_names, message_count}` sense baixar bodies. Indispensable per al check d'idempotència abans d'un fetch complet.
- `fetch_thread_full(id, labels_index)` — fil sencer amb tots els missatges (ordenats cronològicament), headers parsejats, `body_text` (text/plain → tal qual; només HTML → conversió amb `html2text` si està disponible) i adjunts descarregats en binari.
- Filtrat d'adjunts inline (`is_inline_attachment`): es descarten parts amb MIME `image/*` + `Content-Disposition: inline` + `Content-ID` present. Heurística per evitar guardar logos de signatura, icones Outlook i imatges embebudes al cos HTML. Els documents reals (PDF, .docx, .xlsx, .zip, ...) i les imatges adjuntades explícitament com a `attachment` passen el filtre.

**`email_archiver.py`** — Lògica pura per a l'arxivat (sense Qt ni Gmail):
- `discover_vault_series(vault_path, include_sincro=False) -> VaultDiscovery` — escaneja `Reunions/` i retorna `active = {etiqueta → Path}` per a qualsevol top-level que contingui sèries (carpeta amb subfolder `Reunions/`). Excloses sempre: `zConfig` i `Temes seguiment tancats` (tractament dedicat). Exclosa per defecte: `Sincronització` (opt-in via flag). Salta `x*` (plantilles). Detecta sèries niu (e.g. `Proveïdors/ARROW/Microchip`). També retorna `closed_by_active_label = {'Seguiment/X' → Path}` per a sèries de `Temes seguiment tancats/` (indexades per l'etiqueta *activa* esperada per detectar correus tardans).
- `pick_destination(label_names, discovery) -> DispatchResult` — primary per prioritat `Projectes > Proveïdors > Seguiment > Reunions vàries`. Si la primary és tancada, `is_closed=True` + warning. Les altres etiquetes vault del fil van a `extra_labels`.
- `normalize_subject(subject, max_len=60)` — treu Re:/Fwd:/Fw:/Rv:/Rep: repetits, sanitza chars de path, retalla, espais → `_`.
- `place_attachment(files_dir, date_prefix, name, data)` — desa un adjunt idempotentment: si existeix amb bytes idèntics, reusa el path; si col·lisió amb contingut diferent, afegeix sufix `_2`, `_3`, …
- `load_processed_store / save_processed_store / needs_archive / mark_archived` — JSON d'idempotència a `<vault>/zConfig/.processed_threads.json`. `needs_archive` retorna True si el fil és nou o si `message_count` ha crescut.

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

**`obsidian_writer.py` — `ObsidianWriter` + helper de mòdul**
Totes les operacions de lectura/escriptura al vault.
- **Helper de mòdul** `series_name_for_file(folder_name) -> str` — converteix el nom d'una subcarpeta a la forma apta per a fitxer (`_` → ` `, treu `[`/`]`).
- `create_meeting_note` / `create_email_note` / `create_simple_note` — crea notes. **Ja no pre-crea `Estat actual.md` / `Històric.md` automàticament** — l'usuari crea `Temes oberts.md` manualment quan la sèrie ha de fer "Resum+ordre dia".
- `create_email_thread_note(thread, dest_dir, primary_label, extra_labels=None) -> (note_path, attachment_paths)` — escriu una nota markdown del fil sencer a `<dest_dir>/Correus/YYMMDD_<assumpte>.md`. Frontmatter amb `type: correu`, `thread_id`, `data`, `assumpte`, `labels: [primary]`, `tags: [extras]`. Una secció `## YYYY-MM-DD HH:MM — Nom <email>` per missatge (amb `(resposta)` a partir del 2n). Els adjunts es desen a `<dest_dir>/Fitxers/` amb `email_archiver.place_attachment` (idempotent: bytes iguals → reusa) i s'enllacen amb wikilinks `[[Fitxers/...]]` sota cada missatge. Sobreescriu la nota si ja existeix.
- `find_corrected_notes` / `find_unprocessed_notes` / `find_uncorrected_notes` / `find_unprocessed_email_notes` — cerca notes per estat.
- `read_transcript` / `update_transcript` — llegeix/actualitza la secció `## Transcripció`.
- `read_email_body` — extreu cos d'una nota de correu.
- `mark_as_corrected` / `mark_as_processed` — canvia el sufix del fitxer (`~` / `*`).
- `append_to_year_note(meeting_note_path, date_label, title, attendees, content_block) -> Path` — destí unificat de tots els processats de reunió. Escriu a `<subfolder>/<year> <series>.md` amb capçalera `## <date_label> - <title>` + opcional `Assistents: …` + `content_block`. Crea el fitxer si no existeix. Any extret del prefix YYMMDD del nom de la nota; sèrie = `series_name_for_file(subfolder.name)`.
- `append_to_historic` / `append_email_to_provider_note` — **deprecated**, encara els usa `wizard_processar_correus.py` (pendent d'adaptar). No usar per a codi nou.
- `find_subfolders(type_folder)` — llista subcarpetes de `Reunions/<type_folder>/`.
- `update_project_fields(note_path, data_inici, resum)` — omple `Data inici` i `## Resum` a una nota de projecte.

**`transcript_corrector.py` — `TranscriptCorrector`**
Constructor: `(vocab, semantic_memory_path=None, model=None, threshold_auto=0.85)`.
- Carrega correccions memoritzades globals (aliases del `zConfig/Vocabulari.md` unificat, llegits via `VocabularyLoader.load_aliases()`) i locals (`semantic_memory.json` → `aliases`).
- `detect(transcript, reference_transcript=None, semantic_context=None)` retorna `(transcript_amb_memoritzades, llista_correccions_noves)`. Cada correcció: `{original, correccio, motiu, frase, confiança}`. Pipeline intern:
  1. Aplica memoritzades (globals i locals) amb reemplaçament whole-word.
  2. Crida el LLM amb vocab + memòria semàntica + referència + few-shot d'exemples de falsos positius a evitar (paraules catalanes comunes que sonen similars a termes del Vocabulari).
  3. Filtre de confiança del LLM: descarta propostes amb confiança < 0.85.
  4. Filtre fonètic post-LLM: `is_likely_phonetic` descarta substitucions semàntiques (distància > 0.75).
- El pre-pass fuzzy (`find_fuzzy_candidates`) està **desactivat** al pipeline. Empíricament generava falsos positius (paraules catalanes comunes com `cosa`, `pots`, `Vila` matchejaven amb cognoms/termes per similitud 0.7-0.85). El LLM ja veu el vocabulari sencer al prompt; el fuzzy independent només afegia soroll. El mòdul `phonetic_filter` es manté per `is_likely_phonetic` i per a futurs experiments.
- `apply(transcript, corrections)` i les memoritzades comparteixen `_replace_whole_word()` per reemplaçament coherent (regex amb límits de paraula).

**`phonetic_filter.py`**
Funcions pures de similitud per al pipeline de correcció:
- `levenshtein(a, b)`, `normalized_distance(a, b)`, `similarity(a, b)` — case/accent-insensitive.
- `is_likely_phonetic(original, correccio, max_distance=0.75)` — filtre post-LLM contra sinònims. **En ús**.
- `find_fuzzy_candidates(transcript, vocab_terms, min_similarity=0.7)` — **no s'usa actualment** al pipeline (vegeu nota a `TranscriptCorrector`). Conservada per si es vol reintroduir amb llindars més estrictes o com a verificació secundària.

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
- `MeetingAnalyzer.analyze(topics, transcript, brief=False)` retorna `MeetingAnalysisResult` (temes tractats + nous temes) via CrewAI.
- `parse_active_topics(temes_oberts_path)` — llegeix `Temes oberts.md` i retorna la llista de noms dels temes oberts (s'atura a "## Altres temes").
- `StateFileUpdater.update(temes_oberts_path, result, date_label) -> str` — aplica updates inline a `Temes oberts.md` (afegeix bullets datats sota cada tema tractat) i reescriu la secció `## Altres temes` amb els temes nous d'aquesta reunió (els antics es perden — ja s'han escrit al fitxer anual al processat previ on van aparèixer). **Retorna** un bloc markdown amb el resum d'aquesta reunió: tots els temes tractats (`### {topic_name}` + `- {summary}`) seguits de `#### Altres temes` amb els temes nous. El **caller decideix on escriu** el bloc — `wizard_processar.py` el passa a `ObsidianWriter.append_to_year_note(...)` per anar al fitxer anual. Retorna `""` si no hi ha res a escriure.
- **No es toquen els temes marcats `(Tancat)`**: queden al fitxer `Temes oberts.md` amb la marca i l'usuari els elimina manualment quan ho decideix. Decisió presa el 2026-05-23 — abans el sistema els extreia automàticament i només escrivia els tancats al fitxer anual, però resultava confús i deixava poca traça al fitxer anual.

**`daily_processor.py` — `DailyProcessor`**
Constructor: `(vocab, model=None)`. Processa transcripcions de Daily Scrum via CrewAI. `process(transcript, attendees)` retorna `DailyScrumResult` (participants amb ahir/avui + altres temes). `format_markdown(result, meeting_title, date_str)` genera el markdown.

**`vocabulary_loader.py` — `VocabularyLoader`**
Llegeix el `Vocabulari.md` unificat (termes principals + aliases en sublistes indentades).
- `load()` retorna `{secció: [termes_principals]}` — només els termes de primer nivell (compatible amb el codi existent).
- `load_aliases()` retorna `{alias: terme_correcte}` per al corrector global. Si el terme conté `→`, `(...)` o `/`, retorna només la forma canònica (defensiu contra format antic).
- `add_alias(alias, target_term)` escriu un nou alias al fitxer preservant format. Si `target_term` no existeix, es crea a la secció `## Altres (per revisar)`.
- `add_term(term)` afegeix un terme principal sense aliases (per a paraules validades com a correctes). Sempre va a `## Altres (per revisar)`.
- `load_config()` retorna les claus de la secció `## Configuració` (e.g. `threshold_auto`).
- Format del fitxer:
  ```
  ## Secció
  - Terme principal
    - alias1
    - alias2
  - Altre terme
  ## Configuració
    - threshold_auto: 0.85    (entries indentades sense terme pare)
  ```

**`gui/workers.py` — QThread Workers**
- `CalendarWorker` — carrega reunions de Google Calendar
- `EmailArchiveWorker` — orquestra l'arxivat de correus (sync etiquetes + fetch fils + dispatch + escriptura). Signals: `log(str)`, `progress(done, total)`, `finished(summary: dict)`, `error(str)`. `summary` conté `archived_threads`, `skipped_unchanged`, `skipped_no_vault_label`, `sync_created_labels`, `sync_orphan_labels`, `sync_closed_warnings`, `errors`.
- `CorrectionDetectWorker` — correcció d'una transcripció (single)
- `BatchCorrectionDetectWorker` — correcció batch; signals: `note_started(int)`, `note_finished(int, str, list)`, `note_error(int, str)`, `all_finished()`
- `DailyProcessorWorker` — processa daily scrum
- `MeetingAnalyzerWorker` — analitza reunions de seguiment (suporta `brief=True`)
- `SummaryWorker` — genera resums via litellm
- `ProjectInitWorker` — genera resum de projecte via litellm (transcripció + fitxers)
- `PlaudListWorker` — llista gravacions Plaud d'un dia i resol `start_at` UTC per cadascuna. Signals: `progress(done, total)`, `finished(list)`, `error(str)`, `not_authenticated()`.
- `PlaudTranscriptWorker` — baixa transcripció d'una gravació. Signals: `finished(file_id, text)`, `error(file_id, msg)`, `not_authenticated()`. Inclou `file_id` per descartar resultats stale quan l'usuari avança ràpid.

**`gui/widgets/`**
- `inline_correction_editor.py` — editor inline amb highlights de correccions i navegació. Estats: `pending` (groc), `accepted` (verd), `validated` (blau clar, paraula confirmada com a correcta), `rejected` (gris), `manual` (usuari ha editat el transcript), `not_found`. API pública: `get_final_text()`, `get_memorize_global()`, `get_memorize_series()`, `get_correct_words()`, `get_accepted_words()`. La fila 2 mostra `"original" → [target editable]` — l'usuari pot **modificar la proposta** del LLM (QLineEdit) abans d'acceptar; el camp és read-only en estats que no siguin `pending`. La fila 3 té 3 botons d'acció: **✓ Acceptar** (aplica + opcionalment memoritza l'alias), **★ És correcta** (no toca el text, afegeix l'`original` al Vocabulari com a terme principal perquè no es torni a proposar), **✗ Rebutjar** (no toca res); a la dreta, 3 radio buttons d'scope per a memorització d'alias: **Cap** (default, no acumula brossa), **Aquesta sèrie** (alias al `semantic_memory.json` local), **Sempre** (alias al `Vocabulari.md` global). L'scope no aplica a "És correcta" (sempre va al Vocabulari). **Acceptar/rebutjar/auto-acceptar reemplacen totes les ocurrències de paraula sencera** via `_replace_all_whole_word`/`_find_in_doc`, coherent amb `TranscriptCorrector.apply()`. Per a originals d'una sola paraula s'usa `FindCaseSensitively | FindWholeWords`; per a frases multi-paraula (e.g. `"els HPE"`) s'usa `QRegularExpression` amb `(?<!\w)…(?!\w)` perquè `FindWholeWords` no funciona amb cadenes que contenen espais. Conseqüència: si dues correccions comparteixen el mateix `original`, acceptar-ne una marca l'altra com a `manual` (perquè el seu `original` ja no és al text). **Botons habilitats en tots els estats no-tancats**: `accepted`/`rejected`/`validated` blocs els seus botons recíprocs, però `manual` i `not_found` mantenen els 3 botons clicables perquè l'usuari mai no quedi atrapat. Igual amb el QLineEdit del target: editable mentre no s'hagi pres una decisió definitiva.
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

## Wizard Processar — Flux Detallat

**2 pàgines** (`QStackedWidget`):

1. **Selecció** (pàg. 0) — taula de notes corregides amb 3 columnes: `Data`, `Títol`, `Tipus de processat`. La 3a columna és un `QComboBox` per fila amb 4 opcions:
   - **`Resum`** — `SummaryWorker` (litellm). Genera resum estructurat (`##### Tema` + bullets).
   - **`Resum+ordre dia`** — `MeetingAnalyzerWorker` (CrewAI). Compara la transcripció amb els temes de `Temes oberts.md`; actualitza el fitxer (bullets datats); escriu el resum de la reunió al fitxer anual; reescriu `Ordre del dia propera reunió.md`.
   - **`Resum+ordre dia (breu)`** — igual però amb `brief=True` al MeetingAnalyzer (resums de 2 línies per tema).
   - **`Sincro`** — `DailyProcessorWorker` (CrewAI). Daily scrum per persona (ahir/avui + altres temes).

   **Default per fila** via `_default_option_for_path(path)`: path conté `Sincronització/` → `Sincro`; path conté `Seguiment/` → `Resum+ordre dia`; resta → `Resum`. L'usuari pot canviar-ho fila per fila.

2. **Pre-flight check** (al clicar Endavant) — `_validate_pre_flight(selected_rows)` comprova que per a cada fila amb `Resum+ordre dia*` existeix `<subfolder>/Temes oberts.md`. Si falta, mostra `QMessageBox` bloquejant amb la llista de notes afectades. L'usuari ha de crear el fitxer manualment (decisió explícita per evitar crear `Temes oberts.md` buit sense criteri editorial) o canviar el tipus de processat. **No es continua fins resoldre-ho.**

   **Ordenació cronològica**: `_sort_notes_by_date()` ordena els parells `(note, option)` per `note['date']` ASC (oldest first) abans de construir la cua. Important per Seguiment (els temes oberts evolucionen amb el temps) i per llegibilitat dels year notes (seccions per data ascendent). YYMMDD lexicogràfic = cronològic perquè el format és fix.

3. **Batch processing** (pàg. 1) — taula amb 4 columnes (`Data`, `Títol`, `Tipus`, `Estat`). Processament seqüencial: `_process_next()` decideix la branca per `item.option` (no per path!), llança el worker corresponent, i al callback escriu al destí. Tots tres processats acaben cridant `obsidian.append_to_year_note(...)`:
   - **Resum**: contingut = output cru del `SummaryWorker`.
   - **Sincro**: contingut = output del `DailyProcessor` **retallant la primera línia `# title - date`** (que duplicaria la capçalera del bloc anual).
   - **Resum+ordre dia**: contingut = bloc retornat per `StateFileUpdater.update()` amb el resum complet d'aquesta reunió (tots els temes tractats + altres temes nous). Si el bloc és buit (cap tema tractat ni nou) no s'escriu al fitxer anual. A més, reescriu `Ordre del dia propera reunió.md` via `format_ordre_del_dia()`. **No elimina** els temes marcats `(Tancat)` de `Temes oberts.md` — l'usuari els treu manualment.

4. La nota individual es marca com a processada amb `mark_as_processed` (sufix `*`). Ordre dins el `try`: **primer** `append_to_year_note(...)`, **després** `mark_as_processed(...)`. Si la primera falla, el worker emet `error` i la nota queda sense marcar — no hi ha falsos positius (notes marcades sense contingut escrit).

**Decoupling**: el codi de processat **no mira mai el path** de la nota — la decisió ve del selector. Això permet, per exemple, fer "Resum" d'una nota dins `Seguiment/` o "Resum+ordre dia" d'una nota dins `Proveïdors/` si l'usuari ho vol. El path només decideix el **default** del selector.

**Errors a la UI**: la cel·la "Estat" mostra `Error: <primera línia truncada a 60 caràcters>`; passar el cursor per sobre mostra el missatge complet al tooltip (el log detallat amb traceback continua a `data/app.log`).

## Tests

Tests unitaris a `tests/` amb `unittest` (sense pytest). Cobreixen entre altres: `plaud_client.py` (parsing del CLI + gestió d'errors), `meeting_recording_matcher.py` (scoring + assignament), `series_name_for_file`, `ObsidianWriter.append_to_year_note`, `StateFileUpdater.update` (updates a `Temes oberts.md` + retorn del bloc del resum de la reunió per al fitxer anual), `_default_option_for_path` (mapeig path → opció del selector), `email_archiver` (discover sèries vault, dispatcher amb prioritat i cas tancat, normalització d'assumpte, idempotència d'adjunts via `place_attachment`, store JSON) i `ObsidianWriter.create_email_thread_note` (frontmatter, multi-missatge amb `(resposta)`, enllaços a adjunts, regeneració sense duplicar).

```bash
uv run python -m unittest discover -s tests
```

**Regla**: cada vegada que s'afegeix funcionalitat nova, cal:
1. Escriure un test nou per aquella funcionalitat a `tests/`.
2. Executar tots els tests existents per verificar que no s'ha trencat res.

## Wizard Correus — Flux Detallat

**Objectiu**: arxivar fils de Gmail al vault segons etiquetes user. Vault = source of truth de la jerarquia. Tot està pensat per **idempotència**: pots executar-lo cada dia sense duplicacions ni pèrdues.

**Convenció d'etiquetes Gmail**: planes amb `/` per a niu (que Gmail interpreta natiu). Una etiqueta per sèrie del vault:
- `Seguiment/<Persona>`
- `Projectes/<Projecte>`
- `Proveïdors/<Proveïdor>` o `Proveïdors/<Categoria>/<Marca>` per a sèries niu (e.g. `Proveïdors/ARROW/Microchip`)
- `Reunions vàries/<X>`
- (Opcional) `Sincronització/<X>` si `EMAIL_INCLUDE_SINCRO=true` al `.env`.

**Sync vault → Gmail**: a l'inici de cada execució, `EmailArchiveWorker` compara `discover_vault_series(...)` amb `list_user_labels()`. Crea les que falten. Avisa de les òrfenes per consola/log, **no esborra mai**.

**Cas especial — sèrie tancada**: una sèrie traslladada a `Temes seguiment tancats/X/` no genera etiqueta nova (les etiquetes són sempre `Seguiment/X`). `discover_vault_series` indexa aquestes carpetes per la seva *etiqueta activa esperada* (`Seguiment/X`). Si un correu arriba amb aquesta etiqueta i la sèrie ja és tancada:
1. `pick_destination` retorna `dest = .../Temes seguiment tancats/X/`, `is_closed=True` i un warning.
2. La nota i adjunts s'arxiven igualment a la carpeta tancada (no es perd informació).
3. El log emet `[TANCADA]` al costat del fil i el `summary['sync_closed_warnings']` recorda a l'usuari que pot esborrar manualment l'etiqueta a Gmail.

**Dispatcher**: si un fil té múltiples etiquetes vault, prioritat `Projectes > Proveïdors > Seguiment > Reunions vàries`. La primary va al `labels:` del frontmatter; les altres vault-labels a `tags:`. Les no-vault s'ignoren.

**Idempotència** (`<vault>/zConfig/.processed_threads.json`):
- Per cada `thread_id`: `{message_count, archived_at, dest_path}`.
- Abans del fetch full, fa `peek_thread` (crida minimal) per saber `message_count`. Si no ha crescut, salta el fil (estalvia descàrregues).
- Si ha crescut → `fetch_thread_full` + regenera la nota sencera (sobreescriu). Adjunts: `place_attachment` reusa els que ja existeixen amb bytes idèntics; només els nous afegeixen sufix.

**Format de la nota** (`<dest>/Correus/YYMMDD_<assumpte_normalitzat>.md`):
```markdown
---
type: correu
thread_id: <id>
data: 2026-05-20
assumpte: "Original sense Re:/Fwd:"
labels:
  - "Seguiment/Joan"
tags:
  - "Projectes/X"
---

## 2026-05-20 09:15 — Nom Cognom <email>

[cos pla — text/plain si existeix, altrament HTML→text amb html2text]

**Adjunts:**
- [[Fitxers/260520_informe.pdf]]

## 2026-05-20 14:30 — Altra Persona <email> (resposta)

[cos]
```

- Data del nom de fitxer i del frontmatter = data del **primer missatge** del fil.
- `normalize_subject`: treu `Re:`/`Fwd:`/`Fw:`/`Rv:`/`Rep:` repetits, retalla a 60 chars, sanitza chars de path, espais → `_`.

**Adjunts**: a `<dest>/Fitxers/YYMMDD_<nom>` (idempotent: bytes iguals reusen; bytes diferents → sufix `_2`, `_3`, …). Enllaços `[[Fitxers/...]]` sota cada missatge corresponent.

**UI (2 pàgines)**:
1. **Pàg. 0** — Selector d'un dia concret (default = avui) + nota sobre el flag de Sincronització. L'arxivat processa només els fils amb missatges d'aquest dia. Botó "Començar".
2. **Pàg. 1** — `QPlainTextEdit` amb log live + barra de progrés. Al final, panell de resum amb fils arxivats, saltats, etiquetes creades, avisos i errors. Botó "Aturar" actiu durant l'execució (avorta entre fils, no desfà els ja arxivats).

**Logs**: a més del log de la UI, escriu `data/email_archive_<timestamp>.log` (FileHandler dedicat afegit al root logger durant la sessió i retirat en acabar).

**Què NO fa**:
- No esborra correus a Gmail (només llegeix).
- No esborra etiquetes a Gmail automàticament (orphans → avís al resum).
- No toca `semantic_memory.json` ni `Vocabulari.md`.
- No mou ni renombra carpetes existents del vault (només crea `Correus/`/`Fitxers/` dins de cada sèrie si no hi són).

**Gotchas operatius**:
- **Model d'un dia**: la query Gmail és `after:D before:D+1`. Si oblides executar un dia X, els fils amb missatges *únicament* d'aquell dia no es processaran a futures execucions (no hi ha sweep enrere). Workaround: torna a llançar el wizard amb la data X com a `target_day`.
- **Correus enviats**: s'inclouen quan formen part d'un fil etiquetat — `fetch_thread_full` baixa tots els missatges (entrants i sortints). Si vols arxivar un correu enviat solo (no resposta), aplica manualment l'etiqueta de sèrie a Gmail abans/després d'enviar-lo.
- **Forçar re-arxivat d'un fil**: esborra la seva entrada a `<vault>/zConfig/.processed_threads.json` i torna a executar el wizard per a la data del fil. La nota es regenera sencera; els adjunts amb bytes idèntics es reusen (no es dupliquen).
- **Heurística inline-attachment**: el filtre descarta `image/* + inline + Content-ID`. Un PDF amb Content-ID (rar però possible) es manté; una imatge marcada com `attachment` també. Si trobes adjunts útils descartats o logos colats, mira la combinació exacta dels 3 senyals al missatge font abans d'ajustar `is_inline_attachment`.

## Wizard Correccio — Flux Detallat

**3 pàgines** (`QStackedWidget`):

1. **Selecció** — taula de notes sense corregir, selecció múltiple. Inclou dos checkboxes a sota:
   - **Aplicar les correccions automàticament (sense revisió manual)** — `chk_skip_review`. Si està marcat, la pàgina 3 no s'usa: després de detectar, `TranscriptCorrector.apply()` aplica totes les propostes i marca cada nota com a corregida sense memoritzar res (cap scope).
   - **Guardar còpia automàtica per comparar amb la versió manual** — `chk_save_comparison`. Desa 3 còpies de cada nota a `/tmp/comparacio_correccions/`: `<data>_<titol>_original.md` (transcripció abans de res), `_auto.md` (totes les correccions auto-aplicades) i `_manual.md` (la revisió de l'usuari). Permet fer `diff` per quantificar què aporta cada pas.
2. **Batch processing** — per cada nota: crea `TranscriptCorrector` (amb `semantic_memory_path` i `threshold_auto`), carrega transcript i transcript de referència (nota processada més recent), construeix `SemanticContext` via `SemanticMemoryBuilder` + `SemanticContextRetriever`, llança `BatchCorrectionDetectWorker`. Notes sense correccions es marquen directament com a corregides (`~`). Si `skip_review` està actiu, totes les correccions s'apliquen automàticament i la nota es marca com a corregida (mode "Auto-aplicat ✓").
3. **Revisió individual** — `InlineCorrectionEditor` per cada nota amb correccions detectades. En clicar "Desar": actualitza `semantic_memory.json` amb les memoritzacions per sèrie, afegeix aliases globals al `Vocabulari.md` (`VocabularyLoader.add_alias`), afegeix termes validats com a correctes (`VocabularyLoader.add_term`), desa transcript corregit, marca com a corregida.

**Observació empírica de qualitat**: en proves reals amb notes de seguiment intern, l'auto resolt típicament el 95-100% dels errors útils per a l'extracció de contingut. La revisió manual aporta valor sobretot a reunions amb conceptes nous o ambigus (brainstormings, decisions multi-producte). Per a dailies i seguiments rutinaris, `skip_review=True` és suficient.
