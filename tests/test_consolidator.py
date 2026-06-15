"""Tests de la consolidació (fase 2): propaga l'Ordre del dia validat a Temes
oberts + fitxer anual i marca la nota processada. Executar amb:
    uv run python -m unittest discover -s tests
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from obsidian_writer import ObsidianWriter
from consolidator import consolidate_pending_note
from meeting_analyzer import (
    MeetingAnalysisResult, ActiveTopicUpdate, format_ordre_del_dia,
)


class TestConsolidator(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.series = self.tmp / "Reunions" / "Seguiment" / "A10Pro"
        self.reunions = self.series / "Reunions"
        self.reunions.mkdir(parents=True)
        self.writer = ObsidianWriter(self.tmp)

        (self.series / "Temes oberts.md").write_text(
            "### Migració base de dades\n\n"
            "### API REST\n\n"
            "## Altres temes\n",
            encoding="utf-8",
        )

        result = MeetingAnalysisResult(
            updated_topics=[
                ActiveTopicUpdate(topic_name="Migració base de dades",
                                  summary="Decidida per al Q3."),
                ActiveTopicUpdate(topic_name="API REST",
                                  summary="Pendent autenticació."),
            ],
            new_other_topics=["Nou tema de seguretat"],
        )
        (self.series / "Ordre del dia propera reunió.md").write_text(
            format_ordre_del_dia(result, ["Migració base de dades", "API REST"], "20/05/2026"),
            encoding="utf-8",
        )

        self.note_path = self.reunions / "260520_Reunio_A10Pro+.md"
        self.note_path.write_text(
            "---\nattendees:\n  - \"[[Jordi Beringues]]\"\n  - \"Maria\"\n---\n"
            "## Transcripció\n\nblah\n",
            encoding="utf-8",
        )
        self.note = {"path": self.note_path, "date": "260520", "title": "Reunio A10Pro"}

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_marks_note_processed(self):
        res = consolidate_pending_note(self.writer, self.note)
        self.assertFalse(self.note_path.exists())
        self.assertEqual(res["note_path"].name, "260520_Reunio_A10Pro*.md")

    def test_temes_oberts_gets_dated_bullets(self):
        consolidate_pending_note(self.writer, self.note)
        temes = (self.series / "Temes oberts.md").read_text(encoding="utf-8")
        self.assertIn("- **260520:** Decidida per al Q3.", temes)
        self.assertIn("- **260520:** Pendent autenticació.", temes)
        # Tema nou a Altres temes:
        self.assertIn("- Nou tema de seguretat", temes)

    def test_year_note_created_with_block(self):
        res = consolidate_pending_note(self.writer, self.note)
        self.assertTrue(res["year_written"])
        year = (self.series / "2026 A10Pro.md").read_text(encoding="utf-8")
        self.assertIn("## 260520 - Reunio A10Pro", year)
        self.assertIn("Assistents: Jordi Beringues, Maria", year)
        self.assertIn("Decidida per al Q3.", year)
        self.assertIn("Pendent autenticació.", year)

    def test_user_edit_propagates(self):
        # L'usuari corregeix un error de transcripció a l'Ordre del dia.
        ordre = self.series / "Ordre del dia propera reunió.md"
        text = ordre.read_text(encoding="utf-8").replace(
            "Pendent autenticació.", "Pendent revisar OAuth2."
        )
        ordre.write_text(text, encoding="utf-8")
        consolidate_pending_note(self.writer, self.note)
        year = (self.series / "2026 A10Pro.md").read_text(encoding="utf-8")
        self.assertIn("Pendent revisar OAuth2.", year)
        self.assertNotIn("Pendent autenticació.", year)

    def test_missing_ordre_raises(self):
        (self.series / "Ordre del dia propera reunió.md").unlink()
        with self.assertRaises(FileNotFoundError):
            consolidate_pending_note(self.writer, self.note)

    def test_empty_result_no_year_note(self):
        # Ordre del dia sense cap tema tractat ni altres → no escriu anual.
        (self.series / "Ordre del dia propera reunió.md").write_text(
            "### Resum de la reunió anterior 20/05/2026\n\n"
            "Ordre del dia propera reunió:\n1) Migració base de dades\n",
            encoding="utf-8",
        )
        res = consolidate_pending_note(self.writer, self.note)
        self.assertFalse(res["year_written"])
        self.assertFalse((self.series / "2026 A10Pro.md").exists())
        # Tot i així, la nota es marca processada.
        self.assertEqual(res["note_path"].name, "260520_Reunio_A10Pro*.md")


if __name__ == "__main__":
    unittest.main()
