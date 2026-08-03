"""Wizard Consolidar (fase 2 del processat de seguiments).

Llista les reunions en estat '+' (Ordre del dia generat, pendent de consolidar).
Un cop l'usuari ha validat/corregit l'Ordre del dia a Obsidian, consolida els
resums a Temes oberts.md + fitxer anual i marca la nota processada ('*').

La consolidació és ràpida (sense LLM): parse de l'Ordre del dia + escriptures de
fitxers. Es fa de forma síncrona.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QProgressBar,
)

from window_drag import install_window_drag
from consolidator import consolidate_pending_note


class WizardConsolidar(QDialog):
    def __init__(self, obsidian, parent=None, preselected_paths=None):
        super().__init__(parent)
        self.obsidian = obsidian
        self.setWindowTitle("Consolidar reunions")
        self.setMinimumSize(800, 500)
        install_window_drag(self)

        # Si s'obre des del tauler, es filtra a les notes triades i es
        # preseleccionen totes (l'usuari només ha de confirmar).
        self.preselected_paths = preselected_paths
        self.notes = []

        layout = QVBoxLayout(self)

        hint = QLabel(
            "Reunions amb l'Ordre del dia generat, pendents de consolidar.\n"
            "Valida/corregeix l'Ordre del dia a Obsidian ABANS de consolidar: "
            "el que consolidis s'escriu a Temes oberts i al fitxer anual."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        header = QHBoxLayout()
        header.addWidget(QLabel("Pendents de consolidar:"))
        header.addStretch()
        self.lbl_sel_count = QLabel("0 seleccionades")
        header.addWidget(self.lbl_sel_count)
        self.btn_sel_all = QPushButton("Sel. tot")
        self.btn_sel_all.clicked.connect(self._toggle_select_all)
        header.addWidget(self.btn_sel_all)
        layout.addLayout(header)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Data", "Títol", "Sèrie", "Estat"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        hv = self.table.horizontalHeader()
        hv.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hv.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hv.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hv.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        nav = QHBoxLayout()
        nav.addStretch()
        self.btn_consolidar = QPushButton("Consolidar seleccionades")
        self.btn_consolidar.clicked.connect(self._consolidate_selected)
        self.btn_close = QPushButton("Tancar")
        self.btn_close.clicked.connect(self.accept)
        nav.addWidget(self.btn_close)
        nav.addWidget(self.btn_consolidar)
        layout.addLayout(nav)

        self._load_notes()

    def _load_notes(self):
        self.notes = self.obsidian.find_pending_consolidation_notes()
        if self.preselected_paths is not None:
            self.notes = [n for n in self.notes if n['path'] in self.preselected_paths]
        self.table.setRowCount(len(self.notes))
        for i, n in enumerate(self.notes):
            series = n['path'].parent.parent.name
            self.table.setItem(i, 0, QTableWidgetItem(n['date']))
            self.table.setItem(i, 1, QTableWidgetItem(n['title']))
            self.table.setItem(i, 2, QTableWidgetItem(series))
            self.table.setItem(i, 3, QTableWidgetItem("Pendent"))
        if self.preselected_paths is not None:
            self.table.selectAll()
        self._on_selection_changed()
        self.btn_consolidar.setEnabled(len(self.notes) > 0)

    def _toggle_select_all(self):
        if self.table.selectionModel().selectedRows():
            self.table.clearSelection()
        else:
            self.table.selectAll()

    def _on_selection_changed(self):
        count = len(self.table.selectionModel().selectedRows())
        self.lbl_sel_count.setText(f"{count} seleccionades")
        self.btn_sel_all.setText("Desel. tot" if count and count == len(self.notes) else "Sel. tot")

    def _consolidate_selected(self):
        rows = sorted(r.row() for r in self.table.selectionModel().selectedRows())
        if not rows:
            return
        self.btn_consolidar.setEnabled(False)
        self.btn_close.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, len(rows))
        self.progress.setValue(0)

        ok = 0
        for done, r in enumerate(rows, 1):
            note = self.notes[r]
            try:
                res = consolidate_pending_note(self.obsidian, note)
                msg = "Consolidada ✓" if res["year_written"] else "Consolidada (sense resum)"
                self.table.setItem(r, 3, QTableWidgetItem(msg))
                ok += 1
            except Exception as e:
                cell = QTableWidgetItem(f"Error: {str(e).splitlines()[0][:60]}")
                cell.setToolTip(str(e))
                self.table.setItem(r, 3, cell)
            self.progress.setValue(done)

        # Recarrega: les consolidades ('*') ja no surten; queden les fallides.
        self._load_notes()
        self.btn_close.setEnabled(True)
        self.progress.setVisible(False)
