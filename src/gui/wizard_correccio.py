from dataclasses import dataclass, field
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QPushButton, QTableWidget, QTableWidgetItem, QLabel,
    QProgressBar, QMessageBox, QHeaderView, QWidget, QAbstractItemView,
    QCheckBox
)
from PySide6.QtCore import Qt
from vocabulary_loader import VocabularyLoader
from transcript_corrector import TranscriptCorrector
from workers import (
    BatchCorrectionDetectWorker, BatchCorrectionPrepareWorker, detach_worker
)
from widgets.inline_correction_editor import InlineCorrectionEditor


@dataclass
class BatchNoteResult:
    note: dict
    status: str = 'pending'  # preparing | pending | detecting | detected | reviewed | error
    transcript: str | None = None
    corrections: list = field(default_factory=list)
    error_msg: str | None = None
    corrector: TranscriptCorrector | None = None
    meeting_dir: object = None


class WizardCorreccio(QDialog):
    def __init__(self, obsidian, parent=None, preselected_paths=None):
        super().__init__(parent)
        self.obsidian = obsidian
        self.setWindowTitle("Correcció transcripcions")
        self.setMinimumSize(800, 600)

        # Si s'obre des del tauler, es filtra a les notes triades i es
        # preseleccionen totes (l'usuari només ajusta els checkboxes i executa).
        self.preselected_paths = preselected_paths
        self.notes = []
        self.batch_results: dict[int, BatchNoteResult] = {}
        self.batch_worker: BatchCorrectionDetectWorker | None = None
        self.prepare_worker: BatchCorrectionPrepareWorker | None = None
        self._prepared_tasks: list = []
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

        # Opció per saltar la fase de revisió manual: aplica totes les
        # correccions detectades directament i marca les notes com a corregides.
        self.chk_skip_review = QCheckBox(
            "Aplicar les correccions automàticament (sense revisió manual)"
        )
        self.chk_skip_review.setChecked(False)
        self.chk_skip_review.setToolTip(
            "Si està marcat, després de detectar les correccions s'aplicaran "
            "totes directament sense que les hagis de revisar una per una. "
            "Recomanat només quan confies en la qualitat del detector."
        )
        page.addWidget(self.chk_skip_review)

        # Opció per desar còpies temporals (auto + manual) per comparar el
        # benefici real de la revisió manual respecte de l'aplicació automàtica.
        self.chk_save_comparison = QCheckBox(
            "Guardar còpia automàtica per comparar amb la versió manual"
        )
        self.chk_save_comparison.setChecked(False)
        self.chk_save_comparison.setToolTip(
            "Desa tres còpies de cada nota a /tmp/comparacio_correccions/: "
            "_original.md (transcripció abans de res), _auto.md (totes les "
            "correccions auto-aplicades) i _manual.md (la teva revisió). "
            "Pots fer 'diff' entre les tres per veure què aporta cada pas."
        )
        page.addWidget(self.chk_save_comparison)

        self.stack.addWidget(w)

    def _load_notes(self):
        self.notes = self.obsidian.find_uncorrected_notes()
        if self.preselected_paths is not None:
            self.notes = [n for n in self.notes if n['path'] in self.preselected_paths]
        self.table_notes.setRowCount(len(self.notes))
        for i, n in enumerate(self.notes):
            self.table_notes.setItem(i, 0, QTableWidgetItem(n['date']))
            self.table_notes.setItem(i, 1, QTableWidgetItem(n['title']))
        if self.preselected_paths is not None:
            self.table_notes.selectAll()

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

    def _prepare_and_start_batch(self, selected_rows: list[int]):
        selected_notes = [self.notes[r] for r in selected_rows]

        # Guardem l'estat del checkbox: l'usuari podria canviar-lo durant el
        # batch i no volem comportament inconsistent entre notes.
        self.skip_review = self.chk_skip_review.isChecked()
        self.save_comparison = self.chk_save_comparison.isChecked()

        self.batch_results.clear()
        self._prepared_tasks = []

        self.table_batch.setRowCount(len(selected_notes))
        self.progress_batch.setRange(0, len(selected_notes))
        self.progress_batch.setValue(0)
        for idx, note in enumerate(selected_notes):
            self.table_batch.setItem(idx, 0, QTableWidgetItem(note['date']))
            self.table_batch.setItem(idx, 1, QTableWidgetItem(note['title']))
            self.table_batch.setItem(idx, 2, QTableWidgetItem("Preparant..."))
            self.table_batch.setItem(idx, 3, QTableWidgetItem("—"))
            self.batch_results[idx] = BatchNoteResult(note=note, status='preparing')

        self.lbl_batch_status.setText(
            f"Preparant 0/{len(selected_notes)} (llegint el vault)..."
        )

        # La preparació (vocabulari, transcripcions, resums anuals de
        # referència, memòria semàntica) és tota I/O del vault i va en un
        # worker: amb el vault a Google Drive una lectura pot trigar minuts i
        # abans congelava la finestra sencera (cap repintat, cap avís).
        vocab_path = self.obsidian.vault / 'Reunions' / 'zConfig' / 'Vocabulari.md'
        self.prepare_worker = BatchCorrectionPrepareWorker(
            self.obsidian, selected_notes, vocab_path, self
        )
        self.prepare_worker.note_prepared.connect(self._on_note_prepared)
        self.prepare_worker.note_error.connect(self._on_note_error)
        self.prepare_worker.progress.connect(self._on_prepare_progress)
        self.prepare_worker.failed.connect(self._on_prepare_failed)
        self.prepare_worker.all_finished.connect(self._on_prepare_finished)
        self.prepare_worker.start()
        self._update_nav()

    def _on_note_prepared(self, idx, task):
        result = self.batch_results[idx]
        result.status = 'pending'
        result.transcript = task['transcript']
        result.corrector = task['corrector']
        result.meeting_dir = task['meeting_dir']
        self.table_batch.setItem(idx, 2, QTableWidgetItem("Pendent"))

        # Còpia 'original' per comparació: la transcripció tal com era abans de
        # qualsevol modificació (aliases memoritzats, correccions LLM, revisió
        # manual). Va a /tmp (disc local), no al vault.
        if self.save_comparison:
            try:
                self._save_comparison_copy(result.note, task['transcript'], 'original')
            except Exception as e:
                print(f"[WizardCorreccio] Error desant còpia original: {e}")

        self._prepared_tasks.append(task)

    def _on_prepare_progress(self, done, total):
        self.progress_batch.setValue(done)
        self.lbl_batch_status.setText(f"Preparant {done}/{total} (llegint el vault)...")

    def _on_prepare_failed(self, msg):
        """Error global de preparació (vocabulari il·legible): no hi ha batch."""
        self.prepare_worker = None
        self.lbl_batch_status.setText(f"Error llegint el vocabulari: {msg}")
        for idx, result in self.batch_results.items():
            result.status = 'error'
            result.error_msg = msg
            self.table_batch.setItem(idx, 2, QTableWidgetItem("Error"))
            self.table_batch.setItem(idx, 3, QTableWidgetItem(msg[:40]))
        self._update_nav()

    def _on_prepare_finished(self):
        self.prepare_worker = None
        if not self._prepared_tasks:
            self.lbl_batch_status.setText(
                "Cap nota preparada (vegeu els errors a la taula)."
            )
            self._update_nav()
            return

        # La barra passa a comptar el batch de detecció: les notes que han
        # fallat preparant-se ja compten com a fetes.
        errors = sum(1 for r in self.batch_results.values() if r.status == 'error')
        self.progress_batch.setValue(errors)
        self.lbl_batch_status.setText(f"Processant 0/{len(self.batch_results)}...")

        self.batch_worker = BatchCorrectionDetectWorker(self._prepared_tasks, self)
        self.batch_worker.note_started.connect(self._on_note_started)
        self.batch_worker.note_finished.connect(self._on_note_finished)
        self.batch_worker.note_error.connect(self._on_note_error)
        self.batch_worker.all_finished.connect(self._on_batch_finished)
        self.batch_worker.start()
        self._update_nav()

    def _on_note_started(self, idx):
        self.batch_results[idx].status = 'detecting'
        self.table_batch.setItem(idx, 2, QTableWidgetItem("Processant..."))

    def _on_note_finished(self, idx, transcript, corrections):
        result = self.batch_results[idx]
        result.transcript = transcript
        result.corrections = corrections

        if not corrections:
            try:
                self.obsidian.update_transcript(result.note['path'], transcript)
                self.obsidian.mark_as_corrected(result.note['path'])
                result.status = 'reviewed'
                self.table_batch.setItem(idx, 2, QTableWidgetItem("Revisat ✓ (0 errors)"))
                self.table_batch.setItem(idx, 3, QTableWidgetItem("0"))
            except Exception as e:
                result.status = 'error'
                result.error_msg = str(e)
                self.table_batch.setItem(idx, 2, QTableWidgetItem("Error"))
                self.table_batch.setItem(idx, 3, QTableWidgetItem(str(e)[:40]))
        elif getattr(self, 'skip_review', False):
            # Mode automàtic: aplica totes les correccions sense revisió.
            # No es memoritza res (cap scope) — només es modifica el text.
            try:
                corrected = result.corrector.apply(transcript, corrections)
                self.obsidian.update_transcript(result.note['path'], corrected)
                self.obsidian.mark_as_corrected(result.note['path'])
                result.status = 'reviewed'
                n = len(corrections)
                self.table_batch.setItem(
                    idx, 2, QTableWidgetItem(f"Auto-aplicat ✓ ({n} canvis)")
                )
                self.table_batch.setItem(idx, 3, QTableWidgetItem(str(n)))
            except Exception as e:
                result.status = 'error'
                result.error_msg = str(e)
                self.table_batch.setItem(idx, 2, QTableWidgetItem("Error"))
                self.table_batch.setItem(idx, 3, QTableWidgetItem(str(e)[:40]))
        else:
            result.status = 'detected'
            self.table_batch.setItem(idx, 2, QTableWidgetItem("Detectat"))
            self.table_batch.setItem(idx, 3, QTableWidgetItem(str(len(corrections))))

            # Còpia per comparació: aplica totes les correccions com si fos
            # mode auto i desa-ho a un fitxer temporal (no toca la nota real).
            if getattr(self, 'save_comparison', False):
                try:
                    auto_corrected = result.corrector.apply(transcript, corrections)
                    self._save_comparison_copy(result.note, auto_corrected, 'auto')
                except Exception as e:
                    print(f"[WizardCorreccio] Error desant còpia auto: {e}")

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
        msg = f"Completat: {done} processades" + (f" ({errors} errors)" if errors else "")
        if getattr(self, 'save_comparison', False):
            msg += " · Còpies original/auto a /tmp/comparacio_correccions/"
        self.lbl_batch_status.setText(msg)
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
        threshold = result.corrector.threshold_auto if result.corrector else 1.1
        self.inline_editor = InlineCorrectionEditor(
            result.transcript, result.corrections, threshold_auto=threshold
        )
        self._review_page_layout.insertWidget(1, self.inline_editor)

        self.stack.setCurrentIndex(2)
        self._update_nav()

    def _apply_review(self):
        result = self.batch_results[self.reviewing_idx]

        corrected = self.inline_editor.get_final_text()

        # Còpia per comparació amb la versió auto (desada a _on_note_finished)
        if getattr(self, 'save_comparison', False):
            try:
                self._save_comparison_copy(result.note, corrected, 'manual')
            except Exception as e:
                print(f"[WizardCorreccio] Error desant còpia manual: {e}")

        # Memoritzacions locals (semantic_memory.json d'aquesta sèrie)
        series_list = self.inline_editor.get_memorize_series()
        if result.meeting_dir and series_list:
            self._save_to_semantic_memory(result.meeting_dir, series_list)

        # Memoritzacions globals (alias al Vocabulari.md)
        global_list = self.inline_editor.get_memorize_global()
        if global_list:
            self._save_to_global_vocabulary(global_list)

        # Paraules validades com a correctes (termes principals al Vocabulari.md)
        correct_words = self.inline_editor.get_correct_words()
        if correct_words:
            self._save_correct_terms_to_vocabulary(correct_words)

        self.obsidian.update_transcript(result.note['path'], corrected)
        self.obsidian.mark_as_corrected(result.note['path'])

        result.status = 'reviewed'
        self.table_batch.setItem(self.reviewing_idx, 2, QTableWidgetItem("Revisat ✓"))

        self.stack.setCurrentIndex(1)
        self._update_nav()

    def _save_to_global_vocabulary(self, global_list):
        """Afegeix aliases al Vocabulari.md unificat via VocabularyLoader.add_alias()."""
        vocab_path = self.obsidian.vault / 'Reunions' / 'zConfig' / 'Vocabulari.md'
        loader = VocabularyLoader(vocab_path)
        for c in global_list:
            loader.add_alias(c['original'], c['correccio'])

    def _save_correct_terms_to_vocabulary(self, words):
        """Afegeix paraules validades com a termes principals al Vocabulari.md."""
        vocab_path = self.obsidian.vault / 'Reunions' / 'zConfig' / 'Vocabulari.md'
        loader = VocabularyLoader(vocab_path)
        for w in words:
            loader.add_term(w)

    def _save_comparison_copy(self, note, text, kind):
        """Desa una còpia temporal del transcript per comparar auto vs manual.

        kind: 'auto' (totes les correccions aplicades) o 'manual' (revisió usuari).
        Path: /tmp/comparacio_correccions/<data>_<titol>_<kind>.md
        """
        from pathlib import Path
        out_dir = Path('/tmp/comparacio_correccions')
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_title = note['title'].replace('/', '_').replace(' ', '_')
        out_path = out_dir / f"{note['date']}_{safe_title}_{kind}.md"
        out_path.write_text(text, encoding='utf-8')

    def _save_to_semantic_memory(self, meeting_dir, mem_list):
        import json
        json_path = meeting_dir / 'semantic_memory.json'
        if not json_path.exists():
            return
        data = json.loads(json_path.read_text(encoding='utf-8'))
        aliases = data.get('aliases', {})
        technical_terms = data.get('technical_terms', [])

        # Memoritzar: crear alias "original → correccio" i afegir correccio a technical_terms
        for c in mem_list:
            aliases[c['original']] = c['correccio']
            if not any(t.lower() == c['correccio'].lower() for t in technical_terms):
                technical_terms.append(c['correccio'])

        data['aliases'] = aliases
        data['technical_terms'] = technical_terms
        json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    # ── Navegació ────────────────────────────────────────────────────────────

    def _current_page(self):
        return self.stack.currentIndex()

    def _go_to_page(self, page):
        self.stack.setCurrentIndex(page)
        self._update_nav()

    def _go_back(self):
        idx = self._current_page()
        if idx == 1:
            # Abortar la feina en curs (preparació o batch). Cal desvincular el
            # worker, no només abortar-lo: si torna tard, escriuria resultats
            # dins d'un batch_results que la selecció nova ja ha reiniciat.
            preparing = self.prepare_worker is not None and self.prepare_worker.isRunning()
            running = self.batch_worker is not None and self.batch_worker.isRunning()
            if preparing or running:
                ret = QMessageBox.question(
                    self, "Abortar?",
                    ("La preparació està en curs. Vols abortar-la?" if preparing
                     else "El batch està en curs. Vols abortar-lo?"),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if ret != QMessageBox.StandardButton.Yes:
                    return
            if preparing:
                self._release_worker(self.prepare_worker, (
                    self.prepare_worker.note_prepared,
                    self.prepare_worker.note_error,
                    self.prepare_worker.progress,
                    self.prepare_worker.failed,
                    self.prepare_worker.all_finished,
                ))
                self.prepare_worker = None
            if running:
                self._release_worker(self.batch_worker, (
                    self.batch_worker.note_started,
                    self.batch_worker.note_finished,
                    self.batch_worker.note_error,
                    self.batch_worker.all_finished,
                ))
                self.batch_worker = None
            self.stack.setCurrentIndex(0)
        elif idx == 2:
            self.stack.setCurrentIndex(1)
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
            return

    def _update_nav(self):
        idx = self._current_page()
        self.btn_back.setEnabled(idx in (1, 2))

        if idx == 0:
            self.btn_next.setText("Endavant")
            self.btn_next.setEnabled(True)
        elif idx == 1:
            preparing = self.prepare_worker is not None and self.prepare_worker.isRunning()
            batch_done = not preparing and (
                self.batch_worker is None or not self.batch_worker.isRunning()
            )
            self.btn_next.setText("Tancar" if batch_done else "Endavant")
            self.btn_next.setEnabled(batch_done)
            self._update_review_button()
        elif idx == 2:
            self.btn_next.setEnabled(False)
            self.btn_next.setText("Endavant")

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
        # Preguntar ABANS d'abortar: si l'usuari respon "No", el batch ha de
        # continuar intacte (abans s'abortava primer i un "No" deixava el
        # diàleg obert amb el batch mort en silenci).
        preparing = self.prepare_worker is not None and self.prepare_worker.isRunning()
        running = self.batch_worker is not None and self.batch_worker.isRunning()
        detected = sum(1 for r in self.batch_results.values() if r.status == 'detected')
        if preparing or running or detected:
            parts = []
            if preparing:
                parts.append("S'està preparant el batch (s'aturarà).")
            if running:
                parts.append("El batch està en curs (s'aturarà).")
            if detected:
                parts.append(f"Hi ha {detected} notes processades sense revisar.")
            ret = QMessageBox.question(
                self, "Tancar?",
                " ".join(parts) + " Vols tancar igualment?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if ret != QMessageBox.StandardButton.Yes:
                return False
        if preparing:
            self._release_worker(self.prepare_worker, (
                self.prepare_worker.note_prepared,
                self.prepare_worker.note_error,
                self.prepare_worker.progress,
                self.prepare_worker.failed,
                self.prepare_worker.all_finished,
            ))
            self.prepare_worker = None
        if running:
            self._release_worker(self.batch_worker, (
                self.batch_worker.note_started,
                self.batch_worker.note_finished,
                self.batch_worker.note_error,
                self.batch_worker.all_finished,
            ))
            self.batch_worker = None
        return True

    def _release_worker(self, worker, signals, timeout=3000):
        """Atura un worker i, si no acaba a temps, el desvincula.

        L'abort es comprova entre notes, però la feina en curs pot trigar molt
        més (una crida LLM, o una lectura del vault penjada a Google Drive):
        desconnectem els senyals (el resultat tardà no ha d'escriure res) i
        desvinculem el worker perquè destruir el diàleg no avorti l'app."""
        worker.abort()
        if worker.wait(timeout):
            return
        for sig in signals:
            try:
                sig.disconnect()
            except (RuntimeError, TypeError):
                pass
        detach_worker(worker)
