"""Tests de scripts/migrate_year_frontmatter.py (migració one-shot).

Executar amb: uv run python -m unittest discover -s tests
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from migrate_year_frontmatter import find_year_notes, migrate


class TestMigrateYearFrontmatter(unittest.TestCase):
    def setUp(self):
        self.vault = Path(tempfile.mkdtemp())
        self.serie = self.vault / "Reunions" / "Seguiment" / "CRA"
        (self.serie / "Reunions").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.vault)

    def test_finds_year_note_matching_folder(self):
        (self.serie / "2026 CRA.md").write_text("## bloc\n", encoding="utf-8")
        found = find_year_notes(self.vault)
        self.assertEqual([(s, y) for _, s, y in found], [("CRA", 2026)])

    def test_folder_with_underscores(self):
        serie = self.vault / "Reunions" / "Proveïdors" / "EBV_Arrow"
        serie.mkdir(parents=True)
        (serie / "2025 EBV Arrow.md").write_text("## bloc\n", encoding="utf-8")
        found = find_year_notes(self.vault)
        self.assertEqual([(s, y) for _, s, y in found], [("EBV Arrow", 2025)])

    def test_ignores_non_matching_and_special(self):
        # Nom que no coincideix amb la carpeta → no és un anual.
        (self.serie / "2026 Altres.md").write_text("x", encoding="utf-8")
        # zConfig i plantilles x* se salten.
        z = self.vault / "Reunions" / "zConfig"
        z.mkdir(parents=True)
        (z / "2026 zConfig.md").write_text("x", encoding="utf-8")
        x = self.vault / "Reunions" / "Seguiment" / "xPlantilla"
        x.mkdir(parents=True)
        (x / "2026 xPlantilla.md").write_text("x", encoding="utf-8")
        self.assertEqual(find_year_notes(self.vault), [])

    def test_migrate_prepends_and_preserves_content(self):
        note = self.serie / "2026 CRA.md"
        note.write_text("## 260520 - Reunió\n\ncontingut validat\n", encoding="utf-8")
        migrated, skipped = migrate(self.vault, apply=True, log=lambda *_: None)
        self.assertEqual((migrated, skipped), (1, 0))
        content = note.read_text(encoding="utf-8")
        self.assertTrue(content.startswith("---\n"))
        self.assertIn("type: resum_anual", content)
        self.assertIn('serie: "CRA"', content)
        self.assertIn("any: 2026", content)
        self.assertIn("## 260520 - Reunió", content)
        self.assertIn("contingut validat", content)

    def test_migrate_is_idempotent(self):
        note = self.serie / "2026 CRA.md"
        note.write_text("## bloc\n", encoding="utf-8")
        migrate(self.vault, apply=True, log=lambda *_: None)
        first = note.read_text(encoding="utf-8")
        migrated, skipped = migrate(self.vault, apply=True, log=lambda *_: None)
        self.assertEqual((migrated, skipped), (0, 1))
        self.assertEqual(note.read_text(encoding="utf-8"), first)

    def test_dry_run_writes_nothing(self):
        note = self.serie / "2026 CRA.md"
        note.write_text("## bloc\n", encoding="utf-8")
        migrated, _ = migrate(self.vault, apply=False, log=lambda *_: None)
        self.assertEqual(migrated, 1)
        self.assertEqual(note.read_text(encoding="utf-8"), "## bloc\n")


if __name__ == "__main__":
    unittest.main()
