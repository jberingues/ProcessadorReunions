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
    OPTION_RESUM,
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

    def test_proveidors_path_returns_resum(self):
        p = Path("/v/Reunions/Proveïdors/CELO/Reunions/260520_x.md")
        self.assertEqual(_default_option_for_path(p), OPTION_RESUM)

    def test_projectes_path_returns_resum(self):
        p = Path("/v/Reunions/Projectes/EUROTRACK/Reunions/260520_x.md")
        self.assertEqual(_default_option_for_path(p), OPTION_RESUM)

    def test_reunions_varies_path_returns_resum(self):
        p = Path("/v/Reunions/Reunions vàries/Noves incorporacions/Reunions/260520_x.md")
        self.assertEqual(_default_option_for_path(p), OPTION_RESUM)

    def test_sincronitzacio_wins_when_both_in_path_unlikely(self):
        # Cas defensiu: si per error una nota té 'Sincronització' al path,
        # encara que també tingui 'Seguiment' (no hauria de passar), Sincro guanya.
        p = Path("/v/Reunions/Sincronització/Seguiment_X/Reunions/x.md")
        self.assertEqual(_default_option_for_path(p), OPTION_SINCRO)


if __name__ == "__main__":
    unittest.main()
