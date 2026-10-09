"""Tests del helper dels workers de Gmail que crea les notes principals de
projecte abans d'escanejar el vault (`_ensure_project_hubs`).

Executar amb: uv run python -m unittest discover -s tests
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "gui"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from obsidian_writer import ObsidianWriter
from workers import _ensure_project_hubs


class TestEnsureProjectHubsHelper(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "Reunions" / "Projectes" / "KAIMAI" / "Reunions").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_creates_and_logs(self):
        logs = []
        _ensure_project_hubs(ObsidianWriter(self.tmp), logs.append)
        self.assertTrue((self.tmp / "Reunions" / "Projectes" / "KAIMAI" / "KAIMAI.md").exists())
        self.assertEqual(logs, ["Creada la nota principal del projecte: KAIMAI.md"])

    def test_error_does_not_propagate(self):
        # Un error creant notes principals no ha d'aturar l'arxivat de correus.
        obsidian = MagicMock()
        obsidian.ensure_project_hubs.side_effect = OSError("Drive no disponible")
        logs = []
        with self.assertLogs("workers", level="ERROR"):
            _ensure_project_hubs(obsidian, logs.append)
        self.assertEqual(logs, [])


if __name__ == "__main__":
    unittest.main()
