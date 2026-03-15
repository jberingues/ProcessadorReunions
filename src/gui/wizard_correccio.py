from dataclasses import dataclass, field
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QPushButton, QTableWidget, QTableWidgetItem, QLabel,
    QProgressBar, QMessageBox, QHeaderView, QWidget, QAbstractItemView
)
from PySide6.QtCore import Qt
from vocabulary_loader import VocabularyLoader
from transcript_corrector import TranscriptCorrector
from workers import BatchCorrectionDetectWorker
from widgets.inline_correction_editor import InlineCorrectionEditor


@dataclass
class BatchNoteResult:
    note: dict
    status: str = 'pending'  # pending | detecting | detected | reviewed | error
    transcript: str | None = None
    corrections: list = field(default_factory=list)
    error_msg: str | None = None
    corrector: TranscriptCorrector | None = None


class WizardCorreccio(QDialog):
    def __init__(self, obsidian, parent=None):
        super().__init__(parent)
        self.obsidian = obsidian
        self.setWindowTitle("Correcció transcripcions")
        self.setMinimumSize(800, 600)

        self.notes = []
        self.batch_results: dict[int, BatchNoteResult] = {}
        self.batch_worker: BatchCorrectionDetectWorker | None = None
        self.reviewing_idx: int | None = None
        self.inline_editor: InlineCorrectionEditor | None = None

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

        self._build_page0_selection()
        self._build_page1_progress()
        self._build_page2_review()
        self._build_page3_result()

        self._update_nav()
        self._load_notes()

    # ── Pàgina 0: Selecció múltiple ──────────────────────────────────────────

    def _build_page0_selection(self):
        page = QVBoxLayout()
        w = QWidget()
        w.setLayout(page)

        header = QHBoxLayout()
        header.addWidget(QLabel("Reunions per corregir:"))
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
        self.notes = self.obsidian.find_uncorrected_notes()
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

    # ── Pàgina 1: Progrés batch ─────────────────────────────────────────────

    def _build_page1_progress(self):
        page = QVBoxLayout()
        w = QWidget()
        w.setLayout(page)

        self.lbl_batch_status = QLabel("Preparant...")
        page.addWidget(self.lbl_batch_status)

        self.progress_batch = QProgressBar()
        page.addWidget(self.progress_batch)

        self.table_batch = QTableWidget()
        self.table_batch.setColumnCount(4)
        self.table_batch.setHorizontalHeaderLabels(["Data", "Títol", "Estat", "Correccions"])
        self.table_batch.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_batch.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table_batch.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_batch.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_batch.doubleClicked.connect(self._on_batch_row_double_click)
        self.table_batch.itemSelectionChanged.connect(self._update_review_button)
        page.addWidget(self.table_batch)

        btn_row = QHBoxLayout()
        self.btn_review = QPushButton("Revisar seleccionada")
        self.btn_review.setEnabled(False)
        self.btn_review.clicked.connect(self._on_review_clicked)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_review)
        page.addLayout(btn_row)

        self.stack.addWidget(w)

    def _prepare_and_start_batch(self):
        selected_rows = sorted(r.row() for r in self.table_notes.selectionModel().selectedRows())
        selected_notes = [self.notes[r] for r in selected_rows]

        vocab_path = self.obsidian.vault / 'Reunions' / 'zConfig' / 'Vocabulari.md'
        vocab = VocabularyLoader(vocab_path).load()
        memorized_path = self.obsidian.vault / 'Reunions' / 'zConfig' / 'Canvis-Memoritzats.md'

        self.batch_results.clear()
        tasks = []

        self.table_batch.setRowCount(len(selected_notes))
        self.progress_batch.setRange(0, len(selected_notes))
        self.progress_batch.setValue(0)

        for idx, note in enumerate(selected_notes):
            corrector = TranscriptCorrector(vocab, memorized_path=memorized_path)
            transcript = self.obsidian.read_transcript(note['path'])

            reference_transcript = None
            processed_siblings = sorted(
                [p for p in note['path'].parent.glob('*.md') if '*' in p.stem],
                key=lambda p: p.stem[:6],
                reverse=True
            )
            if processed_siblings:
                reference_transcript = self.obsidian.read_transcript(processed_siblings[0])

            semantic_context = None
            meeting_dir = note['path'].parent.parent
            if meeting_dir.name != 'Reunions':
                from semantic_memory_builder import SemanticMemoryBuilder
                from semantic_context_retriever import SemanticContextRetriever
                SemanticMemoryBuilder().build_if_stale(meeting_dir)
                semantic_context = SemanticContextRetriever().load(meeting_dir)

            result = BatchNoteResult(
                note=note, status='pending',
                transcript=transcript, corrector=corrector
            )
            self.batch_results[idx] = result

            tasks.append({
                'index': idx,
                'corrector': corrector,
                'transcript': transcript,
                'reference_transcript': reference_transcript,
                'semantic_context': semantic_context,
            })

            self.table_batch.setItem(idx, 0, QTableWidgetItem(note['date']))
            self.table_batch.setItem(idx, 1, QTableWidgetItem(note['title']))
            self.table_batch.setItem(idx, 2, QTableWidgetItem("Pendent"))
            self.table_batch.setItem(idx, 3, QTableWidgetItem("—"))

        self.lbl_batch_status.setText(f"Processant 0/{len(selected_notes)}...")

        self.batch_worker = BatchCorrectionDetectWorker(tasks, self)
        self.batch_worker.note_started.connect(self._on_note_started)
        self.batch_worker.note_finished.connect(self._on_note_finished)
        self.batch_worker.note_error.connect(self._on_note_error)
        self.batch_worker.all_finished.connect(self._on_batch_finished)
        self.batch_worker.start()

    def _on_note_started(self, idx):
        self.batch_results[idx].status = 'detecting'
        self.table_batch.setItem(idx, 2, QTableWidgetItem("Processant..."))

    def _on_note_finished(self, idx, transcript, corrections):
        result = self.batch_results[idx]
        result.status = 'detected'
        result.transcript = transcript
        result.corrections = corrections

        n_corr = len(corrections)
        self.table_batch.setItem(idx, 2, QTableWidgetItem("Detectat"))
        self.table_batch.setItem(idx, 3, QTableWidgetItem(str(n_corr)))

        done = sum(1 for r in self.batch_results.values() if r.status in ('detected', 'reviewed', 'error'))
        self.progress_batch.setValue(done)
        self.lbl_batch_status.setText(f"Processant {done}/{len(self.batch_results)}...")

        self._update_review_button()

    def _on_note_error(self, idx, msg):
        result = self.batch_results[idx]
        result.status = 'error'
        result.error_msg = msg
        self.table_batch.setItem(idx, 2, QTableWidgetItem("Error"))
        self.table_batch.setItem(idx, 3, QTableWidgetItem("—"))

        done = sum(1 for r in self.batch_results.values() if r.status in ('detected', 'reviewed', 'error'))
        self.progress_batch.setValue(done)
        self.lbl_batch_status.setText(f"Processant {done}/{len(self.batch_results)}...")

        self._update_review_button()

    def _on_batch_finished(self):
        done = sum(1 for r in self.batch_results.values() if r.status in ('detected', 'reviewed', 'error'))
        errors = sum(1 for r in self.batch_results.values() if r.status == 'error')
        self.lbl_batch_status.setText(f"Completat: {done} processades" + (f" ({errors} errors)" if errors else ""))
        self.btn_next.setEnabled(True)

    def _update_review_button(self):
        rows = self.table_batch.selectionModel().selectedRows()
        if rows:
            idx = rows[0].row()
            result = self.batch_results.get(idx)
            self.btn_review.setEnabled(result is not None and result.status == 'detected')
        else:
            self.btn_review.setEnabled(False)

    def _on_batch_row_double_click(self, index):
        idx = index.row()
        result = self.batch_results.get(idx)
        if result and result.status == 'detected':
            self._open_review(idx)

    def _on_review_clicked(self):
        rows = self.table_batch.selectionModel().selectedRows()
        if not rows:
            return
        idx = rows[0].row()
        result = self.batch_results.get(idx)
        if result and result.status == 'detected':
            self._open_review(idx)

    # ── Pàgina 2: Revisió individual ─────────────────────────────────────────

    def _build_page2_review(self):
        page = QVBoxLayout()
        w = QWidget()
        w.setLayout(page)

        self.lbl_review_title = QLabel()
        self.lbl_review_title.setStyleSheet("font-size: 14px; font-weight: bold;")
        page.addWidget(self.lbl_review_title)

        self._review_page_layout = page
        self._review_page_widget = w

        btn_row = QHBoxLayout()
        self.btn_save_review = QPushButton("Desar correccions")
        self.btn_save_review.setStyleSheet(
            "background:#4CAF50; color:white; font-weight:bold; padding:6px 16px;"
        )
        self.btn_save_review.clicked.connect(self._apply_review)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_save_review)
        page.addLayout(btn_row)

        self.stack.addWidget(w)

    def _open_review(self, idx):
        result = self.batch_results[idx]
        self.reviewing_idx = idx

        if self.inline_editor:
            self.inline_editor.setParent(None)
            self.inline_editor.deleteLater()
            self.inline_editor = None

        self.lbl_review_title.setText(f"{result.note['date']} — {result.note['title']}")
        self.inline_editor = InlineCorrectionEditor(result.transcript, result.corrections)
        self._review_page_layout.insertWidget(1, self.inline_editor)

        self.stack.setCurrentIndex(2)
        self._update_nav()

    def _apply_review(self):
        result = self.batch_results[self.reviewing_idx]

        corrected = self.inline_editor.get_final_text()
        for c in self.inline_editor.get_memorize_list():
            result.corrector.save_memorized(c['original'], c['correccio'])

        self.obsidian.update_transcript(result.note['path'], corrected)
        self.obsidian.mark_as_corrected(result.note['path'])

        result.status = 'reviewed'
        self.table_batch.setItem(self.reviewing_idx, 2, QTableWidgetItem("Revisat ✓"))

        self.stack.setCurrentIndex(1)
        self._update_nav()

    # ── Pàgina 3: Resultat ───────────────────────────────────────────────────

    def _build_page3_result(self):
        page = QVBoxLayout()
        w = QWidget()
        w.setLayout(page)

        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet("font-size: 14px;")
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        page.addWidget(self.result_label)

        self.btn_back_to_review = QPushButton("Tornar a revisar")
        self.btn_back_to_review.clicked.connect(lambda: self._go_to_page(1))
        page.addWidget(self.btn_back_to_review, alignment=Qt.AlignmentFlag.AlignCenter)

        page.addStretch()
        self.stack.addWidget(w)

    def _show_result_summary(self):
        reviewed = sum(1 for r in self.batch_results.values() if r.status == 'reviewed')
        detected = sum(1 for r in self.batch_results.values() if r.status == 'detected')
        errors = sum(1 for r in self.batch_results.values() if r.status == 'error')

        lines = [f"Corregides: {reviewed}"]
        if detected:
            lines.append(f"Pendents de revisió: {detected}")
        if errors:
            lines.append(f"Errors: {errors}")

        self.result_label.setText("\n".join(lines))
        self.btn_back_to_review.setVisible(detected > 0)

    # ── Navegació ────────────────────────────────────────────────────────────

    def _current_page(self):
        return self.stack.currentIndex()

    def _go_to_page(self, page):
        self.stack.setCurrentIndex(page)
        self._update_nav()

    def _go_back(self):
        idx = self._current_page()
        if idx == 1:
            # Abortar batch si en curs
            if self.batch_worker and self.batch_worker.isRunning():
                ret = QMessageBox.question(
                    self, "Abortar?",
                    "El batch està en curs. Vols abortar-lo?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if ret != QMessageBox.StandardButton.Yes:
                    return
                self.batch_worker.abort()
                self.batch_worker.wait(3000)
            self.stack.setCurrentIndex(0)
        elif idx == 2:
            self.stack.setCurrentIndex(1)
        elif idx == 3:
            self.stack.setCurrentIndex(1)
        self._update_nav()

    def _go_next(self):
        idx = self._current_page()

        if idx == 0:
            rows = self.table_notes.selectionModel().selectedRows()
            if not rows:
                return
            self.stack.setCurrentIndex(1)
            self._update_nav()
            self._prepare_and_start_batch()
            return

        elif idx == 1:
            self._show_result_summary()
            self.stack.setCurrentIndex(3)
            self._update_nav()
            return

        elif idx == 3:
            self.accept()
            return

    def _update_nav(self):
        idx = self._current_page()
        self.btn_back.setEnabled(idx in (1, 2, 3))

        if idx == 0:
            self.btn_next.setText("Endavant")
            self.btn_next.setEnabled(True)
        elif idx == 1:
            self.btn_next.setText("Endavant")
            # Només habilitat si el batch ha acabat
            batch_done = self.batch_worker is None or not self.batch_worker.isRunning()
            self.btn_next.setEnabled(batch_done)
            self._update_review_button()
        elif idx == 2:
            self.btn_next.setEnabled(False)
            self.btn_next.setText("Endavant")
        elif idx == 3:
            self.btn_next.setText("Tancar")
            self.btn_next.setEnabled(True)

    # ── Tancament ────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        if self._confirm_close():
            event.accept()
        else:
            event.ignore()

    def reject(self):
        if self._confirm_close():
            super().reject()

    def _confirm_close(self):
        # Abortar worker si en curs
        if self.batch_worker and self.batch_worker.isRunning():
            self.batch_worker.abort()
            self.batch_worker.wait(3000)

        # Avisar si hi ha notes detectades però no revisades
        detected = sum(1 for r in self.batch_results.values() if r.status == 'detected')
        if detected > 0:
            ret = QMessageBox.question(
                self, "Notes sense revisar",
                f"Hi ha {detected} notes processades sense revisar. Vols tancar igualment?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            return ret == QMessageBox.StandardButton.Yes
        return True
