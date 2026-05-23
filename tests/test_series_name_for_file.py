"""Tests unitaris per a series_name_for_file. Executar amb:
    uv run python -m unittest discover -s tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from obsidian_writer import series_name_for_file


class TestSeriesNameForFile(unittest.TestCase):
    def test_no_change_when_no_special_chars(self):
        self.assertEqual(series_name_for_file("A10Pro"), "A10Pro")
        self.assertEqual(series_name_for_file("CELO"), "CELO")

    def test_underscores_become_spaces(self):
        self.assertEqual(
            series_name_for_file("Seguiment_Arnau_Prunell"),
            "Seguiment Arnau Prunell",
        )

    def test_brackets_are_stripped(self):
        self.assertEqual(
            series_name_for_file("Sincronització_G1_[VARISONE-473]"),
            "Sincronització G1 VARISONE-473",
        )

    def test_mixed_separators(self):
        # Hyphen es manté, underscores es converteixen
        self.assertEqual(
            series_name_for_file("VARISG8-4_G8_Sincronització"),
            "VARISG8-4 G8 Sincronització",
        )

    def test_empty_string(self):
        self.assertEqual(series_name_for_file(""), "")


if __name__ == "__main__":
    unittest.main()
