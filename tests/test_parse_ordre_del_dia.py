"""Tests per a parse_ordre_del_dia (invers de format_ordre_del_dia), usat a la
fase 2 (Consolidar) per propagar l'Ordre del dia validat a Temes oberts + anual.
Executar amb:
    uv run python -m unittest discover -s tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from meeting_analyzer import (
    MeetingAnalysisResult,
    ActiveTopicUpdate,
    format_ordre_del_dia,
    parse_ordre_del_dia,
    with_pending_marker,
    strip_pending_marker,
)


class TestParseOrdreDelDia(unittest.TestCase):
    def _result(self, updated, others):
        return MeetingAnalysisResult(
            updated_topics=[ActiveTopicUpdate(topic_name=n, summary=s) for n, s in updated],
            new_other_topics=others,
        )

    def assertResultEqual(self, a: MeetingAnalysisResult, b: MeetingAnalysisResult):
        self.assertEqual(
            [(t.topic_name, t.summary) for t in a.updated_topics],
            [(t.topic_name, t.summary) for t in b.updated_topics],
        )
        self.assertEqual(a.new_other_topics, b.new_other_topics)

    # -- Round-trips: format → parse == original --

    def test_roundtrip_full(self):
        result = self._result(
            [("Migració base de dades", "S'ha decidit fer-la al Q3."),
             ("API REST", "Pendent revisar autenticació.")],
            ["Nou tema de seguretat", "Proposta de calendari"],
        )
        text = format_ordre_del_dia(result, ["Migració base de dades", "API REST"], "15/06/2026")
        self.assertResultEqual(parse_ordre_del_dia(text), result)

    def test_roundtrip_no_other_topics(self):
        result = self._result([("Tema A", "Resum A.")], [])
        text = format_ordre_del_dia(result, ["Tema A"], "01/01/2026")
        self.assertResultEqual(parse_ordre_del_dia(text), result)

    def test_roundtrip_empty_topics_only_others(self):
        # Cas Temes oberts buit: tot va a Altres temes, agenda buida.
        result = self._result([], ["Tema nou 1", "Tema nou 2"])
        text = format_ordre_del_dia(result, [], "10/03/2026")
        self.assertResultEqual(parse_ordre_del_dia(text), result)

    def test_roundtrip_empty(self):
        result = self._result([], [])
        text = format_ordre_del_dia(result, [], "10/03/2026")
        parsed = parse_ordre_del_dia(text)
        self.assertEqual(parsed.updated_topics, [])
        self.assertEqual(parsed.new_other_topics, [])

    # -- L'agenda final s'ignora --

    def test_ignores_agenda_list(self):
        result = self._result([("Tema A", "Resum.")], [])
        # all_topics té temes que NO surten a updated_topics; no han d'aparèixer.
        text = format_ordre_del_dia(result, ["Tema A", "Tema B", "Tema C"], "01/01/2026")
        parsed = parse_ordre_del_dia(text)
        self.assertEqual([t.topic_name for t in parsed.updated_topics], ["Tema A"])

    # -- Edicions manuals de l'usuari --

    def test_edited_summary_text_propagates(self):
        result = self._result([("Tema A", "Resum original amb error.")], [])
        text = format_ordre_del_dia(result, ["Tema A"], "01/01/2026")
        edited = text.replace("Resum original amb error.", "Resum corregit per l'usuari.")
        parsed = parse_ordre_del_dia(edited)
        self.assertEqual(parsed.updated_topics[0].summary, "Resum corregit per l'usuari.")

    def test_multiline_summary_joined(self):
        text = (
            "### Resum de la reunió anterior 01/01/2026\n\n"
            "#### *1) Tema A*\n"
            "* Primera línia.\n"
            "* Segona línia afegida a mà.\n\n"
            "Ordre del dia propera reunió:\n"
            "1) Tema A\n"
        )
        parsed = parse_ordre_del_dia(text)
        self.assertEqual(len(parsed.updated_topics), 1)
        self.assertEqual(
            parsed.updated_topics[0].summary,
            "Primera línia. Segona línia afegida a mà.",
        )

    def test_topic_name_with_parenthesis(self):
        result = self._result([("Tema (v2)", "Resum.")], [])
        text = format_ordre_del_dia(result, ["Tema (v2)"], "01/01/2026")
        parsed = parse_ordre_del_dia(text)
        self.assertEqual(parsed.updated_topics[0].topic_name, "Tema (v2)")


class TestPendingMarker(unittest.TestCase):
    def _ordre(self):
        result = MeetingAnalysisResult(
            updated_topics=[ActiveTopicUpdate(topic_name="Tema A", summary="Resum.")],
            new_other_topics=[],
        )
        return format_ordre_del_dia(result, ["Tema A"], "01/01/2026")

    def test_marker_added_as_frontmatter(self):
        marked = with_pending_marker(self._ordre())
        self.assertTrue(marked.startswith("---\npendent_revisio: true\n---\n"))

    def test_parse_ignores_marker(self):
        marked = with_pending_marker(self._ordre())
        parsed = parse_ordre_del_dia(marked)
        self.assertEqual([t.topic_name for t in parsed.updated_topics], ["Tema A"])

    def test_strip_removes_marker_and_frontmatter(self):
        marked = with_pending_marker(self._ordre())
        stripped = strip_pending_marker(marked)
        self.assertEqual(stripped, self._ordre())
        self.assertNotIn("pendent_revisio", stripped)

    def test_strip_idempotent_when_no_marker(self):
        plain = self._ordre()
        self.assertEqual(strip_pending_marker(plain), plain)

    def test_strip_preserves_other_frontmatter_keys(self):
        text = "---\npendent_revisio: true\naltrakey: valor\n---\n### cos\n"
        stripped = strip_pending_marker(text)
        self.assertNotIn("pendent_revisio", stripped)
        self.assertIn("altrakey: valor", stripped)
        self.assertTrue(stripped.startswith("---\n"))


if __name__ == "__main__":
    unittest.main()
