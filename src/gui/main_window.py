from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QPushButton, QLabel
from PySide6.QtCore import Qt
from calendar_matcher import CalendarMatcher
from obsidian_writer import ObsidianWriter
from wizard_transcripcio import WizardTranscripcio
from wizard_processar import WizardProcessar
from wizard_nou_projecte import WizardNouProjecte


class MainWindow(QMainWindow):
    def __init__(self, vault_path: str):
        super().__init__()
        self.setWindowTitle("Processador de Reunions")
        self.setMinimumSize(400, 300)

        self.calendar = CalendarMatcher()
        self.obsidian = ObsidianWriter(vault_path)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(16)

        title = QLabel("Processador de Reunions")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self.btn_transcripcions = QPushButton("Entrar transcripcions")
        self.btn_transcripcions.setMinimumHeight(50)
        self.btn_transcripcions.setStyleSheet("font-size: 14px;")
        self.btn_transcripcions.clicked.connect(self._open_transcripcions)
        layout.addWidget(self.btn_transcripcions)

        self.btn_processar = QPushButton("Processar reunions")
        self.btn_processar.setMinimumHeight(50)
        self.btn_processar.setStyleSheet("font-size: 14px;")
        self.btn_processar.clicked.connect(self._open_processar)
        layout.addWidget(self.btn_processar)

        self.btn_nou_projecte = QPushButton("Crear un projecte nou")
        self.btn_nou_projecte.setMinimumHeight(50)
        self.btn_nou_projecte.setStyleSheet("font-size: 14px;")
        self.btn_nou_projecte.clicked.connect(self._open_nou_projecte)
        layout.addWidget(self.btn_nou_projecte)

        self._all_buttons = [self.btn_transcripcions, self.btn_processar, self.btn_nou_projecte]

    def _open_transcripcions(self):
        self._disable_all()
        wizard = WizardTranscripcio(self.calendar, self.obsidian, self)
        wizard.finished.connect(self._wizard_closed)
        wizard.open()

    def _open_processar(self):
        self._disable_all()
        wizard = WizardProcessar(self.calendar, self.obsidian, self)
        wizard.finished.connect(self._wizard_closed)
        wizard.open()

    def _open_nou_projecte(self):
        self._disable_all()
        wizard = WizardNouProjecte(self.calendar, self.obsidian, self)
        wizard.finished.connect(self._wizard_closed)
        wizard.open()

    def _disable_all(self):
        for btn in self._all_buttons:
            btn.setEnabled(False)

    def _wizard_closed(self):
        for btn in self._all_buttons:
            btn.setEnabled(True)
