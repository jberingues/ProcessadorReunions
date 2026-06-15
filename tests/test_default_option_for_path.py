"""Tests unitaris per a _default_option_for_path. Executar amb:
    uv run python -m unittest discover -s tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "gui"))

from gui.wizard_processar import (  # noqa: E402
    _default_option_for_path,
    _sort_notes_by_date,
    OPTION_RESUM_ORDRE,
    OPTION_SINCRO,
)


class TestDefaultOptionForPath(unittest.TestCase):
    def test_sincronitzacio_path_returns_sincro(self):
        p = Path("/v/Reunions/Sincronització/Sincronització_OT/Reunions/260520_x.md")
        self.assertEqual(_default_option_for_path(p), OPTION_SINCRO)

    def test_seguiment_path_returns_resum_ordre(self):
        p = Path("/v/Reunions/Seguiment/A10Pro/Reunions/260520_x.md")
        self.assertEqual(_default_option_for_path(p), OPTION_RESUM_ORDRE)

    def test_proveidors_path_returns_resum_ordre(self):
        # Unificat: tot el que no és sincronització rep el tractament complet.
        p = Path("/v/Reunions/Proveïdors/CELO/Reunions/260520_x.md")
        self.assertEqual(_default_option_for_path(p), OPTION_RESUM_ORDRE)

    def test_projectes_path_returns_resum_ordre(self):
        p = Path("/v/Reunions/Projectes/EUROTRACK/Reunions/260520_x.md")
        self.assertEqual(_default_option_for_path(p), OPTION_RESUM_ORDRE)

    def test_reunions_varies_path_returns_resum_ordre(self):
        p = Path("/v/Reunions/Reunions vàries/Noves incorporacions/Reunions/260520_x.md")
        self.assertEqual(_default_option_for_path(p), OPTION_RESUM_ORDRE)

    def test_sincronitzacio_wins_when_both_in_path_unlikely(self):
        # Cas defensiu: si per error una nota té 'Sincronització' al path,
        # encara que també tingui 'Seguiment' (no hauria de passar), Sincro guanya.
        p = Path("/v/Reunions/Sincronització/Seguiment_X/Reunions/x.md")
        self.assertEqual(_default_option_for_path(p), OPTION_SINCRO)


class TestSortNotesByDate(unittest.TestCase):
    def test_sorts_ascending_by_date(self):
        pairs = [
            ({'date': '260520', 'title': 'a'}, 'Resum'),
            ({'date': '260408', 'title': 'b'}, 'Sincro'),
            ({'date': '260409', 'title': 'c'}, 'Resum+ordre dia'),
        ]
        result = _sort_notes_by_date(pairs)
        self.assertEqual([p[0]['date'] for p in result], ['260408', '260409', '260520'])

    def test_preserves_option_association(self):
        pairs = [
            ({'date': '260520', 'title': 'a'}, 'OPT-A'),
            ({'date': '260408', 'title': 'b'}, 'OPT-B'),
        ]
        result = _sort_notes_by_date(pairs)
        self.assertEqual(result[0][1], 'OPT-B')  # 260408 → OPT-B
        self.assertEqual(result[1][1], 'OPT-A')  # 260520 → OPT-A

    def test_across_years(self):
        # 25xxxx < 26xxxx lexicogràficament == cronològicament
        pairs = [
            ({'date': '260101', 'title': 'a'}, 'x'),
            ({'date': '251231', 'title': 'b'}, 'x'),
        ]
        result = _sort_notes_by_date(pairs)
        self.assertEqual([p[0]['date'] for p in result], ['251231', '260101'])

    def test_empty_list(self):
        self.assertEqual(_sort_notes_by_date([]), [])


if __name__ == "__main__":
    unittest.main()
