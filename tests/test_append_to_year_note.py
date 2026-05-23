"""Tests unitaris per a ObsidianWriter.append_to_year_note. Executar amb:
    uv run python -m unittest discover -s tests
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from obsidian_writer import ObsidianWriter


class TestAppendToYearNote(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        # Estructura mínima d'un vault: vault/Reunions/Seguiment/A10Pro/Reunions/
        self.subfolder = self.tmp / "Reunions" / "Seguiment" / "A10Pro"
        (self.subfolder / "Reunions").mkdir(parents=True)
        self.note = self.subfolder / "Reunions" / "260520_A10Pro~.md"
        self.note.write_text("(transcripció)", encoding="utf-8")
        self.writer = ObsidianWriter(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_creates_file_if_missing(self):
        out = self.writer.append_to_year_note(
            self.note,
            date_label="260520",
            title="A10Pro",
            attendees="Jordi, Marc",
            content_block="##### Tema 1\n- punt",
        )
        self.assertTrue(out.exists())
        self.assertEqual(out.name, "2026 A10Pro.md")
        content = out.read_text(encoding="utf-8")
        self.assertIn("## 260520 - A10Pro", content)
        self.assertIn("Assistents: Jordi, Marc", content)
        self.assertIn("##### Tema 1", content)

    def test_appends_to_existing(self):
        self.writer.append_to_year_note(
            self.note, "260520", "Reunió 1", "Jordi", "primer contingut"
        )
        note2 = self.subfolder / "Reunions" / "260605_A10Pro~.md"
        note2.write_text("(transcripció 2)", encoding="utf-8")
        out = self.writer.append_to_year_note(
            note2, "260605", "Reunió 2", "Jordi", "segon contingut"
        )
        content = out.read_text(encoding="utf-8")
        self.assertIn("## 260520 - Reunió 1", content)
        self.assertIn("## 260605 - Reunió 2", content)
        self.assertIn("primer contingut", content)
        self.assertIn("segon contingut", content)
        # Hi ha d'haver separador en blanc entre blocs
        self.assertIn("\n\n## 260605", content)

    def test_year_derived_from_filename(self):
        note25 = self.subfolder / "Reunions" / "251205_A10Pro~.md"
        note25.write_text("x", encoding="utf-8")
        out = self.writer.append_to_year_note(
            note25, "251205", "X", "", "contingut"
        )
        self.assertEqual(out.name, "2025 A10Pro.md")

    def test_series_name_with_underscores(self):
        sub = self.tmp / "Reunions" / "Seguiment" / "Seguiment_Arnau_Prunell"
        (sub / "Reunions").mkdir(parents=True)
        note = sub / "Reunions" / "260520_x~.md"
        note.write_text("x", encoding="utf-8")
        out = self.writer.append_to_year_note(
            note, "260520", "X", "", "contingut"
        )
        self.assertEqual(out.name, "2026 Seguiment Arnau Prunell.md")

    def test_series_name_with_brackets(self):
        sub = self.tmp / "Reunions" / "Sincronització" / "Sincronització_G1_[VARISONE-473]"
        (sub / "Reunions").mkdir(parents=True)
        note = sub / "Reunions" / "260520_x~.md"
        note.write_text("x", encoding="utf-8")
        out = self.writer.append_to_year_note(
            note, "260520", "Daily", "", "contingut"
        )
        self.assertEqual(out.name, "2026 Sincronització G1 VARISONE-473.md")

    def test_no_attendees_line_when_empty(self):
        out = self.writer.append_to_year_note(
            self.note, "260520", "X", "", "contingut"
        )
        content = out.read_text(encoding="utf-8")
        self.assertNotIn("Assistents:", content)

    def test_returns_path(self):
        out = self.writer.append_to_year_note(
            self.note, "260520", "X", "", "contingut"
        )
        self.assertIsInstance(out, Path)
        self.assertEqual(out.parent, self.subfolder)


if __name__ == "__main__":
    unittest.main()
