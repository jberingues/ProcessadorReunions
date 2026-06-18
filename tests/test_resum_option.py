"""Tests de l'opció 'Resum' (resum lliure de la reunió): genera un Ordre del
dia amb el marcador de tipus 'resum' i la fase 2 (Consolidar) el propaga NOMÉS
al fitxer anual, sense tocar Temes oberts. Executar amb:
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
    MeetingAnalysisResult, ActiveTopicUpdate,
    format_resum, parse_ordre_del_dia,
    with_pending_marker, strip_pending_marker, read_ordre_kind,
)


class TestFormatResum(unittest.TestCase):
    def _result(self):
        return MeetingAnalysisResult(
            updated_topics=[
                ActiveTopicUpdate(topic_name="Pressupost 2026", summary="Aprovat amb marge."),
                ActiveTopicUpdate(topic_name="Contractació", summary="Dos perfils oberts."),
            ],
            new_other_topics=[],
        )

    def test_no_agenda_section(self):
        text = format_resum(self._result(), "17/06/2026")
        self.assertIn("### Resum de la reunió 17/06/2026", text)
        # Un resum pur no porta agenda de propera reunió.
        self.assertNotIn("Ordre del dia propera reunió", text)

    def test_roundtrip_with_parse(self):
        text = format_resum(self._result(), "17/06/2026")
        parsed = parse_ordre_del_dia(text)
        self.assertEqual(
            [t.topic_name for t in parsed.updated_topics],
            ["Pressupost 2026", "Contractació"],
        )
        self.assertEqual(parsed.updated_topics[0].summary, "Aprovat amb marge.")


class TestOrdreKindMarker(unittest.TestCase):
    def _content(self):
        return format_resum(
            MeetingAnalysisResult(
                updated_topics=[ActiveTopicUpdate(topic_name="X", summary="y.")],
                new_other_topics=[],
            ),
            "17/06/2026",
        )

    def test_resum_marker_includes_kind(self):
        marked = with_pending_marker(self._content(), kind='resum')
        self.assertIn("pendent_revisio: true", marked)
        self.assertIn("tipus_consolidacio: resum", marked)
        self.assertEqual(read_ordre_kind(marked), 'resum')

    def test_seguiment_marker_omits_kind(self):
        # Compatibilitat: el seguiment no escriu la clau; es llegeix com a default.
        marked = with_pending_marker(self._content())
        self.assertNotIn("tipus_consolidacio", marked)
        self.assertEqual(read_ordre_kind(marked), 'seguiment')

    def test_read_kind_defaults_when_no_frontmatter(self):
        self.assertEqual(read_ordre_kind(self._content()), 'seguiment')

    def test_strip_removes_both_keys(self):
        marked = with_pending_marker(self._content(), kind='resum')
        stripped = strip_pending_marker(marked)
        self.assertNotIn("pendent_revisio", stripped)
        self.assertNotIn("tipus_consolidacio", stripped)
        self.assertEqual(stripped, self._content())

    def test_strip_preserves_user_frontmatter(self):
        text = (
            "---\npendent_revisio: true\ntipus_consolidacio: resum\n"
            "altrakey: valor\n---\n### cos\n"
        )
        stripped = strip_pending_marker(text)
        self.assertIn("altrakey: valor", stripped)
        self.assertNotIn("tipus_consolidacio", stripped)


class TestConsolidateResum(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        # Sèrie SENSE Temes oberts: el resum no en necessita.
        self.series = self.tmp / "Reunions" / "Reunions vàries" / "Comitè"
        self.reunions = self.series / "Reunions"
        self.reunions.mkdir(parents=True)
        self.writer = ObsidianWriter(self.tmp)

        result = MeetingAnalysisResult(
            updated_topics=[
                ActiveTopicUpdate(topic_name="Pressupost 2026", summary="Aprovat amb marge."),
            ],
            new_other_topics=[],
        )
        self.ordre = self.writer.ordre_del_dia_path(self.series)
        self.ordre.write_text(
            with_pending_marker(format_resum(result, "17/06/2026"), kind='resum'),
            encoding="utf-8",
        )

        self.note_path = self.reunions / "260617_Comitè+.md"
        self.note_path.write_text(
            "---\nattendees:\n  - \"[[Jordi Beringues]]\"\n---\n## Transcripció\n\nblah\n",
            encoding="utf-8",
        )
        self.note = {"path": self.note_path, "date": "260617", "title": "Comitè"}

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_year_note_written(self):
        res = consolidate_pending_note(self.writer, self.note)
        self.assertTrue(res["year_written"])
        year = (self.series / "2026 Comitè.md").read_text(encoding="utf-8")
        self.assertIn("## 260617 - Comitè", year)
        self.assertIn("Aprovat amb marge.", year)

    def test_temes_oberts_not_created(self):
        consolidate_pending_note(self.writer, self.note)
        self.assertFalse((self.series / "Temes oberts.md").exists())

    def test_existing_temes_oberts_untouched(self):
        temes = self.series / "Temes oberts.md"
        original = "### Un tema viu\n\n## Altres temes\n"
        temes.write_text(original, encoding="utf-8")
        consolidate_pending_note(self.writer, self.note)
        self.assertEqual(temes.read_text(encoding="utf-8"), original)

    def test_note_marked_processed(self):
        res = consolidate_pending_note(self.writer, self.note)
        self.assertEqual(res["note_path"].name, "260617_Comitè*.md")
        self.assertFalse(self.note_path.exists())

    def test_pending_marker_removed(self):
        consolidate_pending_note(self.writer, self.note)
        after = self.ordre.read_text(encoding="utf-8")
        self.assertNotIn("pendent_revisio", after)
        self.assertNotIn("tipus_consolidacio", after)
        self.assertIn("Resum de la reunió", after)


if __name__ == "__main__":
    unittest.main()
