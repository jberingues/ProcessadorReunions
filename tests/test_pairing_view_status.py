"""Tests de l'estat que mostra el PairingView en carregar.

Regressió (2026-08-19): quan el CLI de Plaud tenia el token caducat,
`_on_plaud_not_auth` escrivia l'avís al `status_label` però `_maybe_finalize`
el trepitjava tot seguit amb "N reunions · 0 gravacions · 0 parells". L'usuari
veia la columna de Plaud buida sense cap pista que calia `plaud login`.

Executar amb: uv run python -m unittest discover -s tests
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "gui"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
    from widgets import pairing_view as pv
    _HAS_QT = True
except Exception:  # pragma: no cover - entorn sense Qt
    _HAS_QT = False


@unittest.skipUnless(_HAS_QT, "PySide6 no disponible")
class TestPairingViewStatus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _view(self):
        return pv.PairingView(MagicMock(), MagicMock())

    def _event_today(self, view):
        """Event dins del dia seleccionat al date_edit (passa el filtre)."""
        qd = view.date_edit.date()
        start = datetime(qd.year(), qd.month(), qd.day(), 10, 0).astimezone()
        return {"title": "Reunió", "start": start, "end": start + timedelta(hours=1),
                "attendees": []}

    def test_avis_not_auth_sobreviu_al_recompte(self):
        v = self._view()
        v._on_plaud_not_auth()
        v._on_cal_loaded([self._event_today(v)])

        text = v.status_label.text()
        self.assertIn("plaud login", text)
        self.assertIn("1 reunions · 0 gravacions", text)

    def test_avis_error_plaud_sobreviu_al_recompte(self):
        v = self._view()
        v._on_plaud_error("boom")
        v._on_cal_loaded([])

        text = v.status_label.text()
        self.assertIn("Error Plaud: boom", text)
        self.assertIn("0 gravacions", text)

    def test_avis_error_calendari_sobreviu_al_recompte(self):
        v = self._view()
        v._on_cal_error("quota")
        v._on_plaud_loaded([])

        text = v.status_label.text()
        self.assertIn("Error calendari: quota", text)
        self.assertIn("0 reunions", text)

    def test_carrega_correcta_nomes_mostra_recompte(self):
        v = self._view()
        v._on_plaud_loaded([])
        v._on_cal_loaded([self._event_today(v)])

        self.assertEqual(
            v.status_label.text(),
            "1 reunions · 0 gravacions · 0 parells (auto/suggerit)",
        )

    def test_load_neteja_avisos_previs(self):
        v = self._view()
        v._on_plaud_not_auth()

        with patch.object(pv, "CalendarWorker"), patch.object(pv, "PlaudListWorker"):
            v.load()

        self.assertEqual(v._load_warnings, [])
        self.assertNotIn("plaud login", v.status_label.text())


if __name__ == "__main__":
    unittest.main()
