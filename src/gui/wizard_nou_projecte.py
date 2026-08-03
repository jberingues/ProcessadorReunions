from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QPushButton, QListWidget, QLabel,
    QProgressBar, QWidget, QTextEdit,
    QTreeWidget, QTreeWidgetItem, QSplitter,
)
from PySide6.QtCore import Qt
from window_drag import install_window_drag

from workers import ProjectInitWorker
from project_definition_extractor import ProjectSource
from project_models import format_markdown


class WizardNouProjecte(QDialog):
    def __init__(self, calendar, obsidian, parent=None):
        super().__init__(parent)
        self.obsidian = obsidian
        self.setWindowTitle("Definir projecte")
        self.setMinimumSize(800, 600)
        install_window_drag(self)

        self.selected_project = None
        self.sources: list[ProjectSource] = []
        self.result_definition = None
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

        self._build_page0_project()
        self._build_page1_sources()
        self._build_page2_analysis()
        self._build_page3_result()

        self._load_projects()
        self._update_nav()

    # ── Pàgina 0: Escollir projecte ──────────────────────────────────────────

    def _build_page0_project(self):
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

    # ── Pàgina 1: Seleccionar fonts ──────────────────────────────────────────

    def _build_page1_sources(self):
        w = QWidget()
        page = QVBoxLayout(w)
        page.addWidget(QLabel(
            "Selecciona les fonts per definir el projecte (reunions, correus, fitxers).\n"
            "Ctrl+clic per a selecció múltiple."
        ))

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Reunions list
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Reunions:"))
        self.meetings_tree = QTreeWidget()
        self.meetings_tree.setHeaderLabel("Reunions del projecte")
        self.meetings_tree.setSelectionMode(QTreeWidget.SelectionMode.MultiSelection)
        left_layout.addWidget(self.meetings_tree)
        splitter.addWidget(left)

        # Vault files tree
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("Fitxers del vault:"))
        self.vault_tree = QTreeWidget()
        self.vault_tree.setHeaderLabel("Vault")
        self.vault_tree.setSelectionMode(QTreeWidget.SelectionMode.MultiSelection)
        right_layout.addWidget(self.vault_tree)
        splitter.addWidget(right)

        page.addWidget(splitter)
        self.stack.addWidget(w)

    def _populate_sources(self):
        project_dir = self.obsidian.vault / 'Reunions' / 'Projectes' / self.selected_project

        # Meetings
        self.meetings_tree.clear()
        meetings_dir = project_dir / 'Reunions'
        if meetings_dir.exists():
            for f in sorted(meetings_dir.iterdir(), key=lambda p: p.name, reverse=True):
                if f.suffix == '.md':
                    item = QTreeWidgetItem(self.meetings_tree, [f.name])
                    item.setData(0, Qt.ItemDataRole.UserRole, str(f))

        # Vault tree (project subfolder: Correus, Documentació, Fitxers)
        self.vault_tree.clear()
        for sub_name in ('Correus', 'Documentació', 'Fitxers'):
            sub_dir = project_dir / sub_name
            if sub_dir.exists():
                root = QTreeWidgetItem(self.vault_tree, [sub_name])
                root.setFlags(root.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self._add_dir(root, sub_dir)
        self.vault_tree.expandAll()

    def _add_dir(self, parent, dir_path):
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
                self._add_dir(folder, entry)
            elif entry.suffix.lower() in ('.md', '.txt', '.pdf', '.docx'):
                item = QTreeWidgetItem(parent, [entry.name])
                item.setData(0, Qt.ItemDataRole.UserRole, str(entry))

    # ── Pàgina 2: Anàlisi LLM ────────────────────────────────────────────────

    def _build_page2_analysis(self):
        w = QWidget()
        page = QVBoxLayout(w)
        self.analysis_label = QLabel("Analitzant fonts del projecte...")
        page.addWidget(self.analysis_label)
        self.progress_analysis = QProgressBar()
        self.progress_analysis.setRange(0, 0)
        page.addWidget(self.progress_analysis)
        self.markdown_edit = QTextEdit()
        self.markdown_edit.setPlaceholderText("La definició del projecte apareixerà aquí per editar...")
        self.markdown_edit.setVisible(False)
        page.addWidget(self.markdown_edit)
        self.stack.addWidget(w)

    def _collect_sources(self) -> list[ProjectSource]:
        """Build ProjectSource list from selected items in both trees."""
        sources = []

        # Selected meetings
        for item in self.meetings_tree.selectedItems():
            path_str = item.data(0, Qt.ItemDataRole.UserRole)
            if path_str:
                path = Path(path_str)
                content = self.obsidian.read_transcript(path)
                if content:
                    sources.append(ProjectSource(
                        source_type="meeting",
                        source_name=path.name,
                        content=content,
                    ))

        # Selected vault files
        for item in self.vault_tree.selectedItems():
            path_str = item.data(0, Qt.ItemDataRole.UserRole)
            if path_str:
                path = Path(path_str)
                source_type = self._guess_source_type(path)
                content = self._read_file(path)
                if content:
                    sources.append(ProjectSource(
                        source_type=source_type,
                        source_name=path.name,
                        content=content,
                    ))

        return sources

    def _guess_source_type(self, path: Path) -> str:
        """Guess source type from the file location."""
        parts = [p.lower() for p in path.parts]
        if 'correus' in parts:
            return 'email'
        return 'document'

    def _read_file(self, path: Path) -> str:
        """Read file content as text. Supports .md, .txt, .pdf, .docx."""
        suffix = path.suffix.lower()
        try:
            if suffix in ('.md', '.txt'):
                return path.read_text(encoding='utf-8', errors='ignore')
            elif suffix == '.pdf':
                return self._read_pdf(path)
            elif suffix == '.docx':
                return self._read_docx(path)
        except Exception:
            return ''
        return ''

    @staticmethod
    def _read_pdf(path: Path) -> str:
        try:
            import logging
            import pdfplumber
            logging.getLogger("pdfminer").setLevel(logging.ERROR)
            texts = []
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        texts.append(text)
            return '\n\n'.join(texts)
        except ImportError:
            return path.read_text(encoding='utf-8', errors='ignore')

    @staticmethod
    def _read_docx(path: Path) -> str:
        try:
            from docx import Document
            doc = Document(path)
            return '\n'.join(p.text for p in doc.paragraphs if p.text.strip())
        except ImportError:
            return path.read_text(encoding='utf-8', errors='ignore')

    def _start_analysis(self):
        self.analysis_label.setText("Analitzant fonts del projecte...")
        self.progress_analysis.setVisible(True)
        self.markdown_edit.setVisible(False)
        self.btn_next.setEnabled(False)

        self.sources = self._collect_sources()

        if not self.sources:
            self._on_analysis_error("No s'han seleccionat fonts amb contingut.")
            return

        self.worker = ProjectInitWorker(self.selected_project, self.sources, self)
        self.worker.finished.connect(self._on_analysis_done)
        self.worker.error.connect(self._on_analysis_error)
        self.worker.start()

    def _on_analysis_done(self, definition):
        self.result_definition = definition
        self.progress_analysis.setVisible(False)
        self.analysis_label.setText("Definició generada. Pots editar-la abans de desar:")
        md = format_markdown(definition)
        self.markdown_edit.setPlainText(md)
        self.markdown_edit.setVisible(True)
        self.btn_next.setEnabled(True)
        self.btn_next.setText("Desar projecte")

    def _on_analysis_error(self, msg: str):
        self.progress_analysis.setVisible(False)
        self.analysis_label.setText(f"Error en l'anàlisi: {msg}\nPots editar la definició manualment:")
        self.markdown_edit.setVisible(True)
        self.btn_next.setEnabled(True)
        self.btn_next.setText("Desar projecte")

    # ── Pàgina 3: Resultat ───────────────────────────────────────────────────

    def _build_page3_result(self):
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
            row = self.projects_list.currentRow()
            if row < 0:
                return
            self.selected_project = self.projects_list.item(row).text()
            self._populate_sources()

        elif idx == 1:
            self.stack.setCurrentIndex(2)
            self._update_nav()
            self._start_analysis()
            return

        elif idx == 2:
            self._save_project()
            self.stack.setCurrentIndex(3)
            self._update_nav()
            return

        elif idx == 3:
            self.accept()
            return

        self.stack.setCurrentIndex(idx + 1)
        self._update_nav()

    def _update_nav(self):
        idx = self._current_page()

        self.btn_back.setEnabled(0 < idx < 2)
        self.btn_cancel.setEnabled(idx < 3)

        if idx == 0:
            self.btn_next.setText("Endavant")
            self.btn_next.setEnabled(self.projects_list.currentRow() >= 0)
        elif idx == 1:
            self.btn_next.setText("Analitzar")
            self.btn_next.setEnabled(True)
        elif idx == 2:
            self.btn_next.setText("Desar projecte")
        elif idx == 3:
            self.btn_next.setText("Tancar")
            self.btn_next.setEnabled(True)
            self.btn_cancel.setEnabled(False)

    # ── Desar ─────────────────────────────────────────────────────────────────

    def _save_project(self):
        note_path = (
            self.obsidian.vault / 'Reunions' / 'Projectes'
            / self.selected_project / f'{self.selected_project}.md'
        )

        md = self.markdown_edit.toPlainText().strip()
        note_path.write_text(md, encoding='utf-8')

        # Mark source meetings as processed
        for item in self.meetings_tree.selectedItems():
            path_str = item.data(0, Qt.ItemDataRole.UserRole)
            if path_str:
                path = Path(path_str)
                if path.exists() and not path.stem.endswith('*'):
                    try:
                        self.obsidian.mark_as_processed(path)
                    except Exception:
                        pass

        self.result_label.setText(
            f"Projecte «{self.selected_project}» definit!\n\n"
            f"Fitxer actualitzat:\n"
            f"Reunions/Projectes/{self.selected_project}/{self.selected_project}.md"
        )
