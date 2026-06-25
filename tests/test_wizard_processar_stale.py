"""Tests del wizard Processar contra llistes de notes obsoletes.

Regressió: en re-processar un lot sense recarregar la llista, els Path
cachejats apunten a fitxers ~ ja renombrats (~ -> + / *) i petaven amb
FileNotFoundError ([Errno 2]). Verifiquem les dues defenses:
  1. _go_back recarrega la llista en tornar a la pàgina 0.
  2. _process_next omet (no peta) una nota el path de la qual ja no existeix.

Executar amb: uv run python -m unittest discover -s tests
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "gui"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
    _HAS_QT = True
except Exception:  # pragma: no cover - entorn sense Qt
    _HAS_QT = False


@unittest.skipUnless(_HAS_QT, "PySide6 no disponible")
class TestWizardProcessarStale(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _make_wizard(self, corrected_notes):
        from gui.wizard_processar import WizardProcessar, _BatchItem
        obsidian = MagicMock()
        obsidian.find_corrected_notes.return_value = corrected_notes
        calendar = MagicMock()
        wizard = WizardProcessar(calendar, obsidian)
        return wizard, obsidian, _BatchItem

    def test_process_next_skips_missing_note(self):
        # Una nota amb un path inexistent (renombrada en una passada anterior)
        # s'ha d'ometre, no fer petar el lot.
        wizard, obsidian, _BatchItem = self._make_wizard([])
        missing = Path("/no/existeix/260623_x~.md")
        wizard.batch_results = {0: _BatchItem(note={'path': missing,
                                                     'title': 'x', 'date': '260623'},
                                              option='Resum+ordre dia')}
        wizard._batch_queue = [0]
        wizard._batch_done_count = 0
        wizard.progress_batch.setRange(0, 1)

        wizard._process_next()

        self.assertEqual(wizard.batch_results[0].status, 'skipped')
        # No s'ha intentat llegir la transcripció del fitxer inexistent.
        obsidian.read_transcript.assert_not_called()

    def test_go_back_reloads_notes(self):
        # En tornar a la pàgina 0, la llista es refresca (descarta paths obsolets).
        stale = [{'path': Path("/v/Reunions/Seguiment/A/Reunions/260601_a~.md"),
                  'title': 'a', 'date': '260601'}]
        wizard, obsidian, _ = self._make_wizard(stale)
        self.assertEqual(len(wizard.notes), 1)

        # Simula que el lot ja s'ha processat: la nova càrrega retorna llista buida.
        obsidian.find_corrected_notes.return_value = []
        wizard.stack.setCurrentIndex(1)
        wizard.worker_processing = None

        wizard._go_back()

        self.assertEqual(wizard.stack.currentIndex(), 0)
        self.assertEqual(wizard.notes, [])
        self.assertGreaterEqual(obsidian.find_corrected_notes.call_count, 2)


if __name__ == "__main__":
    unittest.main()
