"""Tests de la cel·la d'estat del Wizard Consolidar (mencions de projecte).
Executar amb: uv run python -m unittest discover -s tests
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "gui"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from wizard_consolidar import _result_cell


class TestResultCell(unittest.TestCase):
    def test_plain(self):
        cell = _result_cell({"year_written": True, "mentions": [], "mention_warnings": []})
        self.assertEqual(cell.text(), "Consolidada ✓")
        self.assertEqual(cell.toolTip(), "")

    def test_with_mentions(self):
        cell = _result_cell({"year_written": True, "mentions": ["A10Pro", "R4G"],
                             "mention_warnings": []})
        self.assertEqual(cell.text(), "Consolidada ✓ · mencions: A10Pro, R4G")

    def test_with_warnings_in_tooltip(self):
        cell = _result_cell({"year_written": True, "mentions": [],
                             "mention_warnings": ["Projecte inexistent: X"]})
        self.assertIn("⚠ avís mencions", cell.text())
        self.assertEqual(cell.toolTip(), "Projecte inexistent: X")

    def test_backward_compatible_result(self):
        cell = _result_cell({"year_written": False})
        self.assertEqual(cell.text(), "Consolidada (sense resum)")


if __name__ == "__main__":
    unittest.main()
