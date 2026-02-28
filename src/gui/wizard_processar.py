import re
import yaml
from datetime import datetime
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QPushButton, QTableWidget, QTableWidgetItem, QLabel,
    QProgressBar, QPlainTextEdit, QMessageBox, QHeaderView
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from vocabulary_loader import VocabularyLoader
from transcript_corrector import TranscriptCorrector
from workers import (
    CorrectionDetectWorker, DailyProcessorWorker,
    MeetingAnalyzerWorker, SummaryWorker
)
from widgets.correction_checklist import CorrectionChecklist


class WizardProcessar(QDialog):
    def __init__(self, calendar, obsidian, parent=None):
        super().__init__(parent)
        self.calendar = calendar
        self.obsidian = obsidian
        self.setWindowTitle("Processar reunions")
        self.setMinimumSize(750, 550)

        self.notes = []
        self.selected_note = None
        self.corrector = None
        self.corrected_transcript = None
        self.processing_result = None
        self.processing_markdown = None

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
        self._build_page1_corrections()
        self._build_page2_processing()
        self._build_page3_result()

        self._update_nav()
        self._load_notes()

    # -- Pàgina 0: Seleccionar nota --

    def _build_page0_notes(self):
        from PySide6.QtWidgets import QWidget
        page = QVBoxLayout()
        w = QWidget()
        w.setLayout(page)

        page.addWidget(QLabel("Reunions per processar:"))

        self.table_notes = QTableWidget()
        self.table_notes.setColumnCount(2)
        self.table_notes.setHorizontalHeaderLabels(["Data", "Títol"])
        self.table_notes.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_notes.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table_notes.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_notes.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_notes.doubleClicked.connect(self._go_next)
        page.addWidget(self.table_notes)

        self.stack.addWidget(w)

    def _load_notes(self):
        self.notes = self.obsidian.find_unprocessed_notes()
        self.table_notes.setRowCount(len(self.notes))
        for i, n in enumerate(self.notes):
            self.table_notes.setItem(i, 0, QTableWidgetItem(n['date']))
            self.table_notes.setItem(i, 1, QTableWidgetItem(n['title']))

    # -- Pàgina 1: Correccions --

    def _build_page1_corrections(self):
        from PySide6.QtWidgets import QWidget
        page = QVBoxLayout()
        w = QWidget()
        w.setLayout(page)

        self.label_corrections = QLabel("Analitzant transcripció...")
        page.addWidget(self.label_corrections)

        self.progress_corrections = QProgressBar()
        self.progress_corrections.setRange(0, 0)
        page.addWidget(self.progress_corrections)

        # Placeholder per al checklist (es reemplaça dinàmicament)
        self.checklist_container = QVBoxLayout()
        page.addLayout(self.checklist_container)

        self.correction_checklist = None

        self.stack.addWidget(w)

    def _start_correction(self):
        self.label_corrections.setText("Analitzant transcripció...")
        self.progress_corrections.setVisible(True)
        self.btn_next.setEnabled(False)

        # Netejar checklist anterior
        if self.correction_checklist:
            self.correction_checklist.setParent(None)
            self.correction_checklist.deleteLater()
            self.correction_checklist = None

        note = self.selected_note
        vocab_path = self.obsidian.vault / 'Reunions' / 'zConfig' / 'Vocabulari.md'
        vocab = VocabularyLoader(vocab_path).load()
        memorized_path = self.obsidian.vault / 'Reunions' / 'zConfig' / 'Canvis-Memoritzats.md'

        # Buscar transcripció de referència
        reference_transcript = None
        processed_siblings = sorted(
            [p for p in note['path'].parent.glob('*.md') if '*' in p.stem],
            key=lambda p: p.stem[:6],
            reverse=True
        )
        if processed_siblings:
            reference_transcript = self.obsidian.read_transcript(processed_siblings[0])

        transcript = self.obsidian.read_transcript(note['path'])
        self.corrector = TranscriptCorrector(vocab, memorized_path=memorized_path)

        self.worker_corrections = CorrectionDetectWorker(
            self.corrector, transcript, reference_transcript, self
        )
        self.worker_corrections.finished.connect(self._on_corrections_detected)
        self.worker_corrections.error.connect(self._on_corrections_error)
        self.worker_corrections.start()

    def _on_corrections_detected(self, transcript, corrections):
        self.progress_corrections.setVisible(False)
        self.corrected_transcript = transcript

        if not corrections:
            self.label_corrections.setText("Cap error detectat.")
        else:
            self.label_corrections.setText(f"{len(corrections)} possibles correccions:")
            self.correction_checklist = CorrectionChecklist(corrections)
            self.checklist_container.addWidget(self.correction_checklist)

        self.btn_next.setEnabled(True)

    def _on_corrections_error(self, msg):
        self.progress_corrections.setVisible(False)
        self.label_corrections.setText(f"Error: {msg}")
        self.btn_next.setEnabled(True)

    def _apply_corrections(self):
        """Aplica les correccions aprovades i memoritza les marcades."""
        if self.correction_checklist:
            approved = self.correction_checklist.get_approved_corrections()
            for c in approved:
                if c.get("memorize"):
                    self.corrector.save_memorized(c["original"], c["correccio"])
            if approved:
                self.corrected_transcript = self.corrector.apply(
                    self.corrected_transcript, approved
                )

        # Actualitzar la nota amb la transcripció corregida
        self.obsidian.update_transcript(self.selected_note['path'], self.corrected_transcript)

    # -- Pàgina 2: Processament específic --

    def _build_page2_processing(self):
        from PySide6.QtWidgets import QWidget
        page = QVBoxLayout()
        w = QWidget()
        w.setLayout(page)

        self.label_processing = QLabel("Processant...")
        page.addWidget(self.label_processing)

        self.progress_processing = QProgressBar()
        self.progress_processing.setRange(0, 0)
        page.addWidget(self.progress_processing)

        self.result_text = QPlainTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setFont(QFont("Courier", 11))
        page.addWidget(self.result_text)

        self.stack.addWidget(w)

    def _start_processing(self):
        self.label_processing.setText("Processant...")
        self.progress_processing.setVisible(True)
        self.result_text.clear()
        self.btn_next.setEnabled(False)
        self.btn_next.setText("Confirmar")

        note = self.selected_note
        path_parts = note['path'].parts

        if 'Sincronització' in path_parts:
            self._start_sincronitzacio()
        elif 'Seguiment' in path_parts:
            subtype = self._extract_subtype_from_note(note['path'])
            if subtype == 'puntual':
                self._start_seguiment_puntual()
            else:
                self._start_seguiment()
        elif 'Proveïdors' in path_parts:
            self._start_proveidors()
        else:
            self.progress_processing.setVisible(False)
            self.label_processing.setText("Tipus de reunió no reconegut. No es processarà.")
            self.btn_next.setEnabled(True)
            self.btn_next.setText("Endavant")
            self._processing_type = None

    def _start_sincronitzacio(self):
        self._processing_type = 'sincronitzacio'
        self.label_processing.setText("Analitzant Daily Scrum...")

        note = self.selected_note
        vocab_path = self.obsidian.vault / 'Reunions' / 'zConfig' / 'Vocabulari.md'
        vocab = VocabularyLoader(vocab_path).load()

        attendees = self._extract_attendees_from_note(note['path'])
        speaker_emails = self._extract_speaker_emails_from_note(note['path'])

        daily_transcript = self.corrected_transcript
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
        self.worker_processing.finished.connect(self._on_daily_finished)
        self.worker_processing.error.connect(self._on_processing_error)
        self.worker_processing.start()

    def _on_daily_finished(self, result, md_output):
        self.progress_processing.setVisible(False)
        self.processing_result = result
        self.processing_markdown = md_output
        self.label_processing.setText("Resultat de l'anàlisi:")
        self.result_text.setPlainText(md_output)
        self.btn_next.setEnabled(True)

    def _start_seguiment(self):
        self._processing_type = 'seguiment'
        self.label_processing.setText("Analitzant temes de seguiment...")

        note = self.selected_note
        title = note['title']
        estat_nom = title[len('Seguiment '):] if title.startswith('Seguiment ') else 'Estat actual'
        estat_path = note['path'].parent.parent / f'{estat_nom}.md'
        if not estat_path.exists():
            estat_path.write_text("", encoding='utf-8')

        from meeting_analyzer import MeetingAnalyzer, parse_active_topics
        self._estat_path = estat_path
        self._estat_nom = estat_nom
        topics = parse_active_topics(estat_path)

        if not topics:
            self.progress_processing.setVisible(False)
            self.label_processing.setText("No hi ha temes oberts a l'estat actual.")
            self.btn_next.setEnabled(True)
            self.btn_next.setText("Endavant")
            return

        self._all_topics = topics
        analyzer = MeetingAnalyzer()

        self.worker_processing = MeetingAnalyzerWorker(
            analyzer, topics, self.corrected_transcript, self
        )
        self.worker_processing.finished.connect(self._on_seguiment_finished)
        self.worker_processing.error.connect(self._on_processing_error)
        self.worker_processing.start()

    def _on_seguiment_finished(self, result):
        self.progress_processing.setVisible(False)
        self.processing_result = result
        self.label_processing.setText("Resultat de l'anàlisi:")

        lines = []
        if result.updated_topics:
            lines.append("Temes tractats:\n")
            for t in result.updated_topics:
                lines.append(f"  {t.topic_name}")
                lines.append(f"  {t.summary}\n")
        if result.new_other_topics:
            lines.append("Nous temes:\n")
            for t in result.new_other_topics:
                lines.append(f"  - {t}")
        if not result.updated_topics and not result.new_other_topics:
            lines.append("Cap tema tractat.")

        self.result_text.setPlainText('\n'.join(lines))
        self.btn_next.setEnabled(True)

    def _start_seguiment_puntual(self):
        self._processing_type = 'seguiment_puntual'
        self.label_processing.setText("Generant resum...")

        self.worker_processing = SummaryWorker(self.corrected_transcript, self)
        self.worker_processing.finished.connect(self._on_summary_finished)
        self.worker_processing.error.connect(self._on_processing_error)
        self.worker_processing.start()

    def _start_proveidors(self):
        self._processing_type = 'proveidors'
        self.label_processing.setText("Generant resum...")

        self.worker_processing = SummaryWorker(self.corrected_transcript, self)
        self.worker_processing.finished.connect(self._on_summary_finished)
        self.worker_processing.error.connect(self._on_processing_error)
        self.worker_processing.start()

    def _on_summary_finished(self, summary):
        self.progress_processing.setVisible(False)
        self.processing_markdown = summary
        self.label_processing.setText("Resum:")
        self.result_text.setPlainText(summary)
        self.btn_next.setEnabled(True)

    def _on_processing_error(self, msg):
        self.progress_processing.setVisible(False)
        self.label_processing.setText(f"Error: {msg}")
        self.btn_next.setEnabled(True)
        self.btn_next.setText("Endavant")

    def _confirm_processing(self):
        """Escriu els resultats als fitxers corresponents."""
        note = self.selected_note
        ptype = getattr(self, '_processing_type', None)

        if ptype == 'sincronitzacio':
            self._confirm_daily()
        elif ptype == 'seguiment':
            self._confirm_seguiment()
        elif ptype == 'seguiment_puntual':
            self._confirm_seguiment_puntual()
        elif ptype == 'proveidors':
            self._confirm_proveidors()

    def _confirm_daily(self):
        note = self.selected_note
        date_obj = datetime.strptime(note['date'], '%y%m%d')
        year = date_obj.strftime('%Y')
        resum_path = note['path'].parent.parent / f'Resum reunions {year}.md'

        if not resum_path.exists():
            resum_path.parent.mkdir(parents=True, exist_ok=True)
            header = f"---\ntype: resum-reunions\nyear: {year}\n---\n\n"
            resum_path.write_text(header + self.processing_markdown + '\n', encoding='utf-8')
        else:
            existing = resum_path.read_text(encoding='utf-8')
            resum_path.write_text(existing + '\n---\n\n' + self.processing_markdown + '\n', encoding='utf-8')

        self._mark_processed()

    def _confirm_seguiment(self):
        from meeting_analyzer import StateFileUpdater, format_ordre_del_dia
        note = self.selected_note
        result = self.processing_result

        updater = StateFileUpdater()
        updater.update(self._estat_path, result, note['date'])

        date_obj = datetime.strptime(note['date'], '%y%m%d')
        ordre_path = note['path'].parent.parent / 'Ordre del dia propera reunió.md'
        ordre_content = format_ordre_del_dia(result, self._all_topics, date_obj.strftime('%d/%m/%Y'))
        ordre_path.write_text(ordre_content, encoding='utf-8')

        self._mark_processed()

    def _confirm_seguiment_puntual(self):
        note = self.selected_note
        title = f"{note['date']} - {note['title']}"
        self.obsidian.append_to_historic(note['path'], title, self.processing_markdown)
        self._mark_processed()

    def _confirm_proveidors(self):
        note = self.selected_note
        self.obsidian.append_to_provider_note(
            note['path'], note['date'], note['title'], self.processing_markdown
        )
        self._mark_processed()

    def _mark_processed(self):
        new_path = self.obsidian.mark_as_processed(self.selected_note['path'])
        self._result_filename = new_path.name

    # -- Pàgina 3: Resultat --

    def _build_page3_result(self):
        from PySide6.QtWidgets import QWidget
        page = QVBoxLayout()
        w = QWidget()
        w.setLayout(page)

        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet("font-size: 14px;")
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        page.addWidget(self.result_label)
        page.addStretch()

        self.stack.addWidget(w)

    # -- Navegació --

    def _current_page(self):
        return self.stack.currentIndex()

    def _go_back(self):
        idx = self._current_page()
        if idx > 0:
            self.stack.setCurrentIndex(idx - 1)
            self._update_nav()

    def _go_next(self):
        idx = self._current_page()

        if idx == 0:
            rows = self.table_notes.selectionModel().selectedRows()
            if not rows:
                return
            row = rows[0].row()
            self.selected_note = self.notes[row]
            self.stack.setCurrentIndex(1)
            self._update_nav()
            self._start_correction()
            return

        elif idx == 1:
            self._apply_corrections()
            self.stack.setCurrentIndex(2)
            self._update_nav()
            self._start_processing()
            return

        elif idx == 2:
            ptype = getattr(self, '_processing_type', None)
            if ptype is None:
                # No processing needed, skip to result
                self._result_filename = self.selected_note['path'].name
                self.obsidian.mark_as_processed(self.selected_note['path'])
            else:
                self._confirm_processing()

            self.result_label.setText(
                f"Nota processada correctament!\n\n"
                f"{getattr(self, '_result_filename', '')}"
            )
            self.stack.setCurrentIndex(3)
            self._update_nav()
            return

        elif idx == 3:
            # "Processar una altra" o tancar
            ret = QMessageBox.question(
                self, "Continuar?",
                "Vols processar una altra reunió?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if ret == QMessageBox.StandardButton.Yes:
                self._reset()
            else:
                self.accept()
            return

    def _update_nav(self):
        idx = self._current_page()
        self.btn_back.setEnabled(idx > 0 and idx < 3)

        if idx == 2:
            self.btn_next.setText("Confirmar")
        elif idx == 3:
            self.btn_next.setText("Tancar")
            self.btn_back.setEnabled(False)
        else:
            self.btn_next.setText("Endavant")

    def _reset(self):
        self.selected_note = None
        self.corrector = None
        self.corrected_transcript = None
        self.processing_result = None
        self.processing_markdown = None
        self._processing_type = None

        if self.correction_checklist:
            self.correction_checklist.setParent(None)
            self.correction_checklist.deleteLater()
            self.correction_checklist = None

        self.result_text.clear()
        self.table_notes.clearSelection()
        self.stack.setCurrentIndex(0)
        self._update_nav()
        self._load_notes()

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
