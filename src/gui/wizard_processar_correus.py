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
from PySide6.QtGui import QFontDatabase
from vocabulary_loader import VocabularyLoader
from workers import MeetingAnalyzerWorker, SummaryWorker


class WizardProcessarCorreus(QDialog):
    def __init__(self, calendar, obsidian, parent=None):
        super().__init__(parent)
        self.calendar = calendar
        self.obsidian = obsidian
        self.setWindowTitle("Processar correus")
        self.setMinimumSize(750, 550)

        self.notes = []
        self.selected_note = None
        self._project_dir = None
        self.email_body = None
        self.processing_result = None
        self.processing_markdown = None

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
        self._build_page1_processing()
        self._build_page2_result()

        self._update_nav()
        self._load_notes()

    # -- Pàgina 0: Seleccionar nota de correu --

    def _build_page0_notes(self):
        from PySide6.QtWidgets import QWidget
        page = QVBoxLayout()
        w = QWidget()
        w.setLayout(page)

        page.addWidget(QLabel("Correus per processar:"))

        self.table_notes = QTableWidget()
        self.table_notes.setColumnCount(2)
        self.table_notes.setHorizontalHeaderLabels(["Data", "Assumpte"])
        self.table_notes.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_notes.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table_notes.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_notes.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_notes.doubleClicked.connect(self._go_next)
        page.addWidget(self.table_notes)

        self.stack.addWidget(w)

    def _load_notes(self):
        self.notes = self.obsidian.find_unprocessed_email_notes()
        self.table_notes.setRowCount(len(self.notes))
        for i, n in enumerate(self.notes):
            self.table_notes.setItem(i, 0, QTableWidgetItem(n['date']))
            self.table_notes.setItem(i, 1, QTableWidgetItem(n['title']))

    # -- Pàgina 1: Processament --

    def _build_page1_processing(self):
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
        self.result_text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        page.addWidget(self.result_text)

        self.stack.addWidget(w)

    def _start_processing(self):
        self.label_processing.setText("Processant...")
        self.progress_processing.setVisible(True)
        self.result_text.clear()
        self.btn_next.setEnabled(False)
        self.btn_next.setText("Confirmar")

        note = self.selected_note
        self.email_body = self.obsidian.read_email_body(note['path'])
        self._project_dir = note['path'].parent
        path_parts = note['path'].parts

        if 'Seguiment' in path_parts:
            subtype = self._extract_subtype_from_note(note['path'])
            if subtype == 'puntual':
                self._start_seguiment_puntual()
            else:
                self._start_seguiment()
        elif 'Proveïdors' in path_parts:
            self._start_proveidors()
        else:
            self.progress_processing.setVisible(False)
            self.label_processing.setText("Tipus de carpeta no reconegut. No es processarà.")
            self.btn_next.setEnabled(True)
            self.btn_next.setText("Endavant")
            self._processing_type = None

    def _start_seguiment(self):
        self._processing_type = 'seguiment'
        self.label_processing.setText("Analitzant temes de seguiment...")

        note = self.selected_note
        title = note['title']
        estat_nom = title[len('Seguiment '):] if title.startswith('Seguiment ') else 'Estat actual'
        estat_path = self._project_dir / f'{estat_nom}.md'
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
            analyzer, topics, self.email_body, self
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

        self.worker_processing = SummaryWorker(self.email_body, self)
        self.worker_processing.finished.connect(self._on_summary_finished)
        self.worker_processing.error.connect(self._on_processing_error)
        self.worker_processing.start()

    def _start_proveidors(self):
        self._processing_type = 'proveidors'
        self.label_processing.setText("Generant resum...")

        self.worker_processing = SummaryWorker(self.email_body, self)
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
        ptype = getattr(self, '_processing_type', None)
        if ptype == 'seguiment':
            self._confirm_seguiment()
        elif ptype == 'seguiment_puntual':
            self._confirm_seguiment_puntual()
        elif ptype == 'proveidors':
            self._confirm_proveidors()

    def _confirm_seguiment(self):
        from meeting_analyzer import StateFileUpdater, format_ordre_del_dia
        note = self.selected_note
        result = self.processing_result

        updater = StateFileUpdater()
        updater.update(self._estat_path, result, note['date'])

        date_obj = datetime.strptime(note['date'], '%y%m%d')
        ordre_path = self._project_dir / 'Ordre del dia propera reunió.md'
        ordre_content = format_ordre_del_dia(result, self._all_topics, date_obj.strftime('%d/%m/%Y'))
        ordre_path.write_text(ordre_content, encoding='utf-8')

        self._mark_processed()

    def _confirm_seguiment_puntual(self):
        note = self.selected_note
        title = f"{note['date']} - {note['title']}"
        self.obsidian.append_to_historic(
            note['path'], title, self.processing_markdown,
            project_dir=self._project_dir
        )
        self._mark_processed()

    def _confirm_proveidors(self):
        note = self.selected_note
        project_dir = self._project_dir
        if project_dir.name == 'Correus':
            project_dir = project_dir.parent
        self.obsidian.append_email_to_provider_note(
            note['path'], note['date'], note['title'], self.processing_markdown,
            project_dir=project_dir
        )
        self._mark_processed()

    def _mark_processed(self):
        new_path = self.obsidian.mark_as_processed(self.selected_note['path'])
        self._result_filename = new_path.name

    # -- Pàgina 2: Resultat --

    def _build_page2_result(self):
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
            self._start_processing()
            return

        elif idx == 1:
            ptype = getattr(self, '_processing_type', None)
            if ptype is None:
                self._result_filename = self.selected_note['path'].name
                self.obsidian.mark_as_processed(self.selected_note['path'])
            else:
                self._confirm_processing()

            self.result_label.setText(
                f"Correu processat correctament!\n\n"
                f"{getattr(self, '_result_filename', '')}"
            )
            self.stack.setCurrentIndex(2)
            self._update_nav()
            return

        elif idx == 2:
            ret = QMessageBox.question(
                self, "Continuar?",
                "Vols processar un altre correu?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if ret == QMessageBox.StandardButton.Yes:
                self._reset()
            else:
                self.accept()
            return

    def _update_nav(self):
        idx = self._current_page()
        self.btn_back.setEnabled(idx == 1)

        if idx == 1:
            self.btn_next.setText("Confirmar")
        elif idx == 2:
            self.btn_next.setText("Tancar")
            self.btn_back.setEnabled(False)
        else:
            self.btn_next.setText("Endavant")

    def _reset(self):
        self.selected_note = None
        self._project_dir = None
        self.email_body = None
        self.processing_result = None
        self.processing_markdown = None
        self._processing_type = None

        self.result_text.clear()
        self.table_notes.clearSelection()
        self.stack.setCurrentIndex(0)
        self._update_nav()
        self._load_notes()

    # -- Utilitats --

    def _extract_subtype_from_note(self, path) -> str:
        content = path.read_text(encoding='utf-8')
        if content.startswith('---'):
            end = content.find('---', 3)
            if end != -1:
                frontmatter = yaml.safe_load(content[3:end])
                if frontmatter:
                    return frontmatter.get('subtype', '') or ''
        return ''
