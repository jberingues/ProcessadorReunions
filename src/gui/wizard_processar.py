import re
import yaml
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QPushButton, QTableWidget, QTableWidgetItem, QLabel,
    QProgressBar, QMessageBox, QHeaderView, QWidget, QAbstractItemView,
    QComboBox
)
from vocabulary_loader import VocabularyLoader
from workers import (
    DailyProcessorWorker,
    MeetingAnalyzerWorker
)


OPTION_RESUM_ORDRE = "Resum+ordre dia"
OPTION_RESUM_ORDRE_BREU = "Resum+ordre dia (breu)"
OPTION_RESUM = "Resum"
OPTION_SINCRO = "Sincro"
ALL_OPTIONS = [OPTION_RESUM_ORDRE, OPTION_RESUM_ORDRE_BREU, OPTION_RESUM, OPTION_SINCRO]

# Opcions que generen un Ordre del dia i deixen la nota '+' (pendent de
# consolidar). Comparteixen el fitxer 'Ordre del dia - <sèrie>.md' → subjectes a
# l'invariant "una consolidació pendent per sèrie" (vegeu _validate_pre_flight).
OPTIONS_PENDING_CONSOLIDATION = (OPTION_RESUM_ORDRE, OPTION_RESUM_ORDRE_BREU, OPTION_RESUM)


def _default_option_for_path(path: Path) -> str:
    # Unificat: tota reunió que no sigui de sincronització rep el tractament
    # complet (genera Ordre del dia → consolidació posterior a Temes oberts +
    # fitxer anual). Ja no hi ha l'opció "Resum" simple.
    if 'Sincronització' in path.parts:
        return OPTION_SINCRO
    return OPTION_RESUM_ORDRE


def _sort_notes_by_date(notes_with_options: list[tuple[dict, str]]) -> list[tuple[dict, str]]:
    """Ordena pairs (note, option) per note['date'] ascendent (cronològic).
    YYMMDD lexicogràfic == cronològic perquè el format és fix.
    """
    return sorted(notes_with_options, key=lambda p: p[0]['date'])


@dataclass
class _BatchItem:
    note: dict
    option: str = OPTION_RESUM_ORDRE
    status: str = 'pending'  # pending|running|saved|skipped|error
    error_msg: str | None = None
    processing_result: object = None
    processing_markdown: str | None = None
    all_topics: list = field(default_factory=list)
    temes_oberts_path: object = None


class WizardProcessar(QDialog):
    def __init__(self, calendar, obsidian, parent=None):
        super().__init__(parent)
        self.calendar = calendar
        self.obsidian = obsidian
        self.setWindowTitle("Processar reunions")
        self.setMinimumSize(800, 550)

        self.notes = []
        self.row_combos: dict[int, QComboBox] = {}
        self.batch_results: dict[int, _BatchItem] = {}
        self._batch_queue: list[int] = []
        self._batch_done_count = 0
        self.worker_processing = None

        layout = QVBoxLayout(self)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        nav = QHBoxLayout()
        self.btn_back = QPushButton("Enrere")
        self.btn_back.clicked.connect(self._go_back)
        self.btn_next = QPushButton("Endavant")
        self.btn_next.clicked.connect(self._go_next)
        self.btn_cancel = QPushButton("Cancel·lar")
        self.btn_cancel.clicked.connect(self.reject)
        nav.addWidget(self.btn_back)
        nav.addStretch()
        nav.addWidget(self.btn_cancel)
        nav.addWidget(self.btn_next)
        layout.addLayout(nav)

        self._build_page0_notes()
        self._build_page1_batch()

        self._update_nav()
        self._load_notes()

    # -- Pàgina 0: Seleccionar notes --

    def _build_page0_notes(self):
        page = QVBoxLayout()
        w = QWidget()
        w.setLayout(page)

        header = QHBoxLayout()
        header.addWidget(QLabel("Reunions corregides per processar:"))
        header.addStretch()
        self.lbl_sel_count = QLabel("0 seleccionades")
        header.addWidget(self.lbl_sel_count)
        self.btn_sel_all = QPushButton("Sel. tot")
        self.btn_sel_all.clicked.connect(self._toggle_select_all)
        header.addWidget(self.btn_sel_all)
        page.addLayout(header)

        self.table_notes = QTableWidget()
        self.table_notes.setColumnCount(3)
        self.table_notes.setHorizontalHeaderLabels(["Data", "Títol", "Tipus de processat"])
        self.table_notes.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_notes.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        header_view = self.table_notes.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table_notes.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_notes.itemSelectionChanged.connect(self._on_selection_changed)
        page.addWidget(self.table_notes)

        self.stack.addWidget(w)

    def _load_notes(self):
        self.notes = self.obsidian.find_corrected_notes()
        self.row_combos.clear()
        self.table_notes.setRowCount(len(self.notes))
        for i, n in enumerate(self.notes):
            self.table_notes.setItem(i, 0, QTableWidgetItem(n['date']))
            self.table_notes.setItem(i, 1, QTableWidgetItem(n['title']))

            combo = QComboBox()
            combo.addItems(ALL_OPTIONS)
            combo.setCurrentText(_default_option_for_path(n['path']))
            self.row_combos[i] = combo
            self.table_notes.setCellWidget(i, 2, combo)

    def _toggle_select_all(self):
        if self.table_notes.selectionModel().selectedRows():
            self.table_notes.clearSelection()
        else:
            self.table_notes.selectAll()

    def _on_selection_changed(self):
        count = len(self.table_notes.selectionModel().selectedRows())
        self.lbl_sel_count.setText(f"{count} seleccionades")
        self.btn_sel_all.setText("Desel. tot" if count == len(self.notes) else "Sel. tot")

    # -- Pàgina 1: Progrés batch --

    def _build_page1_batch(self):
        page = QVBoxLayout()
        w = QWidget()
        w.setLayout(page)

        self.lbl_batch_status = QLabel("Preparant...")
        page.addWidget(self.lbl_batch_status)

        self.progress_batch = QProgressBar()
        page.addWidget(self.progress_batch)

        self.table_batch = QTableWidget()
        self.table_batch.setColumnCount(4)
        self.table_batch.setHorizontalHeaderLabels(["Data", "Títol", "Tipus", "Estat"])
        self.table_batch.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_batch.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table_batch.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_batch.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        page.addWidget(self.table_batch)

        self.stack.addWidget(w)

    # -- Validació prèvia --

    def _validate_pre_flight(self, selected_rows: list[int]) -> list[str]:
        """Retorna llista d'errors (buida si tot OK).

        Per files amb 'Resum+ordre dia' (o variant breu), comprova l'invariant
        "una consolidació pendent per sèrie": com que l'Ordre del dia es
        sobreescriu a cada fase 1, una sèrie no pot tenir dues reunions pendents
        de consolidar alhora. Es bloqueja si ja hi ha una nota '+' a la sèrie, o
        si se n'han seleccionat dues de la mateixa sèrie al mateix lot.

        (El Temes oberts.md ja no es valida aquí: si falta, es crea buit
        automàticament a la fase 1 via ObsidianWriter.ensure_temes_oberts.)
        """
        errors = []
        seen_series: dict[Path, dict] = {}
        for r in selected_rows:
            option = self.row_combos[r].currentText()
            if option not in OPTIONS_PENDING_CONSOLIDATION:
                continue
            note = self.notes[r]
            reunions_dir = note['path'].parent
            series_name = reunions_dir.parent.name

            pending = sorted(reunions_dir.glob('*+.md'))
            if pending:
                errors.append(
                    f"{note['date']} - {note['title']}: la sèrie {series_name} "
                    f"ja té una reunió pendent de consolidar ({pending[0].name}). "
                    f"Consolida-la primer."
                )

            if reunions_dir in seen_series:
                other = seen_series[reunions_dir]
                errors.append(
                    f"{note['date']} - {note['title']}: hi ha dues reunions "
                    f"seleccionades de la sèrie {series_name} "
                    f"({other['date']} i {note['date']}). Processa'n una, "
                    f"consolida-la i després l'altra."
                )
            else:
                seen_series[reunions_dir] = note
        return errors

    # -- Lògica de batch seqüencial --

    def _prepare_and_start_batch(self, selected_rows: list[int]):
        pairs = [(self.notes[r], self.row_combos[r].currentText()) for r in selected_rows]
        pairs = _sort_notes_by_date(pairs)
        selected_notes = [n for n, _ in pairs]
        selected_options = [opt for _, opt in pairs]

        self.batch_results.clear()
        self._batch_queue.clear()
        self._batch_done_count = 0

        self.table_batch.setRowCount(len(selected_notes))
        self.progress_batch.setRange(0, len(selected_notes))
        self.progress_batch.setValue(0)

        for idx, (note, option) in enumerate(zip(selected_notes, selected_options)):
            self.table_batch.setItem(idx, 0, QTableWidgetItem(note['date']))
            self.table_batch.setItem(idx, 1, QTableWidgetItem(note['title']))
            self.table_batch.setItem(idx, 2, QTableWidgetItem(option))
            self.table_batch.setItem(idx, 3, QTableWidgetItem("Pendent"))
            self.batch_results[idx] = _BatchItem(note=note, option=option)
            self._batch_queue.append(idx)

        self.lbl_batch_status.setText(f"Processant 0/{len(selected_notes)}...")
        self._process_next()

    def _process_next(self):
        if not self._batch_queue:
            self._on_batch_all_done()
            return

        idx = self._batch_queue.pop(0)
        item = self.batch_results[idx]
        item.status = 'running'
        self.table_batch.setItem(idx, 3, QTableWidgetItem("Processant..."))

        note = item.note
        # Defensa contra llistes obsoletes: si la nota ja s'ha processat (renombrada
        # ~ -> + / *) en una passada anterior, el path ~ ja no existeix. L'ometem en
        # comptes de petar amb FileNotFoundError.
        if not note['path'].exists():
            self._batch_skip(idx, "ja processada (recarrega la llista)")
            return
        try:
            transcript = self.obsidian.read_transcript(note['path'])
            if item.option == OPTION_SINCRO:
                self._batch_start_sincro(idx, note, transcript)
            elif item.option == OPTION_RESUM:
                self._batch_start_resum(idx, note, transcript)
            elif item.option in (OPTION_RESUM_ORDRE, OPTION_RESUM_ORDRE_BREU):
                brief = (item.option == OPTION_RESUM_ORDRE_BREU)
                self._batch_start_seguiment(idx, note, transcript, brief)
            else:
                self._batch_skip(idx, f"Opció desconeguda: {item.option}")
        except Exception as e:
            self._batch_error(idx, str(e))

    def _batch_start_sincro(self, idx, note, transcript):
        vocab_path = self.obsidian.vault / 'Reunions' / 'zConfig' / 'Vocabulari.md'
        vocab = VocabularyLoader(vocab_path).load()

        attendees = self._extract_attendees_from_note(note['path'])
        speaker_emails = self._extract_speaker_emails_from_note(note['path'])

        daily_transcript = transcript
        if not speaker_emails:
            found_emails = set(re.findall(
                r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b',
                daily_transcript
            ))
            for email in found_emails:
                name = self.calendar._resolve_name(email)
                if name != email:
                    speaker_emails[email] = name

        for email, name in speaker_emails.items():
            daily_transcript = daily_transcript.replace(email, name)

        transcript_speakers = dict.fromkeys(
            re.findall(r'^\d{2}:\d{2}:\d{2} (.+)$', daily_transcript, re.MULTILINE)
        )
        seen_names = {a['name'] for a in attendees}
        for speaker in transcript_speakers:
            if not re.match(r'^Speaker \d+$', speaker) and speaker not in seen_names:
                attendees = attendees + [{'name': speaker}]
                seen_names.add(speaker)

        from daily_processor import DailyProcessor
        processor = DailyProcessor(vocab)
        date_obj = datetime.strptime(note['date'], '%y%m%d')
        date_str = date_obj.strftime('%d/%m/%Y')

        self.worker_processing = DailyProcessorWorker(
            processor, daily_transcript, attendees, note['title'], date_str, self
        )
        self.worker_processing.finished.connect(
            lambda r, md, i=idx: self._batch_on_daily_finished(i, r, md)
        )
        self.worker_processing.error.connect(
            lambda msg, i=idx: self._batch_error(i, msg)
        )
        self.worker_processing.start()

    def _batch_start_seguiment(self, idx, note, transcript, brief: bool):
        item = self.batch_results[idx]
        # Si la sèrie no té Temes oberts.md encara, es crea buit (amb '### Altres
        # temes') automàticament — decisió 2026-06-15: un Temes oberts buit és
        # vàlid i no val la pena bloquejar per fer-lo crear a mà.
        temes_path = self.obsidian.ensure_temes_oberts(note['path'].parent.parent)

        from meeting_analyzer import MeetingAnalyzer, parse_active_topics
        # Temes oberts pot estar buit (sèrie sense temes oberts a seguir): en
        # aquest cas tot el que es tracti anirà a "Altres temes" i l'ordre del
        # dia surt amb l'agenda buida. No es descarta la reunió.
        topics = parse_active_topics(temes_path)

        item.all_topics = topics
        item.temes_oberts_path = temes_path
        analyzer = MeetingAnalyzer()

        self.worker_processing = MeetingAnalyzerWorker(
            analyzer, topics, transcript, self, brief=brief
        )
        self.worker_processing.finished.connect(
            lambda r, i=idx: self._batch_on_seguiment_finished(i, r)
        )
        self.worker_processing.error.connect(
            lambda msg, i=idx: self._batch_error(i, msg)
        )
        self.worker_processing.start()

    def _batch_start_resum(self, idx, note, transcript):
        # Resum lliure: NO llegeix Temes oberts ni en crea cap (un resum pur no
        # segueix temes). El LLM detecta els temes pel seu compte (summarize=True).
        from meeting_analyzer import MeetingAnalyzer
        analyzer = MeetingAnalyzer()

        self.worker_processing = MeetingAnalyzerWorker(
            analyzer, [], transcript, self, summarize=True
        )
        self.worker_processing.finished.connect(
            lambda r, i=idx: self._batch_on_resum_finished(i, r)
        )
        self.worker_processing.error.connect(
            lambda msg, i=idx: self._batch_error(i, msg)
        )
        self.worker_processing.start()

    # -- Callbacks de workers --

    def _batch_on_daily_finished(self, idx, processing_result, md_output):
        item = self.batch_results[idx]
        item.processing_result = processing_result
        item.processing_markdown = md_output
        try:
            note = item.note
            attendees = self._format_attendees_string(note['path'])
            # DailyProcessor genera '# title - date_str' a la primera línia,
            # que duplicaria la capçalera del bloc anual. La retallem.
            lines = md_output.splitlines()
            if lines and lines[0].startswith('# '):
                content = '\n'.join(lines[1:]).lstrip('\n')
            else:
                content = md_output
            self.obsidian.append_to_year_note(
                note['path'], note['date'], note['title'], attendees, content
            )
            self.obsidian.mark_as_processed(note['path'])
            self._batch_mark_done(idx)
        except Exception as e:
            self._batch_error(idx, str(e))
            return
        self._process_next()

    def _batch_on_seguiment_finished(self, idx, processing_result):
        # Fase 1: escriu NOMÉS l'Ordre del dia propera reunió i marca la nota '+'
        # (pendent de consolidar). Temes oberts i el fitxer anual NO es toquen
        # aquí: es propaguen a la fase 2 (Consolidar) a partir de l'Ordre del dia
        # ja validat manualment per l'usuari, garantint fidelitat.
        item = self.batch_results[idx]
        item.processing_result = processing_result
        try:
            from meeting_analyzer import format_ordre_del_dia, with_pending_marker
            note = item.note

            date_obj = datetime.strptime(note['date'], '%y%m%d')
            ordre_path = self.obsidian.ordre_del_dia_path(note['path'].parent.parent)
            ordre_content = format_ordre_del_dia(processing_result, item.all_topics, date_obj.strftime('%d/%m/%Y'))
            ordre_path.write_text(with_pending_marker(ordre_content), encoding='utf-8')

            self.obsidian.mark_as_ordre_generated(note['path'])
            self._batch_mark_done(idx)
        except Exception as e:
            self._batch_error(idx, str(e))
            return
        self._process_next()

    def _batch_on_resum_finished(self, idx, processing_result):
        # Fase 1 (opció Resum): escriu el resum lliure a l'Ordre del dia amb el
        # marcador de tipus 'resum' (perquè la fase 2 propagui NOMÉS a l'anual,
        # sense tocar Temes oberts) i marca la nota '+' (pendent de consolidar).
        item = self.batch_results[idx]
        item.processing_result = processing_result
        try:
            from meeting_analyzer import format_resum, with_pending_marker
            note = item.note

            date_obj = datetime.strptime(note['date'], '%y%m%d')
            ordre_path = self.obsidian.ordre_del_dia_path(note['path'].parent.parent)
            ordre_content = format_resum(processing_result, date_obj.strftime('%d/%m/%Y'))
            ordre_path.write_text(
                with_pending_marker(ordre_content, kind='resum'), encoding='utf-8'
            )

            self.obsidian.mark_as_ordre_generated(note['path'])
            self._batch_mark_done(idx)
        except Exception as e:
            self._batch_error(idx, str(e))
            return
        self._process_next()

    # -- Helpers d'estat de batch --

    def _batch_mark_done(self, idx):
        self.batch_results[idx].status = 'saved'
        self.table_batch.setItem(idx, 3, QTableWidgetItem("Desat ✓"))
        self._batch_done_count += 1
        self.progress_batch.setValue(self._batch_done_count)
        total = len(self.batch_results)
        self.lbl_batch_status.setText(f"Processant {self._batch_done_count}/{total}...")

    def _batch_skip(self, idx, reason):
        self.batch_results[idx].status = 'skipped'
        self.table_batch.setItem(idx, 3, QTableWidgetItem(f"Omesa: {reason}"))
        self._batch_done_count += 1
        self.progress_batch.setValue(self._batch_done_count)
        self._process_next()

    def _batch_error(self, idx, msg):
        self.batch_results[idx].status = 'error'
        self.batch_results[idx].error_msg = msg
        # Cel·la: text curt truncat. Tooltip: missatge complet (al passar el cursor).
        short = (msg or 'desconegut').splitlines()[0]
        if len(short) > 60:
            short = short[:57] + '...'
        cell = QTableWidgetItem(f"Error: {short}")
        cell.setToolTip(msg or 'desconegut')
        self.table_batch.setItem(idx, 3, cell)
        self._batch_done_count += 1
        self.progress_batch.setValue(self._batch_done_count)
        self._process_next()

    def _on_batch_all_done(self):
        saved = sum(1 for r in self.batch_results.values() if r.status == 'saved')
        skipped = sum(1 for r in self.batch_results.values() if r.status == 'skipped')
        errors = sum(1 for r in self.batch_results.values() if r.status == 'error')

        parts = [f"{saved} desades"]
        if skipped:
            parts.append(f"{skipped} omeses")
        if errors:
            parts.append(f"{errors} errors")
        self.lbl_batch_status.setText("Completat: " + ", ".join(parts))
        self._update_nav()

    # -- Navegació --

    def _current_page(self):
        return self.stack.currentIndex()

    def _go_back(self):
        if self._current_page() == 1:
            if self.worker_processing and self.worker_processing.isRunning():
                ret = QMessageBox.question(
                    self, "Abortar?",
                    "Hi ha un processament en curs. Vols abortar-lo?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if ret != QMessageBox.StandardButton.Yes:
                    return
                self.worker_processing.quit()
                self.worker_processing.wait(3000)
                self._batch_queue.clear()
            # Recarrega la llista: el lot anterior ha renombrat notes (~ -> + / *)
            # i els Path cachejats a self.notes han quedat obsolets. Sense això,
            # re-processar llegiria fitxers ~ inexistents (FileNotFoundError).
            self._load_notes()
            self.stack.setCurrentIndex(0)
            self._update_nav()

    def _go_next(self):
        idx = self._current_page()

        if idx == 0:
            rows = self.table_notes.selectionModel().selectedRows()
            if not rows:
                return
            selected_rows = sorted(r.row() for r in rows)
            errors = self._validate_pre_flight(selected_rows)
            if errors:
                QMessageBox.warning(
                    self,
                    "No es pot continuar",
                    "Cal resoldre el següent abans de processar:\n\n"
                    + "\n".join(f"• {e}" for e in errors)
                    + "\n\nConsolida les reunions pendents (o processa una sola "
                    "reunió per sèrie en aquest lot)."
                )
                return
            self.stack.setCurrentIndex(1)
            self._update_nav()
            self._prepare_and_start_batch(selected_rows)
            return

        elif idx == 1:
            self.accept()

    def _update_nav(self):
        idx = self._current_page()
        self.btn_back.setEnabled(idx == 1)

        if idx == 0:
            self.btn_next.setText("Endavant")
            self.btn_next.setEnabled(True)
        elif idx == 1:
            batch_running = self.worker_processing is not None and self.worker_processing.isRunning()
            self.btn_next.setText("Tancar")
            self.btn_next.setEnabled(not batch_running and not self._batch_queue)

    # -- Utilitats d'extracció de notes --

    def _extract_speaker_emails_from_note(self, path) -> dict:
        content = path.read_text(encoding='utf-8')
        if content.startswith('---'):
            end = content.find('---', 3)
            if end != -1:
                frontmatter = yaml.safe_load(content[3:end])
                if frontmatter and 'speaker_emails' in frontmatter:
                    return frontmatter['speaker_emails'] or {}
        return {}

    def _extract_attendees_from_note(self, path) -> list[dict]:
        content = path.read_text(encoding='utf-8')
        if content.startswith('---'):
            end = content.find('---', 3)
            if end != -1:
                frontmatter = yaml.safe_load(content[3:end])
                if frontmatter and 'attendees' in frontmatter:
                    attendees = []
                    for entry in frontmatter['attendees']:
                        name = entry.strip().strip('"').strip()
                        if name.startswith('[[') and name.endswith(']]'):
                            name = name[2:-2]
                        attendees.append({'name': name})
                    return attendees
        return []

    def _format_attendees_string(self, note_path) -> str:
        atts = self._extract_attendees_from_note(note_path)
        return ', '.join(a['name'] for a in atts)
