import shutil
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QStackedWidget, QWidget,
    QPushButton, QTreeWidget, QTreeWidgetItem,
    QLabel, QMessageBox, QFileDialog, QLineEdit
)
from PySide6.QtCore import Qt


class WizardFitxers(QDialog):
    def __init__(self, obsidian, parent=None):
        super().__init__(parent)
        self.obsidian = obsidian
        self.setWindowTitle("Entrar fitxers")
        self.setMinimumSize(700, 500)

        self.selected_file: Path | None = None
        self.selected_target_dir: Path | None = None

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

        self._build_page0_file()
        self._build_page1_tree()
        self._build_page2_confirm()

        self._update_nav()

    # -- Pàgina 0: Selecció de fitxer --

    def _build_page0_file(self):
        page = QVBoxLayout()
        page.setAlignment(Qt.AlignmentFlag.AlignTop)
        container = self._make_page(page)

        page.addWidget(QLabel("Selecciona el fitxer a desar:"))
        page.addSpacing(12)

        file_row = QHBoxLayout()
        self.file_path_edit = QLineEdit()
        self.file_path_edit.setReadOnly(True)
        self.file_path_edit.setPlaceholderText("Cap fitxer seleccionat...")
        file_row.addWidget(self.file_path_edit)
        btn_browse = QPushButton("Examinar...")
        btn_browse.clicked.connect(self._browse_file)
        file_row.addWidget(btn_browse)
        page.addLayout(file_row)

        self.stack.addWidget(container)

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Selecciona un fitxer")
        if path:
            self.selected_file = Path(path)
            self.file_path_edit.setText(path)
            self._update_nav()

    # -- Pàgina 1: Selecció de directori --

    def _build_page1_tree(self):
        page = QVBoxLayout()
        container = self._make_page(page)
        page.addWidget(QLabel("Selecciona el directori de destí:"))
        self.tree_dirs = QTreeWidget()
        self.tree_dirs.setHeaderHidden(True)
        self.tree_dirs.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.tree_dirs.itemSelectionChanged.connect(self._on_tree_selection_changed)
        page.addWidget(self.tree_dirs)
        self.stack.addWidget(container)

    def _populate_tree(self):
        self.tree_dirs.clear()
        self.selected_target_dir = None
        self._add_tree_items(None, self.obsidian.vault / 'Reunions')
        self.tree_dirs.collapseAll()

    def _add_tree_items(self, parent_item, directory: Path):
        try:
            subdirs = sorted(
                [d for d in directory.iterdir()
                 if d.is_dir() and not d.name.startswith('.') and d.name != 'zConfig'],
                key=lambda d: d.name
            )
        except PermissionError:
            return
        for d in subdirs:
            item = QTreeWidgetItem(self.tree_dirs if parent_item is None else parent_item)
            item.setText(0, d.name)
            item.setData(0, Qt.ItemDataRole.UserRole, d)
            self._add_tree_items(item, d)

    def _on_tree_selection_changed(self):
        items = self.tree_dirs.selectedItems()
        self.selected_target_dir = items[0].data(0, Qt.ItemDataRole.UserRole) if items else None
        self._update_nav()

    # -- Pàgina 2: Confirmació --

    def _build_page2_confirm(self):
        page = QVBoxLayout()
        container = self._make_page(page)

        self.confirm_label = QLabel()
        self.confirm_label.setWordWrap(True)
        self.confirm_label.setStyleSheet("font-size: 13px;")
        page.addWidget(self.confirm_label)
        page.addStretch()

        self.stack.addWidget(container)

    def _update_confirm(self):
        try:
            dir_text = str(self.selected_target_dir.relative_to(self.obsidian.vault))
        except ValueError:
            dir_text = str(self.selected_target_dir)
        self.confirm_label.setText(
            f"Fitxer: {self.selected_file.name}\n"
            f"Directori: {dir_text}"
        )

    # -- Navegació --

    def _make_page(self, layout):
        w = QWidget()
        w.setLayout(layout)
        return w

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
            if self.selected_file is None:
                return
            self._populate_tree()

        elif idx == 1:
            if self.selected_target_dir is None:
                return
            self._update_confirm()

        elif idx == 2:
            self._save()
            return

        self.stack.setCurrentIndex(idx + 1)
        self._update_nav()

    def _update_nav(self):
        idx = self._current_page()
        self.btn_back.setEnabled(idx > 0)
        self.btn_next.setText("Desar" if idx == 2 else "Endavant")

        if idx == 0:
            self.btn_next.setEnabled(self.selected_file is not None)
        elif idx == 1:
            self.btn_next.setEnabled(self.selected_target_dir is not None)
        else:
            self.btn_next.setEnabled(True)

    def _save(self):
        try:
            dest = self.selected_target_dir / self.selected_file.name
            shutil.copy2(self.selected_file, dest)
            success = True
        except Exception:
            success = False

        if success:
            ret = QMessageBox.question(
                self, "Fitxer desat",
                "Fitxer guardat correctament!\n\nVols entrar un altre fitxer?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if ret == QMessageBox.StandardButton.Yes:
                self._reset()
            else:
                self.accept()
        else:
            QMessageBox.critical(self, "Error", "Error guardant el fitxer.")

    def _reset(self):
        self.selected_file = None
        self.selected_target_dir = None
        self.file_path_edit.clear()
        self.tree_dirs.clear()
        self.stack.setCurrentIndex(0)
        self._update_nav()
