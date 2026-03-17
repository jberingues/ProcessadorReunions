from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QPushButton, QListWidget, QListWidgetItem, QLabel,
    QProgressBar, QWidget, QDateEdit, QTextEdit,
    QTreeWidget, QTreeWidgetItem,
)
from PySide6.QtCore import Qt, QDate

from workers import ProjectInitWorker


class WizardNouProjecte(QDialog):
    def __init__(self, calendar, obsidian, parent=None):
        super().__init__(parent)
        self.obsidian = obsidian
        self.setWindowTitle("Inicialitzar projecte existent")
        self.setMinimumSize(700, 520)

        self.corrected_notes: list = []
        self.selected_note = None
        self.doc_files: list[str] = []
        self.selected_project = None
        self.data_inici = ''
        self.worker = None

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

        self._build_page0_meeting()
        self._build_page1_files()
        self._build_page2_project()
        self._build_page3_date()
        self._build_page4_analysis()
        self._build_page5_result()

        self._load_meetings()
        self._update_nav()

    # ── Pàgina 0: Escollir reunió corregida ──────────────────────────────────

    def _build_page0_meeting(self):
        w = QWidget()
        page = QVBoxLayout(w)
        page.addWidget(QLabel("Escull la reunió de definició del projecte (transcripció corregida):"))
        self.meetings_list = QListWidget()
        self.meetings_list.currentRowChanged.connect(self._update_nav)
        self.meetings_list.doubleClicked.connect(self._go_next)
        page.addWidget(self.meetings_list)
        self.stack.addWidget(w)

    def _load_meetings(self):
        self.corrected_notes = self.obsidian.find_corrected_notes()
        self.meetings_list.clear()
        for note in self.corrected_notes:
            date_display = self._fmt_date(note['date'])
            self.meetings_list.addItem(QListWidgetItem(f"{date_display} — {note['title']}"))

    def _fmt_date(self, date_str: str) -> str:
        if len(date_str) == 6:
            try:
                return datetime.strptime(date_str, '%y%m%d').strftime('%d/%m/%Y')
            except ValueError:
                pass
        return date_str

    # ── Pàgina 1: Fitxers de l'Obsidian vault ────────────────────────────────

    def _build_page1_files(self):
        w = QWidget()
        page = QVBoxLayout(w)
        page.addWidget(QLabel(
            "Selecciona els fitxers de definició del projecte (Ctrl+clic per a múltiple selecció):"
        ))

        self.vault_tree = QTreeWidget()
        self.vault_tree.setHeaderLabel("Vault")
        self.vault_tree.setSelectionMode(QTreeWidget.SelectionMode.MultiSelection)
        page.addWidget(self.vault_tree)

        skip_lbl = QLabel("Pots continuar sense seleccionar cap fitxer.")
        skip_lbl.setStyleSheet("color: #666; font-style: italic;")
        page.addWidget(skip_lbl)
        self.stack.addWidget(w)

    def _populate_vault_tree(self):
        self.vault_tree.clear()

        def add_dir(parent, dir_path):
            try:
                entries = sorted(dir_path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
            except PermissionError:
                return
            for entry in entries:
                if entry.name.startswith('.'):
                    continue
                if entry.is_dir():
                    folder = QTreeWidgetItem(parent, [entry.name])
                    folder.setFlags(folder.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                    add_dir(folder, entry)
                elif entry.suffix.lower() in ('.md', '.txt', '.pdf', '.docx'):
                    item = QTreeWidgetItem(parent, [entry.name])
                    item.setData(0, Qt.ItemDataRole.UserRole, str(entry))

        root = QTreeWidgetItem(self.vault_tree, [self.obsidian.vault.name])
        root.setFlags(root.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        add_dir(root, self.obsidian.vault)
        self.vault_tree.expandToDepth(1)

    # ── Pàgina 2: Escollir projecte ───────────────────────────────────────────

    def _build_page2_project(self):
        w = QWidget()
        page = QVBoxLayout(w)
        page.addWidget(QLabel("Escull el projecte:"))
        self.projects_list = QListWidget()
        self.projects_list.currentRowChanged.connect(self._update_nav)
        self.projects_list.doubleClicked.connect(self._go_next)
        page.addWidget(self.projects_list)
        self.stack.addWidget(w)

    def _load_projects(self):
        projects = self.obsidian.find_subfolders('Projectes')
        self.projects_list.clear()
        for p in projects:
            self.projects_list.addItem(p)

    # ── Pàgina 3: Data d'inici ────────────────────────────────────────────────

    def _build_page3_date(self):
        w = QWidget()
        page = QVBoxLayout(w)
        page.addStretch()
        page.addWidget(QLabel("Data d'inici del projecte:"))
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd/MM/yyyy")
        self.date_edit.setDate(QDate.currentDate())
        page.addWidget(self.date_edit)
        page.addStretch()
        self.stack.addWidget(w)

    def _prefill_date(self):
        if self.selected_note and len(self.selected_note['date']) == 6:
            try:
                dt = datetime.strptime(self.selected_note['date'], '%y%m%d')
                self.date_edit.setDate(QDate(dt.year, dt.month, dt.day))
            except ValueError:
                pass

    # ── Pàgina 4: Anàlisi LLM ─────────────────────────────────────────────────

    def _build_page4_analysis(self):
        w = QWidget()
        page = QVBoxLayout(w)
        self.analysis_label = QLabel("Analitzant documentació...")
        page.addWidget(self.analysis_label)
        self.progress_analysis = QProgressBar()
        self.progress_analysis.setRange(0, 0)
        page.addWidget(self.progress_analysis)
        self.resum_edit = QTextEdit()
        self.resum_edit.setPlaceholderText("El resum del projecte apareixerà aquí per editar...")
        self.resum_edit.setVisible(False)
        page.addWidget(self.resum_edit)
        self.stack.addWidget(w)

    def _start_analysis(self):
        self.analysis_label.setText("Analitzant documentació...")
        self.progress_analysis.setVisible(True)
        self.resum_edit.setVisible(False)
        self.btn_next.setEnabled(False)

        transcript = self.obsidian.read_transcript(self.selected_note['path'])
        file_contents = []
        for f in self.doc_files:
            try:
                file_contents.append(Path(f).read_text(encoding='utf-8', errors='ignore'))
            except Exception:
                pass

        self.worker = ProjectInitWorker(transcript, file_contents, self.selected_project, self)
        self.worker.finished.connect(self._on_analysis_done)
        self.worker.error.connect(self._on_analysis_error)
        self.worker.start()

    def _on_analysis_done(self, summary: str):
        self.progress_analysis.setVisible(False)
        self.analysis_label.setText("Resum generat. Pots editar-lo abans de desar:")
        self.resum_edit.setPlainText(summary)
        self.resum_edit.setVisible(True)
        self.btn_next.setEnabled(True)
        self.btn_next.setText("Desar projecte")

    def _on_analysis_error(self, msg: str):
        self.progress_analysis.setVisible(False)
        self.analysis_label.setText(f"Error en l'anàlisi: {msg}\nPots escriure el resum manualment:")
        self.resum_edit.setVisible(True)
        self.btn_next.setEnabled(True)
        self.btn_next.setText("Desar projecte")

    # ── Pàgina 5: Resultat ────────────────────────────────────────────────────

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

    # ── Navegació ─────────────────────────────────────────────────────────────

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
            row = self.meetings_list.currentRow()
            if row < 0:
                return
            self.selected_note = self.corrected_notes[row]

        elif idx == 1:
            self.doc_files = [
                item.data(0, Qt.ItemDataRole.UserRole)
                for item in self.vault_tree.selectedItems()
                if item.data(0, Qt.ItemDataRole.UserRole)
            ]

        elif idx == 2:
            row = self.projects_list.currentRow()
            if row < 0:
                return
            self.selected_project = self.projects_list.item(row).text()
            self._prefill_date()

        elif idx == 3:
            self.data_inici = self.date_edit.date().toString("dd/MM/yyyy")
            self.stack.setCurrentIndex(4)
            self._update_nav()
            self._start_analysis()
            return

        elif idx == 4:
            self._save_project()
            self.stack.setCurrentIndex(5)
            self._update_nav()
            return

        elif idx == 5:
            self.accept()
            return

        self.stack.setCurrentIndex(idx + 1)
        if idx == 0:
            self._populate_vault_tree()
        elif idx == 1:
            self._load_projects()
        self._update_nav()

    def _update_nav(self):
        idx = self._current_page()

        self.btn_back.setEnabled(0 < idx < 4)
        self.btn_cancel.setEnabled(idx < 5)

        if idx == 0:
            self.btn_next.setText("Endavant")
            self.btn_next.setEnabled(self.meetings_list.currentRow() >= 0)
        elif idx == 2:
            self.btn_next.setText("Endavant")
            self.btn_next.setEnabled(self.projects_list.currentRow() >= 0)
        elif idx == 4:
            self.btn_next.setText("Desar projecte")
            # Habilitat/deshabilitat des de _on_analysis_done/_on_analysis_error
        elif idx == 5:
            self.btn_next.setText("Tancar")
            self.btn_next.setEnabled(True)
            self.btn_cancel.setEnabled(False)
        else:
            self.btn_next.setText("Endavant")
            self.btn_next.setEnabled(True)

    # ── Desar al projecte ─────────────────────────────────────────────────────

    def _save_project(self):
        note_path = (
            self.obsidian.vault / 'Reunions' / 'Projectes'
            / self.selected_project / f'{self.selected_project}.md'
        )
        if not note_path.exists():
            self.result_label.setText(
                f"Error: no s'ha trobat el fitxer del projecte:\n{note_path}"
            )
            return

        resum = self.resum_edit.toPlainText().strip()
        self.obsidian.update_project_fields(note_path, self.data_inici, resum)
        self.obsidian.mark_as_processed(self.selected_note['path'])

        self.result_label.setText(
            f"Projecte «{self.selected_project}» actualitzat!\n\n"
            f"Data inici: {self.data_inici}\n\n"
            f"Fitxer actualitzat:\n"
            f"Reunions/Projectes/{self.selected_project}/{self.selected_project}.md"
        )
