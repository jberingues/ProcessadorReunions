# CLAUDE.md

Guidance for Claude Code working in this repo. Detalls de mètodes que no estan aquí: llegeix el codi (`src/`). Aquest fitxer recull el **per què** i els **gotchas** que no es dedueixen del codi.

## What This Project Does

PySide6 GUI que integra Google Calendar, Gmail, **Plaud** (àudio + transcripcions via CLI) i un Obsidian vault per gestionar notes de reunions i seguiment de projectes. Baixa transcripcions de Plaud (o paste manual com a fallback), les corregeix amb un LLM, les processa en notes Obsidian estructurades i inicialitza documents de projectes.

## Commands

```bash
uv sync                                          # install deps
uv run python src/gui/app.py                     # run GUI
uv run python -m unittest discover -s tests      # run tests
```

## Required Configuration

- `.env` — `OBSIDIAN_VAULT_PATH=/path/to/vault`, `LLM_MODELH=<litellm model id>`. Opcional: `EMAIL_INCLUDE_SINCRO=true` per incloure `Sincronització/` en l'arxivat de correus.
- `config/google_credentials.json` — OAuth2 (Calendar + Gmail).
- `config/token.pickle` — auto-generat al primer OAuth. **Scopes** (`calendar_matcher.py:SCOPES`): `calendar.readonly`, `directory.readonly`, `gmail.readonly`, `gmail.labels`. Split Gmail intencionat: `readonly` per llegir fils/adjunts; `labels` només per crear/editar etiquetes (no aplicar-les). **Si canvies scopes: `rm config/token.pickle` i refés el flux OAuth.**
- **Plaud CLI**: `npm install -g @plaud-ai/cli` + `plaud login` un cop. Binari al `PATH`.

## Note Lifecycle (filename suffixes)

| Fitxer | Estat |
|--------|-------|
| `YYMMDD_Títol.md` | Transcripció introduïda, sense corregir |
| `YYMMDD_Títol~.md` | Corregida |
| `YYMMDD_Títol*.md` | Processada (LLM o projecte inicialitzat) |

## Vault Structure (Obsidian)

Estructura **homogènia** (migració one-shot 2026-05): totes les sèries tenen el mateix patró. El nivell `<Tipus>/` és organitzatiu — **el codi de processat no el mira** (la branca la decideix el selector del wizard).

```
Reunions/
  <Tipus>/                                # Seguiment / Sincronització / Proveïdors / Projectes / Reunions vàries
    <Subfolder>/                          # sèrie de reunions
      Reunions/YYMMDD_Títol.md            # notes individuals (frontmatter sense `type:`)
      Temes oberts.md                     # només si la sèrie fa "Resum+ordre dia"
      Ordre del dia propera reunió.md     # idem
      <Any> <Subfolder>.md                # resum anual (destí de tots els processats)
      Resum projecte <Subfolder>.md       # només a Projectes/<X>/
      Correus/                            # marcador opt-in per al sync d'etiquetes Gmail (pot quedar buida)
      Fitxers/                            # opcional, adjunts
      semantic_memory.json                # memòria semàntica per sèrie
      <Sub-sèrie>/                         # opcional: sèrie niu amb el seu propi Reunions/, Correus/, Fitxers/
  zConfig/Vocabulari.md                   # vocabulari unificat: termes + aliases en sublistes + "## Configuració"
```

**Gotchas d'estructura:**
- **Sèries niu reals**: una sèrie pot contenir sub-sèries amb contingut propi (e.g. `Proveïdors/ARROW/` amb `Correus/` propi **i** `Proveïdors/ARROW/Microchip/` també). El descobriment de sèries i l'arbre de destí descendeixen per trobar-les.
- **Cicle de vida**: un tema neix a `Seguiment/` i es trasllada a `Projectes/`, `Reunions vàries/` o `Temes seguiment tancats/`. L'etiqueta Gmail (nom de fulla) **no canvia** amb el trasllat.
- **Nom `<Any> <Subfolder>.md`**: `<Subfolder>` via `series_name_for_file()` (`_`→espai, treu `[]`). L'any ve del prefix YYMMDD de la nota, no de la data actual (reunió de 2025 → `2025 <Subfolder>.md`).
- **Subfolders dins `Seguiment/`**: sense prefix `Seguiment_` (eliminat 2026-05). Excepció: `Seguiment x/` (carpeta de proves). Els event titles de Calendar encara duen `Seguiment_` → fitxers individuals `YYMMDD_Seguiment_<X>.md` (cosmètic).
- **Prefix `x`** (`xProjecte/`, `xProveïdor/`) = plantilles; el codi i la migració els salten.

## GUI Wizard Flows (`src/gui/`)

| Botó | Wizard | Descripció |
|------|--------|------------|
| Entrar transcripcions | `wizard_transcripcio.py` | Pàg. 0 = `PairingView` (Plaud esquerra, Calendar dreta). Itera **parells confirmats + gravacions orfes seleccionades**. Reunions sense gravació es descarten. |
| Entrar correus | `wizard_correus.py` | Arxivat automàtic de fils Gmail segons etiquetes. |
| Sincronitzar etiquetes Gmail | `GmailLabelSyncWorker` + `QMessageBox` | Crea les etiquetes Gmail que falten per a sèries del vault (sense arxivar). Sèrie = carpeta amb `Correus/`. No esborra òrfenes. |
| Entrar fitxers | `wizard_fitxers.py` | Copia fitxers externs a una carpeta del vault. |
| Correcció transcripcions | `wizard_correccio.py` | Batch: detecta errors via LLM + vocabulari, editor inline. |
| Processar reunions | `wizard_processar.py` | Selector per fila (4 opcions); default segons path. Tots escriuen a `<Subfolder>/<Any> <Subfolder>.md`. |
| Processar correus | `wizard_processar_correus.py` | **Model antic** (`Estat actual.md`, `Històric.md`, `<NomProveïdor>.md`). **Pendent d'adaptar** al model homogeni. |
| Crear un projecte nou | `wizard_nou_projecte.py` | Nota corregida + fitxers + carpeta projecte → omple `Data inici` i `## Resum` via LLM. Marca la reunió processada. |

## Architecture — Key Modules (`src/`)

Resum funcional; per a signatures exactes llegeix el mòdul. Es destaquen només els punts no-obvis.

- **`calendar_matcher.py` — `CalendarMatcher`**: OAuth Calendar. `_parse_event` → `{title, start, end, duration, attendees}`; `start` tz-aware.
- **`gmail_fetcher.py` — `GmailFetcher`**: wrapper Gmail API (OAuth compartit). Gestió d'etiquetes (`list/create/rename_label` — `rename` conserva l'ID i per tant les assignacions de fils), `list_thread_ids_for_day`, `peek_thread` (`format=minimal`, per idempotència), `fetch_thread_full` (missatges cronològics, `body_text` text/plain o HTML→`html2text`, adjunts binaris).
  - **`is_inline_attachment`**: descarta `image/*` **+ `Content-ID` present** (ignora `Content-Disposition`). El `Content-ID` és el senyal fiable de imatge embeguda (signatura/logo). **No** s'exigeix `inline` perquè reenviar canvia la disposició i deixava colar signatures (e.g. icones socials EBV). Documents reals (PDF/docx/…) no tenen Content-ID; imatges adjuntades explícitament tampoc.
- **`email_archiver.py`** — lògica pura (sense Qt ni Gmail):
  - `discover_vault_series(vault, include_sincro=False)`: carpeta = sèrie **sii conté `Correus/`** (`SERIES_SUBFOLDER_MARKER`, opt-in explícit). **L'etiqueta és el nom de fulla** (no el camí) → invariant als trasllats; per tant els noms de fulla han de ser **únics** (col·lisions → `discovery.warnings`, es conserva la primera). Niu real: `_walk_series` no s'atura en trobar sèrie (salta `NON_SERIES_SUBFOLDERS`). Exclou sempre `zConfig` i `Temes seguiment tancats` (→ `closed_by_active_label`); `Sincronització` opt-in; salta `x*`. `top_level` desa el top-level de cada etiqueta per al dispatch.
  - `pick_destination`: prioritat `Projectes > Proveïdors > Seguiment > Reunions vàries` (derivada de `top_level`, no de l'string). Sèrie tancada → `is_closed=True` + warning. Altres etiquetes → `extra_labels`.
  - `plan_label_migration`: migra etiquetes Gmail format antic (`Seguiment/CRA`) → fulla (`CRA`). Usat per `migrate_gmail_labels.py` (dry-run per defecte, `--apply`).
  - `normalize_subject`, `place_attachment` (idempotent: bytes iguals reusa, sinó sufix `_2`…), store JSON (`load/save_processed_store`, `needs_archive`, `mark_archived`), `sync_gmail_labels` → `LabelSyncResult` (`created/failed/orphan/closed`; mai esborra).
- **`plaud_client.py` — `PlaudClient`**: wrapper CLI `plaud`. `is_authenticated`, `list_for_date`, `get_file_metadata`, `get_start_at_utc` (`PLAUD_TIMEZONE = timezone.utc`, verificat 2026-05-18), `get_transcript` (timestamps `[MM:SS - MM:SS] Speaker:`). Excepcions: `PlaudCLINotInstalled/NotAuthenticated/Error`.
  - **Gotcha — data de pujada ≠ data de gravació**: la columna de data del llistat del CLI (`plaud today`/`recent`) és el **`created_at` (pujada al cloud)**, NO el `start_at` (quan vas gravar). Una gravació feta un dia i sincronitzada l'endemà sortia sota el dia equivocat. Per això `list_for_date` resol `start_at` de cada candidat i filtra per la seva **data local** (`start_at` és UTC → `.astimezone()`), amb fallback a la data del CLI si no hi ha `start_at`. Consulta amb marge (`days_ago + 2`) i pobla `start_at` als objectes retornats (`progress_cb` per al worker, evita doble fetch).
- **`meeting_recording_matcher.py`**: `match(events, recordings)` pur. Score `0.85·temps + 0.15·durada`; temporal per trams (0-5min=1.0, 5-30 lineal a 0.5, 30-60 a 0, >60=0; offset 0 → 0). Llindars AUTO ≥0.9, SUGGESTED ≥0.3. Greedy 1:1. `MANUAL` només el produeix la UI.
- **`obsidian_writer.py` — `ObsidianWriter`** + helper `series_name_for_file()`: totes les operacions al vault. `create_simple/meeting/email_note` (**ja no pre-crea `Temes oberts.md`** — l'usuari el crea manualment). `find_existing_note` (considera els 3 sufixos, evita re-imports). `create_email_thread_note` (escriu fil sencer a `Correus/`, frontmatter `type:correu`, una secció per missatge, adjunts idempotents). `append_to_year_note` = **destí unificat de tots els processats** (capçalera `## <date> - <title>` + `Assistents` + bloc; any del prefix YYMMDD). `mark_as_corrected/processed` (sufix `~`/`*`). **`append_to_historic` / `append_email_to_provider_note` deprecated** (només `wizard_processar_correus.py`; no usar en codi nou).
- **`transcript_corrector.py` — `TranscriptCorrector(vocab, semantic_memory_path, model, threshold_auto=0.85)`**: `detect()` aplica memoritzades (globals del Vocabulari + locals del `semantic_memory.json`), crida LLM amb vocab+memòria+referència+few-shot de falsos positius, filtra confiança <0.85, després filtre fonètic (`is_likely_phonetic`, distància >0.75). **El pre-pass fuzzy (`find_fuzzy_candidates`) està DESACTIVAT**: generava falsos positius (paraules catalanes comunes — `cosa`, `pots`, `Vila` — matchejaven amb termes a 0.7-0.85); el LLM ja veu el vocabulari sencer. Reemplaçament whole-word compartit (`_replace_whole_word`).
- **`phonetic_filter.py`**: `levenshtein/normalized_distance/similarity` (case/accent-insensitive). `is_likely_phonetic` **en ús**; `find_fuzzy_candidates` **no s'usa** (conservada per experiments).
- **`semantic_memory_builder.py` / `semantic_context_retriever.py` / `semantic_models.py`**: construeixen/llegeixen `semantic_memory.json` per sèrie (`build_if_stale`, `load`). Models Pydantic `SemanticMemory` / `SemanticContext`. El JSON conté `person, projects, technical_terms, aliases, recurring_topics`; **s'actualitza només quan l'usuari activa el flag "Memoritzar"** (afegeix alias + paraula correcta).
- **`meeting_analyzer.py` — `MeetingAnalyzer` + `StateFileUpdater`**: `analyze(topics, transcript, brief=False)` (CrewAI). `parse_active_topics` llegeix `Temes oberts.md` (s'atura a "## Altres temes"). `StateFileUpdater.update()` afegeix bullets datats sota cada tema tractat, reescriu "## Altres temes", i **retorna** un bloc markdown amb el resum (el caller decideix on l'escriu → fitxer anual). **No toca els temes `(Tancat)`**: l'usuari els elimina manualment (decisió 2026-05-23 — abans els extreia auto, resultava confús i deixava poca traça).
- **`daily_processor.py` — `DailyProcessor(vocab, model)`**: daily scrum via CrewAI. `process(transcript, attendees)` → `DailyScrumResult`; `format_markdown`.
- **`vocabulary_loader.py` — `VocabularyLoader`**: llegeix `Vocabulari.md` (termes principals + aliases indentats). `load()` (termes nivell 1), `load_aliases()` ({alias:terme}; defensiu contra format antic amb `→`/`()`/`/`), `add_alias`/`add_term` (preserven format; nous a "## Altres (per revisar)"), `load_config()` (secció "## Configuració", e.g. `threshold_auto`).
- **`gui/workers.py` — QThread Workers**:
  - **Retry de xarxa**: `_retry_on_network_error(fn, attempts=3, base_delay=0.6)` amb backoff lineal davant errors de socket transitoris (`EADDRNOTAVAIL`=Errno 49 macOS quan arrenca amb VPN inestable, `ECONNRESET/ETIMEDOUT/timeout/ConnectionError`). Re-llança immediat si **no** és transitori (auth, quota). S'aplica a crides **single-shot** (`CalendarWorker`, `GmailLabelSyncWorker`, setup d'`EmailArchiveWorker`). El bucle per-fil (`peek_thread`/`fetch_thread_full`) **no** porta retry (ja degrada bé i és idempotent).
  - Workers: `CalendarWorker`, `EmailArchiveWorker` (sync+fetch+dispatch+escriptura; `summary` amb `archived_threads`, `skipped_*`, `sync_*`, `errors`), `GmailLabelSyncWorker` (només sync etiquetes), `Correction*`/`BatchCorrectionDetectWorker`, `DailyProcessorWorker`, `MeetingAnalyzerWorker` (`brief=True`), `SummaryWorker`, `ProjectInitWorker`, `PlaudListWorker`, `PlaudTranscriptWorker` (emet `file_id` per descartar resultats stale).
- **`gui/widgets/`**: `pairing_view.py` (`PairingView`: dues taules paral·leles, auto-match, `get_state()` totes les òrfenes / `get_selected_orphan_recordings()` només seleccionades), `transcript_editor.py`, `correction_checklist.py`.
  - **`inline_correction_editor.py`**: estats `pending`(groc)/`accepted`(verd)/`validated`(blau, paraula correcta)/`rejected`(gris)/`manual`/`not_found`. Fila 2: `"original" → [target editable]` (l'usuari pot modificar la proposta). Fila 3: **✓ Acceptar** (aplica + opcionalment memoritza alias), **★ És correcta** (afegeix `original` al Vocabulari com a terme, no toca text), **✗ Rebutjar**. Scope d'alias: **Cap**(default) / **Aquesta sèrie**(`semantic_memory.json`) / **Sempre**(`Vocabulari.md`). **Reemplacen totes les ocurrències whole-word** (una paraula: `FindWholeWords`; frases multi-paraula: `QRegularExpression (?<!\w)…(?!\w)`). Conseqüència: dues correccions amb el mateix `original` → acceptar-ne una marca l'altra `manual`. Botons sempre clicables en `manual`/`not_found` (no quedar atrapat).

## Wizard Transcripcio — Flux

3 pàgines (`QStackedWidget`) + iteració. Pàg.0 `PairingView` (càrrega paral·lela `CalendarWorker`+`PlaudListWorker`, auto-match) → cua `pairs + orphan_recordings_seleccionades` → per item: pàg.1 arbre de carpetes (seleccionables les que tenen `Reunions/`; suporta niu via `_has_series_descendant`; no navega dins `Reunions/`) → pàg.2 baixa transcripció + edita → desa `create_simple_note`. Per orfes es fabrica `{title:rec.name, start, end, duration, attendees:[]}` (**`duration` imprescindible** per `_gen_content`).

**Gotchas:**
- **Re-imports duplicats**: en confirmar carpeta, `_confirm_if_note_exists()` → `find_existing_note` (3 sufixos). Si existeix: QMessageBox **Ometre**(default)/**Importar igualment**. Cal perquè `PairingView` recarrega el dia sense saber què ja es va importar.
- **Workers stale**: `PlaudTranscriptWorker` emet `file_id`; si l'usuari ha avançat, s'ignora.
- **Enrere**: només a pàg.2 (re-triar carpeta sense reaparellar). No es torna a pàg.0 un cop iniciada la iteració.

## Wizard Processar — Flux

2 pàgines. Pàg.0: taula de notes corregides, `QComboBox` per fila amb 4 opcions:
- **Resum** (`SummaryWorker`, litellm) — resum estructurat.
- **Resum+ordre dia** (`MeetingAnalyzerWorker`, CrewAI) — compara amb `Temes oberts.md`, actualitza el fitxer, escriu resum a l'anual, reescriu `Ordre del dia propera reunió.md`.
- **Resum+ordre dia (breu)** — igual amb `brief=True`.
- **Sincro** (`DailyProcessorWorker`, CrewAI) — daily scrum per persona.

**Default per fila** (`_default_option_for_path`): `Sincronització/`→Sincro, `Seguiment/`→Resum+ordre dia, resta→Resum.

**Flux i gotchas:**
- **Pre-flight** (`_validate_pre_flight`): per a cada `Resum+ordre dia` comprova que existeix `<subfolder>/Temes oberts.md`; si falta, QMessageBox bloquejant (l'usuari el crea manualment — decisió explícita per evitar fitxers buits sense criteri). **No continua fins resoldre-ho.**
- **Ordenació cronològica** (`_sort_notes_by_date`): per `date` ASC abans de la cua (els temes oberts evolucionen; year notes llegibles). YYMMDD lexicogràfic = cronològic.
- **Escriptura** (`_process_next`, branca per `item.option`): tots criden `append_to_year_note`. Sincro retalla la 1a línia `# title - date`. Resum+ordre dia escriu el bloc de `StateFileUpdater.update()` (buit→no escriu) i **no elimina** els `(Tancat)`.
- **Ordre dins el `try`**: **primer** `append_to_year_note`, **després** `mark_as_processed` — si la primera falla, la nota queda sense marcar (cap fals positiu).
- **Decoupling**: el processat **mai mira el path** — la decisió ve del selector (el path només és el default).
- **Errors UI**: cel·la "Estat" mostra primera línia truncada a 60 chars; tooltip complet; traceback a `data/app.log`.

## Wizard Correus — Flux

**Objectiu**: arxivar fils Gmail al vault segons etiquetes. Vault = source of truth. Tot **idempotent** (pots executar cada dia sense duplicar).

- **Convenció d'etiquetes**: **nom de fulla** de la sèrie, pla (sense `/`). Una per sèrie amb `Correus/`. **Per què fulla i no camí**: la sèrie viatja entre top-levels; la fulla és invariant, així els fils històrics segueixen lligats. Requereix fulles úniques (col·lisions s'avisen). Migració format antic → `migrate_gmail_labels.py`.
- **Sync vault→Gmail**: a l'inici, `EmailArchiveWorker` crea les etiquetes que falten; avisa d'òrfenes; **no esborra mai**.
- **Sèrie tancada**: a `Temes seguiment tancats/X/` conserva l'etiqueta `X` (`closed_by_active_label`). Correu amb etiqueta tancada → s'arxiva igualment a la carpeta tancada, `[TANCADA]` al log + `sync_closed_warnings`.
- **Dispatcher**: múltiples etiquetes vault → prioritat `Projectes > Proveïdors > Seguiment > Reunions vàries`. Primary → `labels:`; resta → `tags:`; no-vault s'ignoren.
- **Idempotència** (`<vault>/zConfig/.processed_threads.json`, `{thread_id: {message_count, archived_at, dest_path}}`): `peek_thread` abans del full; si `message_count` no ha crescut, salta; si ha crescut → `fetch_thread_full` + regenera nota sencera (adjunts amb bytes idèntics es reusen).
- **Format nota** (`<dest>/Correus/YYMMDD_<assumpte>.md`): frontmatter `type:correu, thread_id, data, assumpte, labels:[primary], tags:[extras]`; una secció `## YYYY-MM-DD HH:MM — Nom <email>` per missatge (`(resposta)` des del 2n); adjunts a `Fitxers/` amb wikilinks. Data = primer missatge.
- **Finestra de dies**: l'arxivat processa un **rang** `[dia_final − (dies−1), dia_final]` (ambdós inclusius). `gmail_fetcher.build_date_range_query(start, end)` construeix `after:start before:end+1` (`before` exclusiu a Gmail); `list_thread_ids_for_range` el consulta (un fil amb missatges en diversos dies del rang apareix un sol cop). `list_thread_ids_for_day` delega al de rang. `EmailArchiveWorker` rep `start_day`/`end_day`.
- **UI 2 pàgines**: selector "fins al dia" (default avui) + spinbox "dies enrere" (default **7**, rang 1–90) → log live + barra + resum. "Aturar" avorta entre fils (no desfà). Log a `data/email_archive_<ts>.log`.
- **Què NO fa**: no esborra correus ni etiquetes a Gmail, no toca `semantic_memory.json`/`Vocabulari.md`, no mou/renombra carpetes (només crea `Correus/`/`Fitxers/`).
- **Gotchas operatius**:
  - **Model de finestra** (default 7 dies): no hi ha sweep enrere il·limitat — un fil amb missatges *únicament* fora de la finestra no es processa. Amb 7 dies, n'hi ha prou amb executar-ho un cop per setmana; si has estat fora més temps, amplia "dies enrere" (o mou el "fins al dia") per cobrir el buit. La idempotència (`peek_thread` + store) fa que re-cobrir dies ja arxivats sigui barat i sense duplicats.
  - **Correus enviats**: inclosos si formen part d'un fil etiquetat. Per arxivar un enviat solo, aplica l'etiqueta manualment a Gmail.
  - **Forçar re-arxivat**: esborra l'entrada a `.processed_threads.json` i re-executa amb una finestra que cobreixi la data del fil.
  - **Inline-attachment**: descarta `image/* + Content-ID`. Si trobes adjunts útils descartats o logos colats, mira el Content-ID al missatge font abans d'ajustar `is_inline_attachment`.

## Wizard Correccio — Flux

3 pàgines. Pàg.0: notes sense corregir + dos checkboxes:
- **`chk_skip_review`** (auto-aplicar sense revisió): aplica totes les propostes i marca corregides sense memoritzar res.
- **`chk_save_comparison`**: desa 3 còpies a `/tmp/comparacio_correccions/` (`_original`/`_auto`/`_manual`) per fer `diff`.

Pàg.1 batch: crea `TranscriptCorrector` (referència = nota processada més recent, `SemanticContext` via builder+retriever), `BatchCorrectionDetectWorker`. Notes sense correccions → corregides directament. Pàg.2 revisió: `InlineCorrectionEditor`; en desar actualitza `semantic_memory.json`, `Vocabulari.md` (alias + termes validats), transcript corregit, marca `~`.

**Observació empírica**: l'auto resol típicament el 95-100% dels errors útils en seguiments rutinaris; la revisió manual aporta sobretot a reunions amb conceptes nous/ambigus. Per dailies/seguiments, `skip_review=True` és suficient.

## Tests

`unittest` (sense pytest) a `tests/`. **Regla**: cada funcionalitat nova → test nou + executar tota la suite.

```bash
uv run python -m unittest discover -s tests
```
