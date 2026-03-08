from datetime import datetime
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QStackedWidget, QWidget,
    QPushButton, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem,
    QLabel, QProgressBar, QMessageBox, QHeaderView, QDateEdit
)
from PySide6.QtCore import Qt, QDate
from workers import CalendarWorker
from widgets.transcript_editor import TranscriptEditor


class WizardTranscripcio(QDialog):
    def __init__(self, calendar, obsidian, parent=None):
        super().__init__(parent)
        self.calendar = calendar
        self.obsidian = obsidian
        self.setWindowTitle("Entrar transcripcions")
        self.setMinimumSize(700, 500)

        self.reunions = []
        self.selected_reunio = None
        self.selected_target_dir: Path | None = None

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

        self._build_page0_meetings()
        self._build_page1_tree()
        self._build_page2_transcript()
        self._build_page3_confirm()

        self._update_nav()
        self._load_meetings()

    # -- Pàgina 0: Seleccionar reunió --

    def _build_page0_meetings(self):
        page = QVBoxLayout()
        container = self._make_page(page)

        page.addWidget(QLabel("Selecciona una reunió:"))

        # Filtre de dates
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
        btn_search.clicked.connect(self._load_meetings)
        date_row.addWidget(btn_search)
        date_row.addStretch()
        page.addLayout(date_row)

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

        self.stack.addWidget(container)

    def _load_meetings(self):
        self.progress_meetings.setVisible(True)
        self.table_meetings.setRowCount(0)
        qd_from = self.date_from.date()
        qd_to = self.date_to.date()
        date_from = datetime(qd_from.year(), qd_from.month(), qd_from.day())
        date_to = datetime(qd_to.year(), qd_to.month(), qd_to.day())
        self.worker_cal = CalendarWorker(self.calendar, date_from=date_from, date_to=date_to, parent=self)
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

    # -- Pàgina 2: Transcripció --

    def _build_page2_transcript(self):
        page = QVBoxLayout()
        container = self._make_page(page)

        page.addWidget(QLabel("Enganxa la transcripció:"))
        self.transcript_editor = TranscriptEditor()
        self.transcript_editor.editor.textChanged.connect(self._update_nav)
        page.addWidget(self.transcript_editor)

        self.stack.addWidget(container)

    # -- Pàgina 3: Confirmació --

    def _build_page3_confirm(self):
        page = QVBoxLayout()
        container = self._make_page(page)

        self.confirm_label = QLabel()
        self.confirm_label.setWordWrap(True)
        self.confirm_label.setStyleSheet("font-size: 13px;")
        page.addWidget(self.confirm_label)
        page.addStretch()

        self.stack.addWidget(container)

    def _update_confirm(self):
        lines = len(self.transcript_editor.get_text().splitlines()) if self.transcript_editor.get_text() else 0
        try:
            dir_text = str(self.selected_target_dir.relative_to(self.obsidian.vault))
        except ValueError:
            dir_text = str(self.selected_target_dir)
        self.confirm_label.setText(
            f"Reunió: {self.selected_reunio['title']}\n"
            f"Data: {self.selected_reunio['start'].strftime('%d/%m/%Y %H:%M')}\n"
            f"Directori: {dir_text}\n"
            f"Línies: {lines}"
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
            rows = self.table_meetings.selectionModel().selectedRows()
            if not rows:
                return
            self.selected_reunio = self.reunions[rows[0].row()]
            self._populate_tree()

        elif idx == 1:
            if self.selected_target_dir is None:
                return

        elif idx == 2:
            if not self.transcript_editor.get_text():
                return
            self._update_confirm()

        elif idx == 3:
            self._save()
            return

        self.stack.setCurrentIndex(idx + 1)
        self._update_nav()

    def _update_nav(self):
        idx = self._current_page()
        self.btn_back.setEnabled(idx > 0)
        self.btn_next.setText("Desar" if idx == 3 else "Endavant")

        if idx == 1:
            self.btn_next.setEnabled(self.selected_target_dir is not None)
        elif idx == 2:
            self.btn_next.setEnabled(bool(self.transcript_editor.get_text()))
        else:
            self.btn_next.setEnabled(True)

    def _save(self):
        success = self.obsidian.create_simple_note(
            self.selected_reunio,
            self.transcript_editor.get_text(),
            self.selected_target_dir
        )
        if success:
            ret = QMessageBox.question(
                self, "Nota desada",
                "Nota guardada correctament!\n\nVols entrar una altra transcripció?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if ret == QMessageBox.StandardButton.Yes:
                self._reset()
            else:
                self.accept()
        else:
            QMessageBox.critical(self, "Error", "Error guardant la nota.")

    def _reset(self):
        self.selected_reunio = None
        self.selected_target_dir = None
        self.transcript_editor.clear()
        self.table_meetings.clearSelection()
        self.tree_dirs.clear()
        self.stack.setCurrentIndex(0)
        self._update_nav()
        self._load_meetings()
