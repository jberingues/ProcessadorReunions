import difflib
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Union

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QStackedWidget, QWidget,
    QPushButton, QTreeWidget, QTreeWidgetItem, QLabel,
    QMessageBox, QProgressBar,
)

from meeting_recording_matcher import Pair
from plaud_client import PlaudRecording
from widgets.pairing_view import PairingView
from widgets.transcript_editor import TranscriptEditor
from workers import PlaudTranscriptWorker


# Una unitat de feina és un parell aparellat o una gravació orfe (sense reunió
# al calendari). Les reunions sense gravació es descarten — no entren al flux.
WorkItem = Union[Pair, PlaudRecording]

_MATCH_THRESHOLD = 0.4


def _normalize(text: str) -> str:
    """Minúscules, sense accents, només alfanumèrics i espais."""
    text = unicodedata.normalize('NFD', text.lower())
    return ''.join(
        c for c in text
        if unicodedata.category(c) != 'Mn' and (c.isalnum() or c == ' ')
    )


def _folder_score(title: str, folder_name: str) -> float:
    """Puntuació 0–1 de similitud entre el títol de l'event i el nom de carpeta."""
    t = _normalize(title)
    f = _normalize(folder_name)
    if not f:
        return 0.0
    # La carpeta apareix íntegrament dins el títol
    if f in t:
        return 0.9
    # Quantes paraules de la carpeta (≥3 chars) apareixen al títol
    f_words = [w for w in f.split() if len(w) >= 3]
    if f_words:
        hits = sum(1 for w in f_words if w in t)
        if hits:
            return 0.5 + 0.4 * (hits / len(f_words))
    return difflib.SequenceMatcher(None, t, f).ratio()


class WizardTranscripcio(QDialog):
    def __init__(self, calendar, obsidian, plaud_client, parent=None):
        super().__init__(parent)
        self.calendar = calendar
        self.obsidian = obsidian
        self.plaud_client = plaud_client
        self.setWindowTitle("Entrar transcripcions")
        self.setMinimumSize(1100, 700)

        self.work_queue: list[WorkItem] = []
        self.current_item: Optional[WorkItem] = None
        self.current_index: int = 0
        self.total_items: int = 0
        self.selected_target_dir: Optional[Path] = None
        self._transcript_worker: Optional[PlaudTranscriptWorker] = None

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

        self._build_page0_pairing()
        self._build_page1_tree()
        self._build_page2_transcript()

        self._update_nav()

    # -- Pàgina 0: aparellament Calendari ↔ Plaud --

    def _build_page0_pairing(self):
        page = QWidget()
        page_layout = QVBoxLayout(page)
        self.pairing_view = PairingView(self.calendar, self.plaud_client)
        page_layout.addWidget(self.pairing_view)
        self.stack.addWidget(page)

    # -- Pàgina 1: selecció de directori --

    def _build_page1_tree(self):
        page = QWidget()
        page_layout = QVBoxLayout(page)
        self.lbl_current_item_p1 = QLabel("")
        self.lbl_current_item_p1.setStyleSheet("font-weight: bold; font-size: 14px;")
        page_layout.addWidget(self.lbl_current_item_p1)
        page_layout.addWidget(QLabel("Selecciona el directori de destí:"))
        self.tree_dirs = QTreeWidget()
        self.tree_dirs.setHeaderHidden(True)
        self.tree_dirs.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.tree_dirs.itemSelectionChanged.connect(self._on_tree_selection_changed)
        self.tree_dirs.itemDoubleClicked.connect(self._on_tree_double_click)
        page_layout.addWidget(self.tree_dirs)
        self.stack.addWidget(page)

    def _populate_tree(self):
        self.tree_dirs.clear()
        self.selected_target_dir = None
        self._add_tree_items(None, self.obsidian.vault / 'Reunions')
        self.tree_dirs.collapseAll()

    def _add_tree_items(self, parent_item, directory: Path):
        """Recursivament afegeix subdirectoris al tree.

        Una carpeta és seleccionable si conté una subcarpeta 'Reunions/'.
        En aquest cas, el target d'escriptura és '<carpeta>/Reunions/'.
        No descendim dins de subcarpetes 'Reunions' — són la destinació final
        i no formen part de la jerarquia de navegació.
        """
        try:
            subdirs = sorted(
                [d for d in directory.iterdir()
                 if d.is_dir() and not d.name.startswith('.')
                    and d.name not in ('zConfig', 'Reunions')],
                key=lambda d: d.name
            )
        except PermissionError:
            return
        for d in subdirs:
            item = QTreeWidgetItem(self.tree_dirs if parent_item is None else parent_item)
            item.setText(0, d.name)
            reunions_subdir = d / 'Reunions'
            if reunions_subdir.is_dir():
                # Carpeta de destinació: no descendim, el que hi ha dins
                # (Annexos, Documentació, etc.) no és part de la navegació.
                item.setData(0, Qt.ItemDataRole.UserRole, reunions_subdir)
            else:
                # Node purament organitzatiu (e.g. "Proveïdors", "Projectes")
                item.setData(0, Qt.ItemDataRole.UserRole, None)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                item.setForeground(0, QColor(140, 140, 140))
                self._add_tree_items(item, d)

    def _auto_select_folder(self, title: str):
        """Pre-selecciona la carpeta del tree més similar al títol, si supera el llindar."""
        best_item = None
        best_score = _MATCH_THRESHOLD

        def walk(item):
            nonlocal best_item, best_score
            if item.data(0, Qt.ItemDataRole.UserRole) is not None:
                score = _folder_score(title, item.text(0))
                if score > best_score:
                    best_score = score
                    best_item = item
            for i in range(item.childCount()):
                walk(item.child(i))

        root = self.tree_dirs.invisibleRootItem()
        for i in range(root.childCount()):
            walk(root.child(i))

        if best_item is not None:
            # Expandeix els avantpassats perquè l'ítem sigui visible
            parent = best_item.parent()
            while parent is not None:
                parent.setExpanded(True)
                parent = parent.parent()
            self.tree_dirs.setCurrentItem(best_item)
            self.tree_dirs.scrollToItem(best_item)

    def _on_tree_selection_changed(self):
        items = self.tree_dirs.selectedItems()
        self.selected_target_dir = items[0].data(0, Qt.ItemDataRole.UserRole) if items else None
        self._update_nav()

    def _on_tree_double_click(self, item, _column):
        if item.data(0, Qt.ItemDataRole.UserRole) is not None:
            self._go_next()

    # -- Pàgina 2: transcripció --

    def _build_page2_transcript(self):
        page = QWidget()
        page_layout = QVBoxLayout(page)
        self.lbl_current_item_p2 = QLabel("")
        self.lbl_current_item_p2.setStyleSheet("font-weight: bold; font-size: 14px;")
        page_layout.addWidget(self.lbl_current_item_p2)
        self.lbl_transcript_status = QLabel("")
        self.lbl_transcript_status.setStyleSheet("color: #666;")
        page_layout.addWidget(self.lbl_transcript_status)
        self.transcript_progress = QProgressBar()
        self.transcript_progress.setRange(0, 0)
        self.transcript_progress.setVisible(False)
        page_layout.addWidget(self.transcript_progress)
        self.transcript_editor = TranscriptEditor()
        self.transcript_editor.editor.textChanged.connect(self._update_nav)
        page_layout.addWidget(self.transcript_editor)
        self.stack.addWidget(page)

    # -- Helpers de WorkItem --

    def _item_title(self, item: WorkItem) -> str:
        if isinstance(item, Pair):
            return item.event.get('title', '(sense títol)')
        return item.name

    def _item_file_id(self, item: WorkItem) -> str:
        if isinstance(item, Pair):
            return item.recording.file_id
        return item.file_id

    def _item_meeting_dict(self, item: WorkItem) -> dict:
        """Retorna un dict compatible amb ObsidianWriter.create_simple_note."""
        if isinstance(item, Pair):
            return item.event
        # Gravació orfe → fabriquem dict amb metadades del Plaud
        rec: PlaudRecording = item
        start = rec.start_at
        end = (start + timedelta(seconds=rec.duration_seconds)) if start else start
        return {
            'title': rec.name,
            'start': start,
            'end': end,
            'attendees': [],
        }

    # -- Navegació --

    def _current_page(self):
        return self.stack.currentIndex()

    def _go_back(self):
        # Només permetem tornar de la pàgina 2 a la 1 dins una iteració.
        # No es pot tornar a la pàgina 0 perquè la cua de feina ja ha estat
        # iniciada i tornar a aparellar perdria el progrés acumulat.
        if self._current_page() == 2:
            self.stack.setCurrentIndex(1)
            self._update_nav()

    def _go_next(self):
        idx = self._current_page()
        if idx == 0:
            self._start_iteration()
        elif idx == 1:
            if self.selected_target_dir is None:
                return
            self.stack.setCurrentIndex(2)
            self._update_nav()
        elif idx == 2:
            if not self.transcript_editor.get_text() or self._transcript_loading():
                return
            self._save_current()

    def _start_iteration(self):
        pairs, _unmatched_events, unmatched_recs = self.pairing_view.get_state()
        work_items: list[WorkItem] = list(pairs) + list(unmatched_recs)
        self.work_queue = sorted(
            work_items,
            key=lambda it: (
                it.event["start"] if isinstance(it, Pair)
                else (it.start_at or datetime.min.replace(tzinfo=timezone.utc))
            ),
        )
        if not self.work_queue:
            QMessageBox.information(
                self, "Res a processar",
                "No hi ha cap parell aparellat ni cap gravació orfe. "
                "Aparella reunions abans de continuar o canvia el dia."
            )
            return
        self.total_items = len(self.work_queue)
        self.current_index = 0
        self._advance_to_next_item()

    def _advance_to_next_item(self):
        if not self.work_queue:
            self.accept()
            return
        self.current_item = self.work_queue.pop(0)
        self.current_index += 1
        title = self._item_title(self.current_item)
        progress_text = f"Element {self.current_index} de {self.total_items} — {title}"
        self.lbl_current_item_p1.setText(progress_text)
        self.lbl_current_item_p2.setText(progress_text)
        self.transcript_editor.clear()
        self._populate_tree()
        self._auto_select_folder(self._item_title(self.current_item))
        self._start_transcript_fetch()
        self.stack.setCurrentIndex(1)
        self._update_nav()

    # -- Càrrega asíncrona de la transcripció --

    def _transcript_loading(self) -> bool:
        return self._transcript_worker is not None and self._transcript_worker.isRunning()

    def _start_transcript_fetch(self):
        if self._transcript_worker is not None:
            try:
                self._transcript_worker.finished.disconnect()
                self._transcript_worker.error.disconnect()
            except (RuntimeError, TypeError):
                pass
        file_id = self._item_file_id(self.current_item)
        self.lbl_transcript_status.setText("Baixant transcripció de Plaud…")
        self.transcript_progress.setVisible(True)
        self._transcript_worker = PlaudTranscriptWorker(self.plaud_client, file_id, parent=self)
        self._transcript_worker.finished.connect(self._on_transcript_loaded)
        self._transcript_worker.error.connect(self._on_transcript_error)
        self._transcript_worker.start()

    def _on_transcript_loaded(self, file_id: str, text: str):
        # Si l'usuari ha avançat ràpid, el worker pot retornar amb un file_id
        # diferent del item actual: ignorem el resultat antic.
        if self.current_item is None or file_id != self._item_file_id(self.current_item):
            return
        self.transcript_progress.setVisible(False)
        self.lbl_transcript_status.setText("Transcripció baixada. Revisa-la abans de desar.")
        self.transcript_editor.editor.setPlainText(text)
        self._update_nav()

    def _on_transcript_error(self, file_id: str, msg: str):
        if self.current_item is None or file_id != self._item_file_id(self.current_item):
            return
        self.transcript_progress.setVisible(False)
        self.lbl_transcript_status.setText(
            f"Error baixant la transcripció: {msg}. Pots enganxar-la manualment."
        )
        self._update_nav()

    # -- Desar i avançar --

    def _save_current(self):
        meeting = self._item_meeting_dict(self.current_item)
        text = self.transcript_editor.get_text()
        ok = self.obsidian.create_simple_note(meeting, text, self.selected_target_dir)
        if not ok:
            QMessageBox.critical(
                self, "Error",
                f"Error guardant la nota '{meeting.get('title', '')}'."
            )
            return
        self._advance_to_next_item()

    def _update_nav(self):
        idx = self._current_page()
        # Enrere només actiu a la pàgina 2 (per tornar a triar carpeta)
        self.btn_back.setEnabled(idx == 2)
        self.btn_next.setText("Desar" if idx == 2 else "Endavant")
        if idx == 0:
            self.btn_next.setEnabled(True)
        elif idx == 1:
            self.btn_next.setEnabled(self.selected_target_dir is not None)
        elif idx == 2:
            self.btn_next.setEnabled(
                bool(self.transcript_editor.get_text()) and not self._transcript_loading()
            )
