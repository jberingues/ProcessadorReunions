"""Tests per a ObsidianWriter.read_recent_year_blocks (referència de correcció).
    uv run python -m unittest discover -s tests
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from obsidian_writer import ObsidianWriter


class TestReadRecentYearBlocks(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.subfolder = self.tmp / "Reunions" / "Seguiment" / "A10Pro"
        (self.subfolder / "Reunions").mkdir(parents=True)
        self.writer = ObsidianWriter(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _note(self, stem: str) -> Path:
        p = self.subfolder / "Reunions" / f"{stem}.md"
        p.write_text("(transcripció)", encoding="utf-8")
        return p

    def _append(self, stem, date_label, title, content):
        return self.writer.append_to_year_note(
            self._note(stem), date_label, title, "", content
        )

    def test_none_when_no_year_file(self):
        note = self._note("260520_A10Pro")
        self.assertIsNone(self.writer.read_recent_year_blocks(note))

    def test_single_block(self):
        self._append("260520_A10Pro~", "260520", "Reunió 1", "contingut 1")
        ref = self.writer.read_recent_year_blocks(self._note("260605_A10Pro"))
        self.assertIn("## 260520 - Reunió 1", ref)
        self.assertIn("contingut 1", ref)

    def test_returns_last_two_of_three(self):
        self._append("260101_A10Pro~", "260101", "Reunió 1", "contingut 1")
        self._append("260201_A10Pro~", "260201", "Reunió 2", "contingut 2")
        self._append("260301_A10Pro~", "260301", "Reunió 3", "contingut 3")
        ref = self.writer.read_recent_year_blocks(self._note("260401_A10Pro"), n=2)
        self.assertNotIn("Reunió 1", ref)
        self.assertIn("## 260201 - Reunió 2", ref)
        self.assertIn("## 260301 - Reunió 3", ref)

    def test_blocks_separated_by_blank_line(self):
        self._append("260101_A10Pro~", "260101", "Reunió 1", "c1")
        self._append("260201_A10Pro~", "260201", "Reunió 2", "c2")
        ref = self.writer.read_recent_year_blocks(self._note("260301_A10Pro"))
        self.assertIn("\n\n## 260201", ref)

    def test_spans_multiple_year_files_chronologically(self):
        # 2025 (un bloc) + 2026 (dos blocs) → els 2 darrers són els de 2026
        self._append("251201_A10Pro~", "251201", "Reunió 2025", "antic")
        self._append("260115_A10Pro~", "260115", "Reunió A", "nou A")
        self._append("260215_A10Pro~", "260215", "Reunió B", "nou B")
        ref = self.writer.read_recent_year_blocks(self._note("260301_A10Pro"), n=2)
        self.assertNotIn("Reunió 2025", ref)
        self.assertIn("Reunió A", ref)
        self.assertIn("Reunió B", ref)

    def test_one_block_across_years_returns_it(self):
        # Només un bloc en total (a 2025) → es retorna encara que demanem 2
        self._append("251201_A10Pro~", "251201", "Única", "contingut")
        ref = self.writer.read_recent_year_blocks(self._note("260101_A10Pro"), n=2)
        self.assertIn("Única", ref)

    def test_ignores_other_md_files(self):
        # 'Resum projecte A10Pro.md' i 'Temes oberts.md' no s'han de comptar
        (self.subfolder / "Resum projecte A10Pro.md").write_text(
            "## fals bloc\nno", encoding="utf-8"
        )
        (self.subfolder / "Temes oberts.md").write_text(
            "## tema\nno", encoding="utf-8"
        )
        self._append("260101_A10Pro~", "260101", "Reunió real", "contingut")
        ref = self.writer.read_recent_year_blocks(self._note("260201_A10Pro"))
        self.assertIn("Reunió real", ref)
        self.assertNotIn("fals bloc", ref)
        self.assertNotIn("## tema", ref)

    def test_series_name_with_underscores(self):
        sub = self.tmp / "Reunions" / "Seguiment" / "Seguiment_Arnau_Prunell"
        (sub / "Reunions").mkdir(parents=True)
        note1 = sub / "Reunions" / "260101_x~.md"
        note1.write_text("x", encoding="utf-8")
        self.writer.append_to_year_note(note1, "260101", "R1", "", "c1")
        note2 = sub / "Reunions" / "260201_x.md"
        note2.write_text("x", encoding="utf-8")
        ref = self.writer.read_recent_year_blocks(note2)
        self.assertIn("R1", ref)


if __name__ == "__main__":
    unittest.main()
