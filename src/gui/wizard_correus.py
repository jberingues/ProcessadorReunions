"""Wizard d'arxivat de correus al vault d'Obsidian.

Flux:
 1. Pàgina 0 (Configuració): triar el dia final i quants dies enrere
    arxivar (finestra [dia_final - dies + 1, dia_final]), i confirmar.
 2. Pàgina 1 (Execució): worker que sync etiquetes + arxiva fils;
    log live + barra de progrés. Al final, resum amb llistes d'avisos.

Els fils ja arxivats sense missatges nous es salten via el store
d'idempotència (`zConfig/.processed_threads.json`), de manera que ampliar
la finestra no re-baixa res ja processat.

El flag `EMAIL_INCLUDE_SINCRO=true` al `.env` inclou les sèries de
`Reunions/Sincronització/` (per defecte excloses).
"""
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from window_drag import install_window_drag
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QStackedWidget, QWidget,
    QPushButton, QLabel, QProgressBar, QDateEdit, QPlainTextEdit,
    QMessageBox, QSpinBox,
)

from workers import EmailArchiveWorker

logger = logging.getLogger(__name__)


def _setup_file_log() -> Path:
    """Configura un FileHandler dedicat per a aquesta sessió d'arxivat."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    log_dir = repo_root / "data"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"email_archive_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    handler = logging.FileHandler(log_path, encoding='utf-8')
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    handler.set_name(f"email_archive_{log_path.stem}")
    root = logging.getLogger()
    root.addHandler(handler)
    return log_path


def _teardown_file_log(log_path: Path) -> None:
    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, 'name', '') == f"email_archive_{log_path.stem}":
            root.removeHandler(h)
            h.close()


class WizardCorreus(QDialog):
    def __init__(self, gmail_fetcher, obsidian, parent=None):
        super().__init__(parent)
        self.gmail_fetcher = gmail_fetcher
        self.obsidian = obsidian
        self.setWindowTitle("Arxivar correus")
        self.setMinimumSize(900, 600)
        install_window_drag(self)

        self.worker: EmailArchiveWorker | None = None
        self.log_path: Path | None = None
        self.include_sincro = os.getenv('EMAIL_INCLUDE_SINCRO', 'false').lower() == 'true'

        layout = QVBoxLayout(self)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        nav = QHBoxLayout()
        self.btn_back = QPushButton("Enrere")
        self.btn_back.clicked.connect(self._go_back)
        self.btn_next = QPushButton("Començar")
        self.btn_next.clicked.connect(self._go_next)
        self.btn_cancel = QPushButton("Cancel·lar")
        self.btn_cancel.clicked.connect(self._on_cancel)
        nav.addWidget(self.btn_back)
        nav.addStretch()
        nav.addWidget(self.btn_cancel)
        nav.addWidget(self.btn_next)
        layout.addLayout(nav)

        self._build_page0_config()
        self._build_page1_execution()
        self._update_nav()

    # -- Pàgina 0: Configuració --

    def _build_page0_config(self):
        page = QVBoxLayout()
        container = QWidget()
        container.setLayout(page)

        page.addWidget(QLabel(
            "<b>Arxivat de correus al vault</b><br><br>"
            "Aquest procés sincronitzarà les etiquetes Gmail amb les sèries del "
            "vault, llegirà els fils marcats amb etiquetes de vault i els desarà "
            "com a notes (amb adjunts) a la carpeta corresponent."
        ))
        page.addSpacing(20)

        date_row = QHBoxLayout()
        date_row.addWidget(QLabel("Arxivar fins al dia:"))
        self.date_day = QDateEdit()
        self.date_day.setCalendarPopup(True)
        self.date_day.setDate(QDate.currentDate())
        self.date_day.setDisplayFormat("dd/MM/yyyy")
        date_row.addWidget(self.date_day)
        date_row.addSpacing(20)
        date_row.addWidget(QLabel("Dies enrere:"))
        self.spin_days = QSpinBox()
        self.spin_days.setRange(1, 90)
        self.spin_days.setValue(7)
        date_row.addWidget(self.spin_days)
        date_row.addStretch()
        page.addLayout(date_row)
        page.addSpacing(6)
        page.addWidget(QLabel(
            "<i>Es processaran els fils amb missatges dins la finestra. "
            "Els fils ja arxivats sense canvis es salten automàticament.</i>"
        ))

        page.addSpacing(12)
        sincro_text = (
            "Sincronització: <b>inclosa</b> (EMAIL_INCLUDE_SINCRO=true)"
            if self.include_sincro else
            "Sincronització: <b>exclosa</b> (configura EMAIL_INCLUDE_SINCRO=true al .env per incloure-la)"
        )
        page.addWidget(QLabel(sincro_text))

        page.addStretch()
        self.stack.addWidget(container)

    # -- Pàgina 1: Execució --

    def _build_page1_execution(self):
        page = QVBoxLayout()
        container = QWidget()
        container.setLayout(page)

        self.lbl_status = QLabel("Esperant per començar...")
        page.addWidget(self.lbl_status)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        page.addWidget(self.progress)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("font-family: Menlo, monospace; font-size: 11px;")
        page.addWidget(self.log_view, stretch=1)

        self.summary_view = QPlainTextEdit()
        self.summary_view.setReadOnly(True)
        self.summary_view.setMaximumHeight(180)
        self.summary_view.setVisible(False)
        page.addWidget(self.summary_view)

        self.stack.addWidget(container)

    # -- Navegació --

    def _go_back(self):
        if self.stack.currentIndex() > 0 and self.worker is None:
            self.stack.setCurrentIndex(self.stack.currentIndex() - 1)
            self._update_nav()

    def _go_next(self):
        idx = self.stack.currentIndex()
        if idx == 0:
            self._start_archive()

    def _on_cancel(self):
        if self.worker is not None and self.worker.isRunning():
            ret = QMessageBox.question(
                self, "Aturar?",
                "S'està arxivant. Aturar el procés?\n"
                "Els fils ja arxivats no es desfaran.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ret == QMessageBox.StandardButton.Yes:
                self.worker.abort()
            return
        self.reject()

    def _update_nav(self):
        idx = self.stack.currentIndex()
        if idx == 0:
            self.btn_back.setEnabled(False)
            self.btn_next.setText("Començar")
            self.btn_next.setEnabled(True)
            self.btn_cancel.setText("Cancel·lar")
            self.btn_cancel.setVisible(True)
        elif idx == 1:
            self.btn_back.setEnabled(False)
            running = self.worker is not None and self.worker.isRunning()
            self.btn_next.setEnabled(not running)
            self.btn_next.setText("Tancar")
            if running:
                self.btn_cancel.setText("Aturar")
                self.btn_cancel.setVisible(True)
            else:
                # Quan ha acabat, només cal un botó: Tancar.
                self.btn_cancel.setVisible(False)
                try:
                    self.btn_next.clicked.disconnect()
                except (TypeError, RuntimeError):
                    pass
                self.btn_next.clicked.connect(self.accept)

    # -- Execució --

    def _start_archive(self):
        qd = self.date_day.date()
        end_day = date(qd.year(), qd.month(), qd.day())
        start_day = end_day - timedelta(days=self.spin_days.value() - 1)

        self.log_path = _setup_file_log()
        logger.info(
            "Iniciant arxivat: rang=%s..%s include_sincro=%s log=%s",
            start_day.isoformat(), end_day.isoformat(), self.include_sincro, self.log_path,
        )

        self.log_view.appendPlainText(f"Log: {self.log_path}")
        self.lbl_status.setText("Treballant...")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

        self.worker = EmailArchiveWorker(
            self.gmail_fetcher, self.obsidian,
            self.obsidian.vault, start_day, end_day, self.include_sincro,
            parent=self,
        )
        self.worker.log.connect(self._on_log)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()

        self.stack.setCurrentIndex(1)
        self._update_nav()

    def _on_log(self, msg: str):
        self.log_view.appendPlainText(msg)
        logger.info(msg)

    def _on_progress(self, done: int, total: int):
        if total == 0:
            self.progress.setRange(0, 1)
            self.progress.setValue(1)
            return
        self.progress.setRange(0, total)
        self.progress.setValue(done)

    def _on_finished(self, summary: dict):
        self.lbl_status.setText("Acabat.")
        self.summary_view.setVisible(True)
        self.summary_view.setPlainText(self._format_summary(summary))
        if self.log_path is not None:
            _teardown_file_log(self.log_path)
        self.worker = None
        self._update_nav()

    def _on_error(self, msg: str):
        self.lbl_status.setText("Error fatal.")
        QMessageBox.critical(self, "Error", msg)
        if self.log_path is not None:
            _teardown_file_log(self.log_path)
        self.worker = None
        self._update_nav()

    @staticmethod
    def _format_summary(s: dict) -> str:
        lines = ["=== RESUM ==="]
        lines.append(f"Fils arxivats:         {len(s['archived_threads'])}")
        lines.append(f"Saltats (sense canvi): {s['skipped_unchanged']}")
        lines.append(f"Saltats (no vault):    {s['skipped_no_vault_label']}")
        if s['sync_created_labels']:
            lines.append("")
            lines.append(f"Etiquetes creades a Gmail ({len(s['sync_created_labels'])}):")
            for l in s['sync_created_labels']:
                lines.append(f"  + {l}")
        if s['sync_closed_warnings']:
            lines.append("")
            lines.append(f"Avisos sèrie tancada ({len(s['sync_closed_warnings'])}):")
            for l in s['sync_closed_warnings']:
                lines.append(f"  ! {l} — esborra l'etiqueta a Gmail")
        if s['sync_orphan_labels']:
            lines.append("")
            lines.append(f"Etiquetes Gmail sense sèrie al vault ({len(s['sync_orphan_labels'])}):")
            for l in s['sync_orphan_labels']:
                lines.append(f"  ? {l}")
        if s['errors']:
            lines.append("")
            lines.append(f"Errors ({len(s['errors'])}):")
            for e in s['errors']:
                lines.append(f"  ✗ {e['thread_id']}: {e['msg']}")
        return "\n".join(lines)
