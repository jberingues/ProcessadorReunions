"""Widget per aparellar reunions de Google Calendar amb gravacions de Plaud.

Carrega ambdues fonts en paral·lel per a una data, fa auto-match amb el
MeetingRecordingMatcher i permet a l'usuari ajustar manualment els parells.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from PySide6.QtCore import Qt, QDate, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDateEdit,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from meeting_recording_matcher import Pair, PairStatus, match
from plaud_client import PlaudRecording
from workers import CalendarWorker, PlaudListWorker


# Colors de fons per indicar l'estat d'una fila. Triats prou foscos perquè
# el text blanc (per defecte a macOS dark mode) sigui llegible.
_COLOR_AUTO = QColor(46, 125, 50)        # verd fosc (Material green 800)
_COLOR_SUGGESTED = QColor(230, 145, 0)   # taronja fosc
_COLOR_MANUAL = QColor(21, 101, 192)     # blau fosc (Material blue 800)
_TEXT_ON_COLORED = QColor(255, 255, 255)  # text blanc explícit


def _fmt_local_time(dt: datetime) -> str:
    """Format hora local 'HH:MM' a partir d'un datetime tz-aware."""
    return dt.astimezone().strftime("%H:%M")


def _fmt_duration_seconds(seconds: int) -> str:
    """'22m19s' → '22 min', '1h23m45s' → '1h 24m'."""
    if seconds < 60:
        return f"{seconds}s"
    minutes = (seconds + 30) // 60
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60}h {minutes % 60:02d}m"


def _fmt_duration_event(start: datetime, end: datetime) -> str:
    return _fmt_duration_seconds(int((end - start).total_seconds()))


class PairingView(QWidget):
    """Widget de pàgina 0 redissenyada del wizard de transcripcions.

    Senyals:
        loaded(): emès quan els dos workers han acabat (calendari + Plaud).
        plaud_not_authenticated(): emès si el CLI de Plaud no està autenticat.
        plaud_error(str): emès si el CLI de Plaud retorna error genèric.
    """

    loaded = Signal()
    plaud_not_authenticated = Signal()
    plaud_error = Signal(str)

    def __init__(self, calendar, plaud_client, parent=None):
        super().__init__(parent)
        self.calendar = calendar
        self.plaud_client = plaud_client

        self.events: list[dict[str, Any]] = []
        self.recordings: list[PlaudRecording] = []
        self.pairs: list[Pair] = []
        # Estats per fila (sincronitzats amb self.events i self.recordings)
        self._event_status: list[Optional[PairStatus]] = []
        self._rec_status: list[Optional[PairStatus]] = []

        self._cal_worker: Optional[CalendarWorker] = None
        self._plaud_worker: Optional[PlaudListWorker] = None
        self._cal_done = False
        self._plaud_done = False
        self._syncing = False

        self._build_ui()

    # ---------- UI ----------

    def _build_ui(self):
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("Data:"))
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.setDisplayFormat("dd/MM/yyyy")
        top.addWidget(self.date_edit)
        top.addSpacing(12)
        self.btn_load = QPushButton("Carregar")
        self.btn_load.clicked.connect(self.load)
        top.addWidget(self.btn_load)
        top.addStretch()
        layout.addLayout(top)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666;")
        layout.addWidget(self.status_label)

        tables_row = QHBoxLayout()
        # Taula Plaud (esquerra) — es pot multi-seleccionar perquè una
        # gravació no aparellada s'inclogui al flux com a "orfe seleccionada".
        plaud_box = QVBoxLayout()
        plaud_box.addWidget(QLabel("Gravacions Plaud:"))
        self.table_plaud = self._make_table(["Hora", "Nom", "Durada", "Estat"])
        plaud_box.addWidget(self.table_plaud)
        tables_row.addLayout(plaud_box)
        # Taula calendari (dreta)
        cal_box = QVBoxLayout()
        cal_box.addWidget(QLabel("Reunions del calendari:"))
        self.table_cal = self._make_table(["Hora", "Títol", "Durada", "Estat"])
        cal_box.addWidget(self.table_cal)
        tables_row.addLayout(cal_box)
        layout.addLayout(tables_row, stretch=2)

        actions = QHBoxLayout()
        self.btn_pair = QPushButton("Aparellar seleccionats")
        self.btn_pair.clicked.connect(self._pair_selected)
        self.btn_pair.setEnabled(False)
        actions.addWidget(self.btn_pair)
        actions.addStretch()
        layout.addLayout(actions)

        layout.addWidget(QLabel("Parells confirmats:"))
        self.list_pairs = QListWidget()
        self.list_pairs.itemSelectionChanged.connect(self._on_pair_list_selection)
        layout.addWidget(self.list_pairs, stretch=1)

        unpair_row = QHBoxLayout()
        self.btn_unpair = QPushButton("Desfer parell seleccionat")
        self.btn_unpair.clicked.connect(self._unpair_selected)
        self.btn_unpair.setEnabled(False)
        unpair_row.addWidget(self.btn_unpair)
        unpair_row.addStretch()
        layout.addLayout(unpair_row)

        self.table_cal.itemSelectionChanged.connect(self._on_table_selection)
        self.table_plaud.itemSelectionChanged.connect(self._on_table_selection)

    def _make_table(self, headers: list[str]) -> QTableWidget:
        t = QTableWidget()
        t.setColumnCount(len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        # ExtendedSelection: Cmd+click per multi-selecció. Util sobretot a la
        # taula de Plaud per marcar diverses gravacions orfes com a migrar.
        t.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        # Força el color de selecció igual tant si la taula té focus com si no,
        # evitant que la fila seleccionada es torni grisa en perdre el focus.
        t.setStyleSheet(
            "QTableWidget::item:selected { background-color: #1976D2; color: white; }"
        )
        return t

    # ---------- Carregar dades ----------

    def load(self):
        """Llança els dos workers en paral·lel."""
        self.btn_load.setEnabled(False)
        self.progress.setVisible(True)
        self.status_label.setText("Carregant calendari i gravacions...")
        self.events = []
        self.recordings = []
        self.pairs = []
        self._cal_done = False
        self._plaud_done = False
        self._refresh_tables()
        self._refresh_pairs_list()

        qd = self.date_edit.date()
        target = datetime(qd.year(), qd.month(), qd.day())
        end_of_day = target + timedelta(days=1) - timedelta(seconds=1)

        self._cal_worker = CalendarWorker(self.calendar, date_from=target, date_to=end_of_day, parent=self)
        self._cal_worker.finished.connect(self._on_cal_loaded)
        self._cal_worker.error.connect(self._on_cal_error)
        self._cal_worker.start()

        self._plaud_worker = PlaudListWorker(self.plaud_client, target.date(), parent=self)
        self._plaud_worker.finished.connect(self._on_plaud_loaded)
        self._plaud_worker.error.connect(self._on_plaud_error)
        self._plaud_worker.not_authenticated.connect(self._on_plaud_not_auth)
        self._plaud_worker.start()

    def _on_cal_loaded(self, events: list[dict[str, Any]]):
        # Filtrar a esdeveniments amb dia == data seleccionada (CalendarWorker pot
        # retornar coses fora del rang per timezone).
        qd = self.date_edit.date()
        target_date = (qd.year(), qd.month(), qd.day())
        self.events = [
            e for e in events
            if (e["start"].astimezone().year, e["start"].astimezone().month, e["start"].astimezone().day) == target_date
        ]
        self._cal_done = True
        self._maybe_finalize()

    def _on_cal_error(self, msg: str):
        self.status_label.setText(f"Error calendari: {msg}")
        self._cal_done = True
        self._maybe_finalize()

    def _on_plaud_loaded(self, recordings: list[PlaudRecording]):
        self.recordings = list(recordings)
        self._plaud_done = True
        self._maybe_finalize()

    def _on_plaud_error(self, msg: str):
        self.status_label.setText(f"Error Plaud: {msg}")
        self.recordings = []
        self._plaud_done = True
        self.plaud_error.emit(msg)
        self._maybe_finalize()

    def _on_plaud_not_auth(self):
        self.status_label.setText(
            "Plaud no autenticat — executa `plaud login` al terminal i recarrega."
        )
        self.recordings = []
        self._plaud_done = True
        self.plaud_not_authenticated.emit()
        self._maybe_finalize()

    def _maybe_finalize(self):
        if not (self._cal_done and self._plaud_done):
            return
        self.progress.setVisible(False)
        self.btn_load.setEnabled(True)
        # Ordena per hora ascendent
        self.events.sort(key=lambda e: e["start"])
        self.recordings.sort(
            key=lambda r: r.start_at if r.start_at is not None
            else datetime.min.replace(tzinfo=timezone.utc)
        )
        # Auto-match
        result = match(self.events, self.recordings)
        self.pairs = list(result.pairs)
        self.status_label.setText(
            f"{len(self.events)} reunions · {len(self.recordings)} gravacions · "
            f"{len(self.pairs)} parells (auto/suggerit)"
        )
        self._refresh_tables()
        self._refresh_pairs_list()
        self.loaded.emit()

    # ---------- Render ----------

    def _refresh_tables(self):
        # Recalcula l'estat de cada fila a partir de self.pairs
        pair_by_event = {id(p.event): p for p in self.pairs}
        pair_by_rec = {p.recording.file_id: p for p in self.pairs}

        # Calendari
        self.table_cal.setRowCount(len(self.events))
        for i, ev in enumerate(self.events):
            start = ev["start"]
            end = ev["end"]
            items = [
                QTableWidgetItem(_fmt_local_time(start)),
                QTableWidgetItem(ev.get("title", "")),
                QTableWidgetItem(_fmt_duration_event(start, end)),
                QTableWidgetItem(self._status_text(pair_by_event.get(id(ev)))),
            ]
            color = self._row_color(pair_by_event.get(id(ev)))
            for col, it in enumerate(items):
                if color:
                    it.setBackground(color)
                    it.setForeground(_TEXT_ON_COLORED)
                self.table_cal.setItem(i, col, it)

        # Plaud
        self.table_plaud.setRowCount(len(self.recordings))
        for i, rec in enumerate(self.recordings):
            hora = _fmt_local_time(rec.start_at) if rec.start_at else "?"
            items = [
                QTableWidgetItem(hora),
                QTableWidgetItem(rec.name),
                QTableWidgetItem(_fmt_duration_seconds(rec.duration_seconds)),
                QTableWidgetItem(self._status_text(pair_by_rec.get(rec.file_id))),
            ]
            color = self._row_color(pair_by_rec.get(rec.file_id))
            for col, it in enumerate(items):
                if color:
                    it.setBackground(color)
                    it.setForeground(_TEXT_ON_COLORED)
                self.table_plaud.setItem(i, col, it)

    def _status_text(self, p: Optional[Pair]) -> str:
        if p is None:
            return ""
        if p.status == PairStatus.AUTO:
            return f"Auto ({p.score:.0%})"
        if p.status == PairStatus.SUGGESTED:
            return f"Suggerit ({p.score:.0%})"
        return "Manual"

    def _row_color(self, p: Optional[Pair]) -> Optional[QColor]:
        if p is None:
            return None
        return {
            PairStatus.AUTO: _COLOR_AUTO,
            PairStatus.SUGGESTED: _COLOR_SUGGESTED,
            PairStatus.MANUAL: _COLOR_MANUAL,
        }.get(p.status)

    def _refresh_pairs_list(self):
        self.list_pairs.clear()
        sorted_pairs = sorted(self.pairs, key=lambda p: p.event["start"])
        for p in sorted_pairs:
            ev_title = p.event.get("title", "(sense títol)")
            ev_time = _fmt_local_time(p.event["start"])
            rec_time = _fmt_local_time(p.recording.start_at) if p.recording.start_at else "?"
            rec_name = p.recording.name
            label = f"{ev_time} {ev_title}  ←→  {rec_time} {rec_name}  [{self._status_text(p)}]"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, p)  # objecte Pair (no índex)
            self.list_pairs.addItem(item)

    # ---------- Interaccions usuari ----------

    def _selected_event_index(self) -> Optional[int]:
        rows = self.table_cal.selectionModel().selectedRows() if self.table_cal.selectionModel() else []
        return rows[0].row() if rows else None

    def _selected_recording_index(self) -> Optional[int]:
        rows = self.table_plaud.selectionModel().selectedRows() if self.table_plaud.selectionModel() else []
        return rows[0].row() if rows else None

    def _selected_recording_indices(self) -> list[int]:
        rows = self.table_plaud.selectionModel().selectedRows() if self.table_plaud.selectionModel() else []
        return sorted(r.row() for r in rows)

    def _update_pair_btn(self):
        # Per aparellar manualment cal exactament 1 fila a cada taula (la
        # multi-selecció de Plaud serveix per marcar orfes, no per aparellar).
        cal_rows = self.table_cal.selectionModel().selectedRows() if self.table_cal.selectionModel() else []
        plaud_rows = self.table_plaud.selectionModel().selectedRows() if self.table_plaud.selectionModel() else []
        if len(cal_rows) != 1 or len(plaud_rows) != 1:
            self.btn_pair.setEnabled(False)
            return
        ev = self.events[cal_rows[0].row()]
        rec = self.recordings[plaud_rows[0].row()]
        used_ev = {id(p.event) for p in self.pairs}
        used_rec = {p.recording.file_id for p in self.pairs}
        self.btn_pair.setEnabled(id(ev) not in used_ev and rec.file_id not in used_rec)

    def _on_pair_list_selection(self):
        """Quan es selecciona un parell a la llista, ressalta les files a les taules (i viceversa)."""
        if self._syncing:
            return
        self._syncing = True
        item = self.list_pairs.currentItem()
        self.btn_unpair.setEnabled(item is not None)
        if item is None:
            self.table_cal.clearSelection()
            self.table_plaud.clearSelection()
        else:
            pair = item.data(Qt.ItemDataRole.UserRole)
            for row, ev in enumerate(self.events):
                if id(ev) == id(pair.event):
                    self.table_cal.selectRow(row)
                    break
            else:
                self.table_cal.clearSelection()
            for row, rec in enumerate(self.recordings):
                if rec.file_id == pair.recording.file_id:
                    self.table_plaud.selectRow(row)
                    break
            else:
                self.table_plaud.clearSelection()
        self._syncing = False
        self._update_pair_btn()

    def _on_table_selection(self):
        """Quan l'usuari selecciona directament una fila a les taules, neteja la selecció de la llista."""
        if self._syncing:
            return
        self._syncing = True
        self.list_pairs.clearSelection()
        self.btn_unpair.setEnabled(False)
        self._syncing = False
        self._update_pair_btn()

    def _pair_selected(self):
        ei = self._selected_event_index()
        ri = self._selected_recording_index()
        if ei is None or ri is None:
            return
        ev = self.events[ei]
        rec = self.recordings[ri]
        self.pairs.append(Pair(event=ev, recording=rec, score=1.0, status=PairStatus.MANUAL))
        self._refresh_tables()
        self._refresh_pairs_list()
        self._update_pair_btn()

    def _unpair_selected(self):
        item = self.list_pairs.currentItem()
        if item is None:
            return
        pair = item.data(Qt.ItemDataRole.UserRole)
        if pair in self.pairs:
            self.pairs.remove(pair)
            self._refresh_tables()
            self._refresh_pairs_list()
            self._update_pair_btn()

    # ---------- API pública ----------

    def get_state(self) -> tuple[list[Pair], list[dict[str, Any]], list[PlaudRecording]]:
        """Retorna (parells_confirmats, reunions_sense_aparellar, gravacions_sense_aparellar)."""
        used_ev = {id(p.event) for p in self.pairs}
        used_rec = {p.recording.file_id for p in self.pairs}
        unmatched_events = [e for e in self.events if id(e) not in used_ev]
        unmatched_recs = [r for r in self.recordings if r.file_id not in used_rec]
        return list(self.pairs), unmatched_events, unmatched_recs

    def get_selected_orphan_recordings(self) -> list[PlaudRecording]:
        """Gravacions seleccionades a la taula Plaud que NO formen part de cap parell.
        Permet a l'usuari incloure al flux gravacions sense reunió al calendari."""
        used_rec = {p.recording.file_id for p in self.pairs}
        return [
            self.recordings[i] for i in self._selected_recording_indices()
            if self.recordings[i].file_id not in used_rec
        ]
