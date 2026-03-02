import shutil
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QPushButton, QTableWidget, QTableWidgetItem, QLabel,
    QProgressBar, QListWidget, QLineEdit, QMessageBox,
    QHeaderView, QFileDialog, QWidget
)
from PySide6.QtCore import Qt

from vocabulary_loader import VocabularyLoader
from transcript_corrector import TranscriptCorrector
from workers import CalendarWorker, CorrectionDetectWorker
from widgets.transcript_editor import TranscriptEditor
from widgets.inline_correction_editor import InlineCorrectionEditor


PROJECT_NOTE_TEMPLATE = """\
## Identificació
Tipus:
BM:
Grup:
Data inici:
Última actualització:

---
## Resum

---
## Objectius

---
## Estat actual

---
## Planificació
Finalització prevista:
Release actual

---
## Accions en curs
| Acció | Responsable | Data prevista |
|------|-------------|--------------|

---
## Cost i inversió

### Cost producte / operació
-

### Inversió R+D
-

---
## Riscos i bloquejos
-

---
## Decisions pendents
-

---
## Context rellevant
"""


class WizardNouProjecte(QDialog):
    def __init__(self, calendar, obsidian, parent=None):
        super().__init__(parent)
        self.calendar = calendar
        self.obsidian = obsidian
        self.setWindowTitle("Crear nou projecte")
        self.setMinimumSize(700, 520)

        self.project_name = ''
        self.reunions: list = []
        self.selected_meeting = None
        self.doc_files: list[str] = []
        self.corrector = None
        self.inline_editor: InlineCorrectionEditor | None = None
        self.raw_transcript = ''

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

        self._build_page0_name()
        self._build_page1_meeting()
        self._build_page2_transcript()
        self._build_page3_docs()
        self._build_page4_correction()
        self._build_page5_result()

        self._update_nav()

    # ── Pàgina 0: Nom del projecte ───────────────────────────────────────────

    def _build_page0_name(self):
        w = QWidget()
        page = QVBoxLayout(w)
        page.addStretch()

        page.addWidget(QLabel("Nom del projecte:"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Ex: HONOADOOR v2")
        self.name_input.textChanged.connect(self._update_nav)
        self.name_input.returnPressed.connect(self._go_next)
        page.addWidget(self.name_input)

        self.name_error = QLabel()
        self.name_error.setStyleSheet("color: red;")
        page.addWidget(self.name_error)
        page.addStretch()

        self.stack.addWidget(w)

    # ── Pàgina 1: Reunió de definició ────────────────────────────────────────

    def _build_page1_meeting(self):
        w = QWidget()
        page = QVBoxLayout(w)

        page.addWidget(QLabel("Reunió de definició del projecte:"))

        self.progress_meetings = QProgressBar()
        self.progress_meetings.setRange(0, 0)
        page.addWidget(self.progress_meetings)

        self.table_meetings = QTableWidget()
        self.table_meetings.setColumnCount(3)
        self.table_meetings.setHorizontalHeaderLabels(["Data", "Títol", "Assistents"])
        self.table_meetings.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_meetings.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table_meetings.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_meetings.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_meetings.doubleClicked.connect(self._go_next)
        page.addWidget(self.table_meetings)

        self.stack.addWidget(w)

    def _load_meetings(self):
        self.progress_meetings.setVisible(True)
        self.table_meetings.setRowCount(0)
        self.worker_cal = CalendarWorker(self.calendar, self)
        self.worker_cal.finished.connect(self._on_meetings_loaded)
        self.worker_cal.error.connect(self._on_meetings_error)
        self.worker_cal.start()

    def _on_meetings_loaded(self, reunions):
        self.progress_meetings.setVisible(False)
        self.reunions = reunions
        self.table_meetings.setRowCount(len(reunions))
        for i, r in enumerate(reunions):
            data = r['start'].strftime('%d/%m/%Y %H:%M')
            noms = ', '.join(a['name'] for a in r['attendees'][:3])
            self.table_meetings.setItem(i, 0, QTableWidgetItem(data))
            self.table_meetings.setItem(i, 1, QTableWidgetItem(r['title']))
            self.table_meetings.setItem(i, 2, QTableWidgetItem(noms))

    def _on_meetings_error(self, msg):
        self.progress_meetings.setVisible(False)
        QMessageBox.critical(self, "Error", f"Error carregant reunions:\n{msg}")

    # ── Pàgina 2: Transcripció ───────────────────────────────────────────────

    def _build_page2_transcript(self):
        w = QWidget()
        page = QVBoxLayout(w)

        page.addWidget(QLabel("Enganxa la transcripció de la reunió de definició:"))
        self.transcript_editor = TranscriptEditor()
        self.transcript_editor.editor.textChanged.connect(self._update_nav)
        page.addWidget(self.transcript_editor)

        self.stack.addWidget(w)

    # ── Pàgina 3: Documentació (opcional) ────────────────────────────────────

    def _build_page3_docs(self):
        w = QWidget()
        page = QVBoxLayout(w)

        page.addWidget(QLabel("Fitxers de definició del projecte (opcional):"))

        btn_row = QHBoxLayout()
        btn_add = QPushButton("Afegir fitxers...")
        btn_add.clicked.connect(self._add_doc_files)
        self.btn_remove_doc = QPushButton("Eliminar seleccionat")
        self.btn_remove_doc.clicked.connect(self._remove_doc_file)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(self.btn_remove_doc)
        btn_row.addStretch()
        page.addLayout(btn_row)

        self.docs_list = QListWidget()
        page.addWidget(self.docs_list)

        skip_lbl = QLabel("Si no tens fitxers ara, pots saltar aquest pas amb \"Endavant\".")
        skip_lbl.setStyleSheet("color: #666; font-style: italic;")
        page.addWidget(skip_lbl)

        self.stack.addWidget(w)

    def _add_doc_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Selecciona fitxers de definició")
        for f in files:
            if f not in self.doc_files:
                self.doc_files.append(f)
                self.docs_list.addItem(Path(f).name)

    def _remove_doc_file(self):
        row = self.docs_list.currentRow()
        if row >= 0:
            self.doc_files.pop(row)
            self.docs_list.takeItem(row)

    # ── Pàgina 4: Correcció de transcripció ──────────────────────────────────

    def _build_page4_correction(self):
        w = QWidget()
        page = QVBoxLayout(w)

        self.label_corrections = QLabel("Analitzant transcripció...")
        page.addWidget(self.label_corrections)

        self.progress_corrections = QProgressBar()
        self.progress_corrections.setRange(0, 0)
        page.addWidget(self.progress_corrections)

        self._corrections_page_layout = page
        self.stack.addWidget(w)

    def _start_correction(self):
        self.label_corrections.setText("Analitzant transcripció...")
        self.progress_corrections.setVisible(True)
        self.btn_next.setEnabled(False)

        if self.inline_editor:
            self.inline_editor.setParent(None)
            self.inline_editor.deleteLater()
            self.inline_editor = None

        vocab_path = self.obsidian.vault / 'Reunions' / 'zConfig' / 'Vocabulari.md'
        vocab = VocabularyLoader(vocab_path).load()
        memorized_path = self.obsidian.vault / 'Reunions' / 'zConfig' / 'Canvis-Memoritzats.md'

        self.raw_transcript = self.transcript_editor.get_text()
        self.corrector = TranscriptCorrector(vocab, memorized_path=memorized_path)

        self.worker_corrections = CorrectionDetectWorker(
            self.corrector, self.raw_transcript, None, self
        )
        self.worker_corrections.finished.connect(self._on_corrections_detected)
        self.worker_corrections.error.connect(self._on_corrections_error)
        self.worker_corrections.start()

    def _on_corrections_detected(self, transcript, corrections):
        self.progress_corrections.setVisible(False)
        self.raw_transcript = transcript

        if corrections:
            self.label_corrections.setText(
                f"{len(corrections)} correccions detectades. Revisa i edita el text lliurement:"
            )
        else:
            self.label_corrections.setText("Cap correcció detectada. Pots editar el text lliurement:")

        self.inline_editor = InlineCorrectionEditor(transcript, corrections)
        self._corrections_page_layout.addWidget(self.inline_editor)

        self.btn_next.setEnabled(True)
        self.btn_next.setText("Crear projecte")

    def _on_corrections_error(self, msg):
        self.progress_corrections.setVisible(False)
        self.label_corrections.setText(f"Error en la correcció: {msg}")
        # Mostrar l'editor igualment amb el text sense correccions
        self.inline_editor = InlineCorrectionEditor(self.raw_transcript, [])
        self._corrections_page_layout.addWidget(self.inline_editor)
        self.btn_next.setEnabled(True)
        self.btn_next.setText("Crear projecte")

    # ── Pàgina 5: Resultat ───────────────────────────────────────────────────

    def _build_page5_result(self):
        w = QWidget()
        page = QVBoxLayout(w)
        page.addStretch()

        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result_label.setStyleSheet("font-size: 13px; line-height: 1.6;")
        page.addWidget(self.result_label)
        page.addStretch()

        self.stack.addWidget(w)

    # ── Navegació ────────────────────────────────────────────────────────────

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
            name = self.name_input.text().strip()
            if not name:
                self.name_error.setText("Cal introduir un nom.")
                return
            clean = name
            for c in '<>:"/\\|?*':
                clean = clean.replace(c, '')
            clean = ' '.join(clean.split()).replace(' ', '_')
            project_dir = self.obsidian.vault / 'Reunions' / 'Projectes' / clean
            if project_dir.exists():
                self.name_error.setText(f'Ja existeix un projecte amb el nom "{clean}".')
                return
            self.name_error.setText('')
            self.project_name = clean
            self._load_meetings()

        elif idx == 1:
            rows = self.table_meetings.selectionModel().selectedRows()
            if not rows:
                return
            self.selected_meeting = self.reunions[rows[0].row()]

        elif idx == 2:
            if not self.transcript_editor.get_text():
                return

        elif idx == 3:
            # Documentació: sempre OK (pas opcional)
            self.stack.setCurrentIndex(4)
            self._update_nav()
            self._start_correction()
            return

        elif idx == 4:
            self._create_project()
            self.stack.setCurrentIndex(5)
            self._update_nav()
            return

        elif idx == 5:
            self.accept()
            return

        self.stack.setCurrentIndex(idx + 1)
        self._update_nav()

    def _update_nav(self):
        idx = self._current_page()

        self.btn_back.setEnabled(0 < idx < 5)
        self.btn_cancel.setEnabled(idx < 5)

        if idx == 0:
            self.btn_next.setText("Endavant")
            self.btn_next.setEnabled(bool(self.name_input.text().strip()))
        elif idx == 2:
            self.btn_next.setText("Endavant")
            self.btn_next.setEnabled(bool(self.transcript_editor.get_text()))
        elif idx == 4:
            self.btn_next.setText("Crear projecte")
            # s'activa des de _on_corrections_detected
        elif idx == 5:
            self.btn_next.setText("Tancar")
            self.btn_next.setEnabled(True)
            self.btn_cancel.setEnabled(False)
        else:
            self.btn_next.setText("Endavant")
            self.btn_next.setEnabled(True)

    # ── Crear el projecte ────────────────────────────────────────────────────

    def _create_project(self):
        name = self.project_name
        project_dir = self.obsidian.vault / 'Reunions' / 'Projectes' / name

        # 1. Nota de reunió amb la transcripció corregida
        corrected = self.inline_editor.get_final_text() if self.inline_editor else self.raw_transcript

        if self.inline_editor and self.corrector:
            for c in self.inline_editor.get_memorize_list():
                self.corrector.save_memorized(c['original'], c['correccio'])

        self.obsidian.create_meeting_note(
            self.selected_meeting, corrected, 'Projectes', name
        )

        # Marcar la reunió com a processada (afegeix '*' al nom del fitxer)
        note_path = self.obsidian._gen_path(self.selected_meeting, 'Projectes', name)
        processed_path = self.obsidian.mark_as_processed(note_path)

        # 2. Fitxers de documentació
        if self.doc_files:
            doc_dir = project_dir / 'Documentació' / 'Definició'
            doc_dir.mkdir(parents=True, exist_ok=True)
            for f in self.doc_files:
                shutil.copy2(f, doc_dir / Path(f).name)

        # 3. Nota del projecte (template)
        project_note = project_dir / f'{name}.md'
        project_note.write_text(PROJECT_NOTE_TEMPLATE, encoding='utf-8')

        # Missatge de resultat
        lines = [
            f"Projecte «{name}» creat correctament!\n",
            f"Reunions/Projectes/{name}/",
            f"  Reunions/{processed_path.name}",
            f"  {name}.md",
        ]
        if self.doc_files:
            lines.append(f"  Documentació/Definició/  ({len(self.doc_files)} fitxer(s))")

        self.result_label.setText('\n'.join(lines))
