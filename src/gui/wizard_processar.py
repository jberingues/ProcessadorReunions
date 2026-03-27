import re
import yaml
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QPushButton, QTableWidget, QTableWidgetItem, QLabel,
    QProgressBar, QMessageBox, QHeaderView, QWidget, QAbstractItemView
)
from PySide6.QtCore import Qt
from vocabulary_loader import VocabularyLoader
from workers import (
    DailyProcessorWorker,
    MeetingAnalyzerWorker, SummaryWorker
)


@dataclass
class _BatchItem:
    note: dict
    status: str = 'pending'  # pending|running|saved|skipped|error
    error_msg: str | None = None
    processing_type: str | None = None
    processing_result: object = None
    processing_markdown: str | None = None
    all_topics: list = field(default_factory=list)
    estat_path: object = None


class WizardProcessar(QDialog):
    def __init__(self, calendar, obsidian, parent=None, mode='normal'):
        super().__init__(parent)
        self.calendar = calendar
        self.obsidian = obsidian
        self.mode = mode
        self.setWindowTitle("Processar curt reunions" if mode == 'curt' else "Processar reunions")
        self.setMinimumSize(750, 550)

        self.notes = []
        self.batch_results: dict[int, _BatchItem] = {}
        self._batch_queue: list[int] = []
        self._batch_done_count = 0
        self.worker_processing = None

        layout = QVBoxLayout(self)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        # Botons navegació
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
        label_text = "Reunions de Seguiment corregides per processar:" if self.mode == 'curt' else "Reunions corregides per processar:"
        header.addWidget(QLabel(label_text))
        header.addStretch()
        self.lbl_sel_count = QLabel("0 seleccionades")
        header.addWidget(self.lbl_sel_count)
        self.btn_sel_all = QPushButton("Sel. tot")
        self.btn_sel_all.clicked.connect(self._toggle_select_all)
        header.addWidget(self.btn_sel_all)
        page.addLayout(header)

        self.table_notes = QTableWidget()
        self.table_notes.setColumnCount(2)
        self.table_notes.setHorizontalHeaderLabels(["Data", "Títol"])
        self.table_notes.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_notes.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table_notes.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_notes.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_notes.itemSelectionChanged.connect(self._on_selection_changed)
        page.addWidget(self.table_notes)

        self.stack.addWidget(w)

    def _load_notes(self):
        notes = self.obsidian.find_corrected_notes()
        if self.mode == 'curt':
            notes = [n for n in notes if 'Seguiment' in n['path'].parts]
        self.notes = notes
        self.table_notes.setRowCount(len(self.notes))
        for i, n in enumerate(self.notes):
            self.table_notes.setItem(i, 0, QTableWidgetItem(n['date']))
            self.table_notes.setItem(i, 1, QTableWidgetItem(n['title']))

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
        self.table_batch.setColumnCount(3)
        self.table_batch.setHorizontalHeaderLabels(["Data", "Títol", "Estat"])
        self.table_batch.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_batch.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table_batch.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_batch.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        page.addWidget(self.table_batch)

        self.stack.addWidget(w)

    # -- Lògica de batch seqüencial --

    def _prepare_and_start_batch(self, selected_rows: list[int]):
        selected_notes = [self.notes[r] for r in selected_rows]

        self.batch_results.clear()
        self._batch_queue.clear()
        self._batch_done_count = 0

        self.table_batch.setRowCount(len(selected_notes))
        self.progress_batch.setRange(0, len(selected_notes))
        self.progress_batch.setValue(0)

        for idx, note in enumerate(selected_notes):
            self.table_batch.setItem(idx, 0, QTableWidgetItem(note['date']))
            self.table_batch.setItem(idx, 1, QTableWidgetItem(note['title']))
            self.table_batch.setItem(idx, 2, QTableWidgetItem("Pendent"))
            self.batch_results[idx] = _BatchItem(note=note)
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
        self.table_batch.setItem(idx, 2, QTableWidgetItem("Processant..."))

        note = item.note
        try:
            transcript = self.obsidian.read_transcript(note['path'])
            path_parts = note['path'].parts

            if 'Sincronització' in path_parts:
                self._batch_start_sincronitzacio(idx, note, transcript)
            elif 'Seguiment' in path_parts:
                subtype = self._extract_subtype_from_note(note['path'])
                if subtype == 'puntual':
                    self._batch_start_seguiment_puntual(idx, note, transcript)
                else:
                    self._batch_start_seguiment(idx, note, transcript)
            elif 'Proveïdors' in path_parts:
                self._batch_start_proveidors(idx, note, transcript)
            else:
                self._batch_skip(idx, "Tipus no reconegut")
        except Exception as e:
            self._batch_error(idx, str(e))

    def _batch_start_sincronitzacio(self, idx, note, transcript):
        item = self.batch_results[idx]
        item.processing_type = 'sincronitzacio'

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

    def _batch_start_seguiment(self, idx, note, transcript):
        item = self.batch_results[idx]
        item.processing_type = 'seguiment'

        title = note['title']
        estat_nom = title if title else 'Estat actual'
        estat_path = note['path'].parent.parent / f'{estat_nom}.md'
        if not estat_path.exists():
            estat_path.write_text("", encoding='utf-8')

        from meeting_analyzer import MeetingAnalyzer, parse_active_topics
        topics = parse_active_topics(estat_path)

        if not topics:
            self._batch_skip(idx, "Sense temes oberts")
            return

        item.all_topics = topics
        item.estat_path = estat_path
        analyzer = MeetingAnalyzer()

        self.worker_processing = MeetingAnalyzerWorker(
            analyzer, topics, transcript, self, brief=(self.mode == 'curt')
        )
        self.worker_processing.finished.connect(
            lambda r, i=idx: self._batch_on_seguiment_finished(i, r)
        )
        self.worker_processing.error.connect(
            lambda msg, i=idx: self._batch_error(i, msg)
        )
        self.worker_processing.start()

    def _batch_start_seguiment_puntual(self, idx, note, transcript):
        self.batch_results[idx].processing_type = 'seguiment_puntual'
        self.worker_processing = SummaryWorker(transcript, self)
        self.worker_processing.finished.connect(
            lambda s, i=idx: self._batch_on_summary_finished(i, s)
        )
        self.worker_processing.error.connect(
            lambda msg, i=idx: self._batch_error(i, msg)
        )
        self.worker_processing.start()

    def _batch_start_proveidors(self, idx, note, transcript):
        self.batch_results[idx].processing_type = 'proveidors'
        self.worker_processing = SummaryWorker(transcript, self)
        self.worker_processing.finished.connect(
            lambda s, i=idx: self._batch_on_summary_finished(i, s)
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
            date_obj = datetime.strptime(note['date'], '%y%m%d')
            year = date_obj.strftime('%Y')
            resum_path = note['path'].parent.parent / f'Resum reunions {year}.md'

            if not resum_path.exists():
                resum_path.parent.mkdir(parents=True, exist_ok=True)
                header = f"---\ntype: resum-reunions\nyear: {year}\n---\n\n"
                resum_path.write_text(header + md_output + '\n', encoding='utf-8')
            else:
                existing = resum_path.read_text(encoding='utf-8')
                resum_path.write_text(existing + '\n---\n\n' + md_output + '\n', encoding='utf-8')

            self.obsidian.mark_as_processed(note['path'])
            self._batch_mark_done(idx)
        except Exception as e:
            self._batch_error(idx, str(e))
            return
        self._process_next()

    def _batch_on_seguiment_finished(self, idx, processing_result):
        item = self.batch_results[idx]
        item.processing_result = processing_result
        try:
            from meeting_analyzer import StateFileUpdater, format_ordre_del_dia
            note = item.note

            updater = StateFileUpdater()
            updater.update(item.estat_path, processing_result, note['date'])

            date_obj = datetime.strptime(note['date'], '%y%m%d')
            ordre_path = note['path'].parent.parent / 'Ordre del dia propera reunió.md'
            ordre_content = format_ordre_del_dia(processing_result, item.all_topics, date_obj.strftime('%d/%m/%Y'))
            ordre_path.write_text(ordre_content, encoding='utf-8')

            self.obsidian.mark_as_processed(note['path'])
            self._batch_mark_done(idx)
        except Exception as e:
            self._batch_error(idx, str(e))
            return
        self._process_next()

    def _batch_on_summary_finished(self, idx, summary):
        item = self.batch_results[idx]
        item.processing_markdown = summary
        try:
            note = item.note
            if item.processing_type == 'seguiment_puntual':
                title = f"{note['date']} - {note['title']}"
                self.obsidian.append_to_historic(note['path'], title, summary)
            elif item.processing_type == 'proveidors':
                self.obsidian.append_to_provider_note(
                    note['path'], note['date'], note['title'], summary
                )
            self.obsidian.mark_as_processed(note['path'])
            self._batch_mark_done(idx)
        except Exception as e:
            self._batch_error(idx, str(e))
            return
        self._process_next()

    # -- Helpers d'estat de batch --

    def _batch_mark_done(self, idx):
        self.batch_results[idx].status = 'saved'
        self.table_batch.setItem(idx, 2, QTableWidgetItem("Desat ✓"))
        self._batch_done_count += 1
        self.progress_batch.setValue(self._batch_done_count)
        total = len(self.batch_results)
        self.lbl_batch_status.setText(f"Processant {self._batch_done_count}/{total}...")

    def _batch_skip(self, idx, reason):
        self.batch_results[idx].status = 'skipped'
        self.table_batch.setItem(idx, 2, QTableWidgetItem(f"Omesa: {reason}"))
        self._batch_done_count += 1
        self.progress_batch.setValue(self._batch_done_count)
        self._process_next()

    def _batch_error(self, idx, msg):
        self.batch_results[idx].status = 'error'
        self.batch_results[idx].error_msg = msg
        self.table_batch.setItem(idx, 2, QTableWidgetItem("Error"))
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
            self.stack.setCurrentIndex(0)
            self._update_nav()

    def _go_next(self):
        idx = self._current_page()

        if idx == 0:
            rows = self.table_notes.selectionModel().selectedRows()
            if not rows:
                return
            selected_rows = sorted(r.row() for r in rows)
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

    def _extract_subtype_from_note(self, path) -> str:
        content = path.read_text(encoding='utf-8')
        if content.startswith('---'):
            end = content.find('---', 3)
            if end != -1:
                frontmatter = yaml.safe_load(content[3:end])
                if frontmatter:
                    return frontmatter.get('subtype', '') or ''
        return ''

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
