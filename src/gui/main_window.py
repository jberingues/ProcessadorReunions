import os

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QListWidget,
    QPushButton, QLabel, QMessageBox, QApplication, QAbstractItemView,
)
from PySide6.QtCore import Qt
from window_drag import install_window_drag
from calendar_matcher import CalendarMatcher
from obsidian_writer import ObsidianWriter
from plaud_client import PlaudClient
from wizard_transcripcio import WizardTranscripcio
from wizard_correccio import WizardCorreccio
from wizard_processar import WizardProcessar
from wizard_consolidar import WizardConsolidar
from wizard_processar_correus import WizardProcessarCorreus
from wizard_nou_projecte import WizardNouProjecte
from wizard_correus import WizardCorreus
from wizard_fitxers import WizardFitxers
from gmail_fetcher import GmailFetcher
from workers import GmailLabelSyncWorker


class MainWindow(QMainWindow):
    def __init__(self, vault_path: str):
        super().__init__()
        self.setWindowTitle("Processador de Reunions")
        self.setMinimumSize(900, 480)
        # Aprofita tota l'amplada de la pantalla; no cal gaire alçada perquè
        # mai hi ha més de ~10 reunions per columna.
        avail = QApplication.primaryScreen().availableGeometry()
        self.resize(avail.width(), 640)
        self.move(avail.left(), avail.top())
        install_window_drag(self)

        self.vault_path = vault_path
        self.calendar = CalendarMatcher()
        self.obsidian = ObsidianWriter(vault_path)
        self.gmail_fetcher = GmailFetcher(self.calendar.gmail)
        self.plaud_client = PlaudClient()
        self._label_sync_worker: GmailLabelSyncWorker | None = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(16)

        title = QLabel("Processador de Reunions")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # --- Tauler de fases: 3 columnes per estat del cicle de vida ---
        # Cada columna llista les notes en aquell estat (via els finders de
        # ObsidianWriter) i el botó del peu obre el wizard de la fase tal qual.
        board = QHBoxLayout()
        board.setSpacing(12)

        self.list_correccio = QListWidget()
        self.list_correccio.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.box_correccio = QGroupBox("Per corregir")
        col = QVBoxLayout(self.box_correccio)
        col.addWidget(self.list_correccio)
        self.btn_correccio = QPushButton("Corregir")
        self.btn_correccio.setMinimumHeight(40)
        self.btn_correccio.setToolTip("Selecciona una o més reunions a la llista")
        self.btn_correccio.clicked.connect(self._open_correccio)
        self.list_correccio.itemSelectionChanged.connect(self._update_action_buttons)
        col.addWidget(self.btn_correccio)
        board.addWidget(self.box_correccio)

        self.list_processar = QListWidget()
        self.list_processar.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.box_processar = QGroupBox("Per processar")
        col = QVBoxLayout(self.box_processar)
        col.addWidget(self.list_processar)
        self.btn_processar = QPushButton("Processar")
        self.btn_processar.setMinimumHeight(40)
        self.btn_processar.setToolTip("Selecciona una o més reunions a la llista")
        self.btn_processar.clicked.connect(self._open_processar)
        self.list_processar.itemSelectionChanged.connect(self._update_action_buttons)
        col.addWidget(self.btn_processar)
        board.addWidget(self.box_processar)

        self.list_consolidar = QListWidget()
        self.list_consolidar.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.box_consolidar = QGroupBox("Per consolidar")
        col = QVBoxLayout(self.box_consolidar)
        col.addWidget(self.list_consolidar)
        self.btn_consolidar = QPushButton("Consolidar")
        self.btn_consolidar.setMinimumHeight(40)
        self.btn_consolidar.setToolTip("Selecciona una o més reunions a la llista")
        self.btn_consolidar.clicked.connect(self._open_consolidar)
        self.list_consolidar.itemSelectionChanged.connect(self._update_action_buttons)
        col.addWidget(self.btn_consolidar)
        board.addWidget(self.box_consolidar)

        layout.addLayout(board, stretch=1)

        # --- Accions auxiliars (fora del cicle de fases) ---
        actions = QHBoxLayout()
        actions.setSpacing(8)

        self.btn_transcripcions = QPushButton("Entrar reunió nova")
        self.btn_transcripcions.clicked.connect(self._open_transcripcions)
        actions.addWidget(self.btn_transcripcions)

        self.btn_correus = QPushButton("Entrar correus")
        self.btn_correus.clicked.connect(self._open_correus)
        actions.addWidget(self.btn_correus)

        self.btn_sync_labels = QPushButton("Sincronitzar etiquetes Gmail")
        self.btn_sync_labels.clicked.connect(self._sync_gmail_labels)
        actions.addWidget(self.btn_sync_labels)

        self.btn_fitxers = QPushButton("Entrar fitxers")
        self.btn_fitxers.clicked.connect(self._open_fitxers)
        actions.addWidget(self.btn_fitxers)

        self.btn_processar_correus = QPushButton("Processar correus")
        self.btn_processar_correus.clicked.connect(self._open_processar_correus)
        actions.addWidget(self.btn_processar_correus)

        self.btn_nou_projecte = QPushButton("Crear un projecte nou")
        self.btn_nou_projecte.clicked.connect(self._open_nou_projecte)
        actions.addWidget(self.btn_nou_projecte)

        layout.addLayout(actions)

        self._all_buttons = [self.btn_transcripcions, self.btn_correus, self.btn_sync_labels, self.btn_fitxers, self.btn_correccio, self.btn_processar, self.btn_consolidar, self.btn_processar_correus, self.btn_nou_projecte]

        self._refresh_dashboard()

    def _open_transcripcions(self):
        self._disable_all()
        wizard = WizardTranscripcio(self.calendar, self.obsidian, self.plaud_client, self)
        wizard.finished.connect(self._wizard_closed)
        wizard.open()

    def _open_processar(self):
        notes = self._selected_notes(self.list_processar)
        if not notes:
            return
        self._disable_all()
        wizard = WizardProcessar(self.calendar, self.obsidian, self,
                                 preselected_paths={n['path'] for n in notes})
        wizard.finished.connect(self._wizard_closed)
        wizard.open()

    def _open_consolidar(self):
        notes = self._selected_notes(self.list_consolidar)
        if not notes:
            return
        self._disable_all()
        wizard = WizardConsolidar(self.obsidian, self,
                                  preselected_paths={n['path'] for n in notes})
        wizard.finished.connect(self._wizard_closed)
        wizard.open()

    def _open_nou_projecte(self):
        self._disable_all()
        wizard = WizardNouProjecte(self.calendar, self.obsidian, self)
        wizard.finished.connect(self._wizard_closed)
        wizard.open()

    def _open_correus(self):
        self._disable_all()
        wizard = WizardCorreus(self.gmail_fetcher, self.obsidian, self)
        wizard.finished.connect(self._wizard_closed)
        wizard.open()

    def _sync_gmail_labels(self):
        """Sincronitza les etiquetes vault → Gmail. Sense diàleg: el resultat
        es mostra com a QMessageBox en acabar. Ideal després de crear una
        sèrie nova al vault."""
        self._disable_all()
        include_sincro = os.environ.get("EMAIL_INCLUDE_SINCRO", "").lower() == "true"
        self._label_sync_worker = GmailLabelSyncWorker(
            self.gmail_fetcher, self.vault_path, include_sincro, self
        )
        self._label_sync_worker.finished.connect(self._on_label_sync_finished)
        self._label_sync_worker.error.connect(self._on_label_sync_error)
        self._label_sync_worker.start()

    def _on_label_sync_finished(self, result):
        self._wizard_closed()
        lines = []
        if result.created:
            lines.append(f"Creades a Gmail ({len(result.created)}):")
            lines.extend(f"  + {n}" for n in result.created)
        else:
            lines.append("Cap etiqueta nova: el vault i Gmail ja estan sincronitzats.")
        if result.failed:
            lines.append("")
            lines.append(f"Errors ({len(result.failed)}):")
            lines.extend(f"  ! {n}: {err}" for n, err in result.failed)
        if result.closed:
            lines.append("")
            lines.append(f"Etiquetes de sèries tancades ({len(result.closed)}) — esborrables manualment a Gmail:")
            lines.extend(f"  ~ {n}" for n in result.closed)
        if result.orphan:
            lines.append("")
            lines.append(f"Etiquetes a Gmail sense sèrie al vault ({len(result.orphan)}):")
            lines.extend(f"  ? {n}" for n in result.orphan)
        QMessageBox.information(self, "Sincronització d'etiquetes", "\n".join(lines))

    def _on_label_sync_error(self, msg: str):
        self._wizard_closed()
        QMessageBox.critical(self, "Error sincronitzant etiquetes", msg)

    def _open_fitxers(self):
        self._disable_all()
        wizard = WizardFitxers(self.obsidian, self)
        wizard.finished.connect(self._wizard_closed)
        wizard.open()

    def _open_processar_correus(self):
        self._disable_all()
        wizard = WizardProcessarCorreus(self.calendar, self.obsidian, self)
        wizard.finished.connect(self._wizard_closed)
        wizard.open()

    def _open_correccio(self):
        notes = self._selected_notes(self.list_correccio)
        if not notes:
            return
        self._disable_all()
        wizard = WizardCorreccio(self.obsidian, self,
                                 preselected_paths={n['path'] for n in notes})
        wizard.finished.connect(self._wizard_closed)
        wizard.open()

    def _refresh_dashboard(self):
        """Re-escaneja el vault i reomple les 3 columnes del tauler. Els finders
        de ObsidianWriter són escanejos de fitxers (sincrons i barats)."""
        self._fill_column(self.list_correccio, self.box_correccio, self.btn_correccio,
                          "Per corregir", self.obsidian.find_uncorrected_notes(), with_series=False)
        self._fill_column(self.list_processar, self.box_processar, self.btn_processar,
                          "Per processar", self.obsidian.find_corrected_notes(), with_series=True)
        self._fill_column(self.list_consolidar, self.box_consolidar, self.btn_consolidar,
                          "Per consolidar", self.obsidian.find_pending_consolidation_notes(), with_series=True)

    def _fill_column(self, list_widget, box, button, title, notes, with_series):
        list_widget.clear()
        # Les notes queden lligades a la llista per mapejar selecció → nota.
        list_widget.notes_data = notes
        for n in notes:
            label = f"{n['date']} — {n['title']}"
            if with_series:
                # sèrie = carpeta pare de Reunions/ (igual que wizard_consolidar)
                label += f"  ({n['path'].parent.parent.name})"
            list_widget.addItem(label)
        box.setTitle(f"{title} ({len(notes)})")
        # El botó s'habilita segons la selecció (vegeu _update_action_buttons),
        # no segons el nombre de notes: el tauler és l'únic punt de selecció.
        self._update_action_buttons()

    def _selected_notes(self, list_widget):
        """Retorna les notes seleccionades a la llista (dicts dels finders)."""
        notes = getattr(list_widget, 'notes_data', [])
        return [notes[i.row()] for i in list_widget.selectedIndexes()]

    def _update_action_buttons(self):
        self.btn_correccio.setEnabled(bool(self.list_correccio.selectedIndexes()))
        self.btn_processar.setEnabled(bool(self.list_processar.selectedIndexes()))
        self.btn_consolidar.setEnabled(bool(self.list_consolidar.selectedIndexes()))

    def _disable_all(self):
        for btn in self._all_buttons:
            btn.setEnabled(False)

    def _wizard_closed(self):
        for btn in self._all_buttons:
            btn.setEnabled(True)
        self._refresh_dashboard()
