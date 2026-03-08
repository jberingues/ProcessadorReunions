from datetime import datetime
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QStackedWidget, QWidget,
    QPushButton, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem,
    QLabel, QProgressBar, QMessageBox, QHeaderView, QDateEdit
)
from PySide6.QtCore import Qt, QDate
from workers import GmailWorker


class WizardCorreus(QDialog):
    def __init__(self, gmail_fetcher, obsidian, parent=None):
        super().__init__(parent)
        self.gmail_fetcher = gmail_fetcher
        self.obsidian = obsidian
        self.setWindowTitle("Entrar correus")
        self.setMinimumSize(1000, 500)

        self.threads = []
        self.selected_thread: dict | None = None
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

        self._build_page0_threads()
        self._build_page1_tree()
        self._build_page2_confirm()

        self._update_nav()

    # -- Pàgina 0: Llista de fils --

    def _build_page0_threads(self):
        page = QVBoxLayout()
        container = self._make_page(page)

        page.addWidget(QLabel("Selecciona un fil de correu (etiqueta \"Arxivar\"):"))

        date_row = QHBoxLayout()
        date_row.addWidget(QLabel("Data inicial:"))
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDate(QDate.currentDate().addDays(-1))
        self.date_from.setDisplayFormat("dd/MM/yyyy")
        date_row.addWidget(self.date_from)
        date_row.addSpacing(16)
        date_row.addWidget(QLabel("Data final:"))
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDate(QDate.currentDate())
        self.date_to.setDisplayFormat("dd/MM/yyyy")
        date_row.addWidget(self.date_to)
        date_row.addSpacing(16)
        btn_search = QPushButton("Cercar")
        btn_search.clicked.connect(self._load_threads)
        date_row.addWidget(btn_search)
        date_row.addStretch()
        page.addLayout(date_row)

        self.progress_threads = QProgressBar()
        self.progress_threads.setRange(0, 0)
        self.progress_threads.setVisible(False)
        page.addWidget(self.progress_threads)

        self.table_threads = QTableWidget()
        self.table_threads.setColumnCount(4)
        self.table_threads.setHorizontalHeaderLabels(["Data", "Assumpte", "Remitent", "Missatges"])
        self.table_threads.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_threads.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        header = self.table_threads.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table_threads.setColumnWidth(0, 90)
        self.table_threads.setColumnWidth(3, 80)
        self.table_threads.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_threads.doubleClicked.connect(self._go_next)
        page.addWidget(self.table_threads)

        self.stack.addWidget(container)

    def _load_threads(self):
        self.progress_threads.setVisible(True)
        self.table_threads.setRowCount(0)
        qd_from = self.date_from.date()
        qd_to = self.date_to.date()
        date_from = datetime(qd_from.year(), qd_from.month(), qd_from.day())
        date_to = datetime(qd_to.year(), qd_to.month(), qd_to.day())
        self.worker_gmail = GmailWorker(self.gmail_fetcher, date_from, date_to, parent=self)
        self.worker_gmail.finished.connect(self._on_threads_loaded)
        self.worker_gmail.error.connect(self._on_threads_error)
        self.worker_gmail.start()

    def _on_threads_loaded(self, threads):
        self.progress_threads.setVisible(False)
        self.threads = threads
        self.table_threads.setRowCount(len(threads))
        for i, t in enumerate(threads):
            data = t['date'].strftime('%d/%m/%Y')
            self.table_threads.setItem(i, 0, QTableWidgetItem(data))
            self.table_threads.setItem(i, 1, QTableWidgetItem(t['subject']))
            self.table_threads.setItem(i, 2, QTableWidgetItem(t['from']))
            self.table_threads.setItem(i, 3, QTableWidgetItem(str(t['num_messages'])))

    def _on_threads_error(self, msg):
        self.progress_threads.setVisible(False)
        QMessageBox.critical(self, "Error", f"Error carregant correus:\n{msg}")

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
        t = self.selected_thread
        try:
            dir_text = str(self.selected_target_dir.relative_to(self.obsidian.vault))
        except ValueError:
            dir_text = str(self.selected_target_dir)
        self.confirm_label.setText(
            f"Assumpte: {t['subject']}\n"
            f"De: {t['from']}\n"
            f"Data: {t['date'].strftime('%d/%m/%Y')}\n"
            f"Missatges: {t['num_messages']}\n"
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
            rows = self.table_threads.selectionModel().selectedRows()
            if not rows:
                return
            self.selected_thread = self.threads[rows[0].row()]
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

        if idx == 1:
            self.btn_next.setEnabled(self.selected_target_dir is not None)
        else:
            self.btn_next.setEnabled(True)

    def _save(self):
        success = self.obsidian.create_email_note(
            self.selected_thread,
            self.selected_target_dir
        )
        if success:
            ret = QMessageBox.question(
                self, "Nota desada",
                "Nota guardada correctament!\n\nVols entrar un altre correu?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if ret == QMessageBox.StandardButton.Yes:
                self._reset()
            else:
                self.accept()
        else:
            QMessageBox.critical(self, "Error", "Error guardant la nota.")

    def _reset(self):
        self.selected_thread = None
        self.selected_target_dir = None
        self.table_threads.clearSelection()
        self.tree_dirs.clear()
        self.stack.setCurrentIndex(0)
        self._update_nav()
