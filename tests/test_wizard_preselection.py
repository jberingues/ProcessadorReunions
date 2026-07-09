"""Tests de la preselecció des del tauler (main_window → wizards).

El tauler de fases és l'únic punt de selecció: en obrir un wizard des d'un botó,
se li passa `preselected_paths` amb les notes triades. El wizard ha de:
  1. Filtrar la seva llista a NOMÉS aquestes notes.
  2. Preseleccionar-les totes (l'usuari només confirma / ajusta config).

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


def _note(path_str, date, title):
    return {'path': Path(path_str), 'date': date, 'title': title}


@unittest.skipUnless(_HAS_QT, "PySide6 no disponible")
class TestWizardPreselection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _three_notes(self):
        base = "/v/Reunions/Seguiment/A/Reunions"
        return [
            _note(f"{base}/260601_a~.md", '260601', 'a'),
            _note(f"{base}/260602_b~.md", '260602', 'b'),
            _note(f"{base}/260603_c~.md", '260603', 'c'),
        ]

    def test_processar_filters_and_selects_preselected(self):
        from gui.wizard_processar import WizardProcessar
        notes = self._three_notes()
        obsidian = MagicMock()
        obsidian.find_corrected_notes.return_value = notes
        chosen = {notes[0]['path'], notes[2]['path']}

        wizard = WizardProcessar(MagicMock(), obsidian, preselected_paths=chosen)

        self.assertEqual({n['path'] for n in wizard.notes}, chosen)
        self.assertEqual(len(wizard.notes), 2)
        selected = {r.row() for r in wizard.table_notes.selectionModel().selectedRows()}
        self.assertEqual(selected, {0, 1})

    def test_correccio_filters_and_selects_preselected(self):
        from gui.wizard_correccio import WizardCorreccio
        notes = self._three_notes()
        obsidian = MagicMock()
        obsidian.find_uncorrected_notes.return_value = notes
        chosen = {notes[1]['path']}

        wizard = WizardCorreccio(obsidian, preselected_paths=chosen)

        self.assertEqual({n['path'] for n in wizard.notes}, chosen)
        selected = {r.row() for r in wizard.table_notes.selectionModel().selectedRows()}
        self.assertEqual(selected, {0})

    def test_consolidar_filters_and_selects_preselected(self):
        from gui.wizard_consolidar import WizardConsolidar
        # find_pending_consolidation_notes retorna notes '+' amb l'estructura
        # habitual (path a .../Reunions/<fitxer>+.md).
        base = "/v/Reunions/Seguiment/A/Reunions"
        notes = [
            _note(f"{base}/260601_a+.md", '260601', 'a'),
            _note(f"{base}/260602_b+.md", '260602', 'b'),
        ]
        obsidian = MagicMock()
        obsidian.find_pending_consolidation_notes.return_value = notes
        chosen = {notes[0]['path']}

        wizard = WizardConsolidar(obsidian, preselected_paths=chosen)

        self.assertEqual({n['path'] for n in wizard.notes}, chosen)
        selected = {r.row() for r in wizard.table.selectionModel().selectedRows()}
        self.assertEqual(selected, {0})

    def test_no_preselection_shows_all(self):
        # Sense preselecció (comportament clàssic): es mostren totes les notes i
        # cap no queda preseleccionada.
        from gui.wizard_processar import WizardProcessar
        notes = self._three_notes()
        obsidian = MagicMock()
        obsidian.find_corrected_notes.return_value = notes

        wizard = WizardProcessar(MagicMock(), obsidian)

        self.assertEqual(len(wizard.notes), 3)
        self.assertEqual(wizard.table_notes.selectionModel().selectedRows(), [])


if __name__ == "__main__":
    unittest.main()
