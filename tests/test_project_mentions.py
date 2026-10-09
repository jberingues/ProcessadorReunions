"""Tests de les mencions de projecte (fase 2, decisió 2026-10).

En consolidar, cada tema etiquetat amb projectes afegeix una línia a la
secció '## Mencions des d'altres sèries' de la nota principal del projecte
(`Projectes/<X>/<X>.md`), amb link al bloc del fitxer anual.
Executar amb:
    uv run python -m unittest discover -s tests
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from obsidian_writer import ObsidianWriter, MENTIONS_HEADING
from consolidator import consolidate_pending_note
from meeting_analyzer import (
    ActiveTopicUpdate,
    MeetingAnalysisResult,
    build_project_mentions,
    format_ordre_del_dia,
    format_resum,
    with_pending_marker,
)

LINK = "[[2026 Reunió qualitat#261005 - Reunió Qualitat|Reunió qualitat]]"


def _mentions(result, exclude=()):
    return build_project_mentions(
        result, "261005", "Reunió qualitat", "2026 Reunió qualitat",
        "261005 - Reunió Qualitat", exclude=exclude,
    )


class TestBuildProjectMentions(unittest.TestCase):
    def test_one_line_per_project_with_conclusion(self):
        r = MeetingAnalysisResult(updated_topics=[
            ActiveTopicUpdate(topic_name="Substitució dels A7", summary="Llarg.",
                              conclusion="No hi ha reemplaçament fiable.",
                              projects=["A10Pro", "VDPJCM"]),
        ], new_other_topics=[])
        line = f"- **2026-10-05** · {LINK} · *Substitució dels A7*: No hi ha reemplaçament fiable."
        self.assertEqual(_mentions(r), {"A10Pro": [line], "VDPJCM": [line]})

    def test_falls_back_to_summary(self):
        r = MeetingAnalysisResult(updated_topics=[
            ActiveTopicUpdate(topic_name="T", summary="Resum\nen dues línies.", projects=["A10Pro"]),
        ], new_other_topics=[])
        self.assertTrue(_mentions(r)["A10Pro"][0].endswith("*T*: Resum en dues línies."))

    def test_topics_without_projects_ignored(self):
        r = MeetingAnalysisResult(updated_topics=[
            ActiveTopicUpdate(topic_name="T", summary="S"),
        ], new_other_topics=["Sense link"])
        self.assertEqual(_mentions(r), {})

    def test_other_topics_with_inline_links(self):
        r = MeetingAnalysisResult(updated_topics=[], new_other_topics=[
            "Cal revisar el certificat CE [[A10Pro]]",
        ])
        self.assertEqual(_mentions(r)["A10Pro"], [
            f"- **2026-10-05** · {LINK} · *Altres temes*: Cal revisar el certificat CE",
        ])

    def test_excluded_projects_skipped(self):
        r = MeetingAnalysisResult(updated_topics=[
            ActiveTopicUpdate(topic_name="T", summary="S", projects=["A10Pro", "R4G"]),
        ], new_other_topics=[])
        self.assertEqual(list(_mentions(r, exclude={"A10Pro"})), ["R4G"])

    def test_heading_sanitized_for_obsidian_links(self):
        r = MeetingAnalysisResult(updated_topics=[
            ActiveTopicUpdate(topic_name="T", summary="S", projects=["A10Pro"]),
        ], new_other_topics=[])
        out = build_project_mentions(r, "260904", "Reunió estratègia", "2026 Reunió estratègia",
                                     "260904 - R Estrategia a Vic[SM-544]")
        self.assertIn("[[2026 Reunió estratègia#260904 - R Estrategia a Vic SM-544|Reunió estratègia]]",
                      out["A10Pro"][0])

    def test_invalid_date_label_kept_as_is(self):
        r = MeetingAnalysisResult(updated_topics=[
            ActiveTopicUpdate(topic_name="T", summary="S", projects=["A10Pro"]),
        ], new_other_topics=[])
        out = build_project_mentions(r, "", "S", "2026 S", " - S")
        self.assertTrue(out["A10Pro"][0].startswith("- **?** · "))


class TestAppendProjectMentions(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.proj = self.tmp / "Reunions" / "Projectes" / "A10Pro"
        (self.proj / "Reunions").mkdir(parents=True)
        self.hub = self.proj / "A10Pro.md"
        self.writer = ObsidianWriter(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_creates_section_at_end(self):
        self.hub.write_text("---\ntype: hub\n---\n# A10Pro\n\n## Resum\nText.\n", encoding="utf-8")
        path = self.writer.append_project_mentions("A10Pro", ["- l1", "- l2"])
        self.assertEqual(path, self.hub)
        self.assertEqual(self.hub.read_text(encoding="utf-8"),
                         "---\ntype: hub\n---\n# A10Pro\n\n## Resum\nText.\n\n"
                         f"{MENTIONS_HEADING}\n- l1\n- l2\n")

    def test_appends_inside_existing_section_before_next_heading(self):
        self.hub.write_text(
            f"# A10Pro\n\n{MENTIONS_HEADING}\n- vella\n\n## Notes meves\nNo tocar.\n",
            encoding="utf-8")
        self.writer.append_project_mentions("A10Pro", ["- nova"])
        self.assertEqual(self.hub.read_text(encoding="utf-8"),
                         f"# A10Pro\n\n{MENTIONS_HEADING}\n- vella\n- nova\n\n## Notes meves\nNo tocar.\n")

    def test_idempotent(self):
        self.hub.write_text("# A10Pro\n", encoding="utf-8")
        self.writer.append_project_mentions("A10Pro", ["- l1"])
        self.writer.append_project_mentions("A10Pro", ["- l1", "- l2"])
        text = self.hub.read_text(encoding="utf-8")
        self.assertEqual(text.count("- l1"), 1)
        self.assertIn("- l2", text)

    def test_creates_hub_if_missing(self):
        self.writer.append_project_mentions("A10Pro", ["- l1"])
        text = self.hub.read_text(encoding="utf-8")
        self.assertIn("type: hub", text)
        self.assertTrue(text.rstrip().endswith(f"{MENTIONS_HEADING}\n- l1"))

    def test_nested_project(self):
        sub = self.proj / "Sub"
        (sub / "Reunions").mkdir(parents=True)
        self.assertEqual(self.writer.append_project_mentions("Sub", ["- l1"]), sub / "Sub.md")

    def test_unknown_project_returns_none(self):
        self.assertIsNone(self.writer.append_project_mentions("Inventat", ["- l1"]))

    def test_project_series_dir(self):
        self.assertEqual(self.writer.project_series_dir("A10Pro"), self.proj)
        self.assertIsNone(self.writer.project_series_dir("Inventat"))


class TestConsolidatorMentions(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        r = self.tmp / "Reunions"
        self.a10 = r / "Projectes" / "A10Pro"
        (self.a10 / "Reunions").mkdir(parents=True)
        (self.a10 / "A10Pro.md").write_text("# A10Pro\n\n## Resum\nX\n", encoding="utf-8")
        self.series = r / "Reunions vàries" / "Reunió qualitat"
        (self.series / "Reunions").mkdir(parents=True)
        (self.series / "Temes oberts.md").write_text("### Substitució\n\n## Altres temes\n",
                                                     encoding="utf-8")
        self.writer = ObsidianWriter(self.tmp)
        self.result = MeetingAnalysisResult(updated_topics=[
            ActiveTopicUpdate(topic_name="Substitució", summary="S.", conclusion="C.",
                              projects=["A10Pro"]),
            ActiveTopicUpdate(topic_name="Bulgària", summary="B."),
        ], new_other_topics=[])

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _note(self, series, ordre_text):
        self.writer.ordre_del_dia_path(series).write_text(ordre_text, encoding="utf-8")
        p = series / "Reunions" / "261005_Reunió_Qualitat+.md"
        p.write_text("---\nassistents: []\n---\n", encoding="utf-8")
        return {"path": p, "date": "261005", "title": "Reunió Qualitat"}

    def test_seguiment_writes_mentions(self):
        text = with_pending_marker(format_ordre_del_dia(self.result, ["Substitució"], "05/10/2026"))
        res = consolidate_pending_note(self.writer, self._note(self.series, text))
        hub = (self.a10 / "A10Pro.md").read_text(encoding="utf-8")
        self.assertIn(MENTIONS_HEADING, hub)
        self.assertIn("- **2026-10-05** · [[2026 Reunió qualitat#261005 - Reunió Qualitat|Reunió qualitat]]"
                      " · *Substitució*: C.", hub)
        self.assertNotIn("Bulgària", hub)
        self.assertEqual(res["mentions"], ["A10Pro"])
        self.assertEqual(res["mention_warnings"], [])
        # L'anual conserva el link del tema.
        year = (self.series / "2026 Reunió qualitat.md").read_text(encoding="utf-8")
        self.assertIn("- **Projectes:** [[A10Pro]]", year)

    def test_resum_writes_mentions(self):
        text = with_pending_marker(format_resum(self.result, "05/10/2026"), kind="resum")
        res = consolidate_pending_note(self.writer, self._note(self.series, text))
        self.assertEqual(res["mentions"], ["A10Pro"])
        self.assertIn("*Substitució*: C.", (self.a10 / "A10Pro.md").read_text(encoding="utf-8"))

    def test_own_project_series_skipped(self):
        (self.a10 / "Temes oberts.md").write_text("### Substitució\n\n## Altres temes\n",
                                                  encoding="utf-8")
        text = with_pending_marker(format_ordre_del_dia(self.result, ["Substitució"], "05/10/2026"))
        res = consolidate_pending_note(self.writer, self._note(self.a10, text))
        self.assertEqual(res["mentions"], [])
        self.assertNotIn(MENTIONS_HEADING, (self.a10 / "A10Pro.md").read_text(encoding="utf-8"))

    def test_unknown_project_is_warning_not_error(self):
        self.result.updated_topics[0].projects = ["Inventat"]
        text = with_pending_marker(format_ordre_del_dia(self.result, ["Substitució"], "05/10/2026"))
        note = self._note(self.series, text)
        res = consolidate_pending_note(self.writer, note)
        self.assertEqual(res["mentions"], [])
        self.assertEqual(len(res["mention_warnings"]), 1)
        self.assertIn("Inventat", res["mention_warnings"][0])
        self.assertTrue(res["note_path"].name.endswith("*.md"))

    def test_write_failure_does_not_block_consolidation(self):
        text = with_pending_marker(format_ordre_del_dia(self.result, ["Substitució"], "05/10/2026"))
        note = self._note(self.series, text)
        with patch.object(ObsidianWriter, "append_project_mentions", side_effect=OSError("Drive")), \
                self.assertLogs("consolidator", level="ERROR"):
            res = consolidate_pending_note(self.writer, note)
        self.assertTrue(res["note_path"].name.endswith("*.md"))
        self.assertEqual(res["mentions"], [])
        self.assertIn("Drive", res["mention_warnings"][0])


if __name__ == "__main__":
    unittest.main()
