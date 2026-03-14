from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QPushButton, QTableWidget, QTableWidgetItem, QLabel,
    QProgressBar, QMessageBox, QHeaderView
)
from PySide6.QtCore import Qt
from vocabulary_loader import VocabularyLoader
from transcript_corrector import TranscriptCorrector
from workers import CorrectionDetectWorker
from widgets.inline_correction_editor import InlineCorrectionEditor


class WizardCorreccio(QDialog):
    def __init__(self, obsidian, parent=None):
        super().__init__(parent)
        self.obsidian = obsidian
        self.setWindowTitle("Correcció transcripcions")
        self.setMinimumSize(750, 550)

        self.notes = []
        self.selected_note = None
        self.corrector = None

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
        self._build_page1_corrections()
        self._build_page2_result()

        self._update_nav()
        self._load_notes()

    # -- Pàgina 0: Seleccionar nota --

    def _build_page0_notes(self):
        from PySide6.QtWidgets import QWidget
        page = QVBoxLayout()
        w = QWidget()
        w.setLayout(page)

        page.addWidget(QLabel("Reunions per corregir:"))

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
        self.notes = self.obsidian.find_uncorrected_notes()
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

        self._corrections_page_layout = page
        self.inline_editor: InlineCorrectionEditor | None = None

        self.stack.addWidget(w)

    def _start_correction(self):
        self.label_corrections.setText("Analitzant transcripció...")
        self.progress_corrections.setVisible(True)
        self.btn_next.setEnabled(False)

        if self.inline_editor:
            self.inline_editor.setParent(None)
            self.inline_editor.deleteLater()
            self.inline_editor = None

        note = self.selected_note
        vocab_path = self.obsidian.vault / 'Reunions' / 'zConfig' / 'Vocabulari.md'
        vocab = VocabularyLoader(vocab_path).load()
        memorized_path = self.obsidian.vault / 'Reunions' / 'zConfig' / 'Canvis-Memoritzats.md'

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

        # Memòria semàntica (sèries de reunions: Seguiment, Proveïdors, etc.)
        semantic_context = None
        meeting_dir = note['path'].parent.parent  # .../Seguiment_Pau_Coll/
        if meeting_dir.name != 'Reunions':
            from semantic_memory_builder import SemanticMemoryBuilder
            from semantic_context_retriever import SemanticContextRetriever
            SemanticMemoryBuilder().build_if_stale(meeting_dir)
            semantic_context = SemanticContextRetriever().load(meeting_dir)

        self.worker_corrections = CorrectionDetectWorker(
            self.corrector, transcript, reference_transcript, semantic_context, self
        )
        self.worker_corrections.finished.connect(self._on_corrections_detected)
        self.worker_corrections.error.connect(self._on_corrections_error)
        self.worker_corrections.start()

    def _on_corrections_detected(self, transcript, corrections):
        self.progress_corrections.setVisible(False)

        if corrections:
            self.label_corrections.setText(
                f"{len(corrections)} correccions detectades. "
                "Revisa i edita el text lliurement:"
            )
        else:
            self.label_corrections.setText("Cap correcció detectada. Pots editar el text lliurement:")

        self.inline_editor = InlineCorrectionEditor(transcript, corrections)
        self._corrections_page_layout.addWidget(self.inline_editor)
        self.btn_next.setEnabled(True)

    def _on_corrections_error(self, msg):
        self.progress_corrections.setVisible(False)
        self.label_corrections.setText(f"Error: {msg}")
        self.btn_next.setEnabled(True)

    def _apply_corrections(self):
        if self.inline_editor:
            corrected_transcript = self.inline_editor.get_final_text()
            for c in self.inline_editor.get_memorize_list():
                self.corrector.save_memorized(c['original'], c['correccio'])

            self.obsidian.update_transcript(self.selected_note['path'], corrected_transcript)

        new_path = self.obsidian.mark_as_corrected(self.selected_note['path'])
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
            self._start_correction()
            return

        elif idx == 1:
            self._apply_corrections()
            self.result_label.setText(
                f"Transcripció corregida i guardada!\n\n{getattr(self, '_result_filename', '')}"
            )
            self.stack.setCurrentIndex(2)
            self._update_nav()
            return

        elif idx == 2:
            ret = QMessageBox.question(
                self, "Continuar?",
                "Vols corregir una altra reunió?",
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

        if idx == 2:
            self.btn_next.setText("Tancar")
        else:
            self.btn_next.setText("Endavant")

    def _reset(self):
        self.selected_note = None
        self.corrector = None

        if self.inline_editor:
            self.inline_editor.setParent(None)
            self.inline_editor.deleteLater()
            self.inline_editor = None

        self.table_notes.clearSelection()
        self.stack.setCurrentIndex(0)
        self._update_nav()
        self._load_notes()
