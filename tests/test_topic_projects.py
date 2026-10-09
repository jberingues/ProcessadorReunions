"""Tests del camp `projects` per tema (links a projectes, decisió 2026-10).

Cada tema tractat pot portar els projectes on s'hi decideix o informa alguna
cosa. Es renderitza com a `**Projectes:** [[A]], [[B]]` a l'Ordre del dia
(seguiment i resum) i al bloc anual, i parse_ordre_del_dia el recupera
(round-trip) perquè l'usuari el pugui validar/editar abans de consolidar.
Executar amb:
    uv run python -m unittest discover -s tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from meeting_analyzer import (
    ActiveTopicUpdate,
    MeetingAnalysisResult,
    StateFileUpdater,
    format_ordre_del_dia,
    format_resum,
    parse_ordre_del_dia,
)


def _result(*topics: ActiveTopicUpdate, others=None) -> MeetingAnalysisResult:
    return MeetingAnalysisResult(updated_topics=list(topics), new_other_topics=others or [])


A10 = ActiveTopicUpdate(
    topic_name="Substitució dels A7",
    summary="L'A10 no és substitut directe.",
    conclusion="No hi ha reemplaçament fiable.",
    projects=["A10Pro"],
)
DOS = ActiveTopicUpdate(
    topic_name="Videoporter i app",
    summary="Integració amb l'app.",
    conclusion="Es prioritza l'app.",
    projects=["A10Pro", "VDPJCM"],
)
CAP = ActiveTopicUpdate(topic_name="Producció Bulgària", summary="Canvis d'operaris.")


class TestTopicProjectsRender(unittest.TestCase):
    def test_default_is_empty_list(self):
        self.assertEqual(CAP.projects, [])

    def test_ordre_del_dia_renders_links_after_conclusion(self):
        text = format_ordre_del_dia(_result(A10), [], "05/10/2026")
        lines = text.splitlines()
        i = lines.index("* **Conclusió:** No hi ha reemplaçament fiable.")
        self.assertEqual(lines[i + 1], "* **Projectes:** [[A10Pro]]")

    def test_multiple_projects_comma_separated(self):
        text = format_ordre_del_dia(_result(DOS), [], "05/10/2026")
        self.assertIn("* **Projectes:** [[A10Pro]], [[VDPJCM]]", text)

    def test_no_projects_no_line(self):
        text = format_ordre_del_dia(_result(CAP), [], "05/10/2026")
        self.assertNotIn("Projectes:", text)

    def test_resum_renders_links(self):
        text = format_resum(_result(A10), "05/10/2026")
        self.assertIn("* **Projectes:** [[A10Pro]]", text)

    def test_year_block_renders_links(self):
        block = StateFileUpdater().build_year_block(_result(A10, CAP))
        self.assertIn("- **Projectes:** [[A10Pro]]", block)
        self.assertEqual(block.count("Projectes:"), 1)


class TestTopicProjectsParse(unittest.TestCase):
    def test_roundtrip_ordre_del_dia(self):
        original = _result(A10, DOS, CAP)
        parsed = parse_ordre_del_dia(format_ordre_del_dia(original, [], "05/10/2026"))
        self.assertEqual(
            [(t.topic_name, t.summary, t.conclusion, t.projects) for t in parsed.updated_topics],
            [(t.topic_name, t.summary, t.conclusion, t.projects) for t in original.updated_topics],
        )

    def test_roundtrip_resum(self):
        parsed = parse_ordre_del_dia(format_resum(_result(DOS), "05/10/2026"))
        self.assertEqual(parsed.updated_topics[0].projects, ["A10Pro", "VDPJCM"])

    def test_projects_line_not_merged_into_summary(self):
        parsed = parse_ordre_del_dia(format_ordre_del_dia(_result(A10), [], "05/10/2026"))
        self.assertNotIn("Projectes", parsed.updated_topics[0].summary)
        self.assertNotIn("[[", parsed.updated_topics[0].summary)

    def test_user_edits_projects_line(self):
        # L'usuari valida a Obsidian: esborra un projecte i n'afegeix un altre.
        text = format_ordre_del_dia(_result(DOS), [], "05/10/2026").replace(
            "* **Projectes:** [[A10Pro]], [[VDPJCM]]",
            "* **Projectes:** [[VDPJCM]], [[HONOA]]",
        )
        self.assertEqual(parse_ordre_del_dia(text).updated_topics[0].projects, ["VDPJCM", "HONOA"])

    def test_user_adds_projects_line_by_hand(self):
        text = format_ordre_del_dia(_result(CAP), [], "05/10/2026").replace(
            "* Canvis d'operaris.", "* Canvis d'operaris.\n* **Projectes:** [[BASIC-OPT]]"
        )
        self.assertEqual(parse_ordre_del_dia(text).updated_topics[0].projects, ["BASIC-OPT"])

    def test_user_empties_projects_line(self):
        text = format_ordre_del_dia(_result(A10), [], "05/10/2026").replace(
            "* **Projectes:** [[A10Pro]]", "* **Projectes:**"
        )
        self.assertEqual(parse_ordre_del_dia(text).updated_topics[0].projects, [])

    def test_link_variants_alias_and_heading(self):
        # [[X|text]] i [[X#secció]] → nom del fitxer X; duplicats fora.
        text = format_ordre_del_dia(_result(CAP), [], "05/10/2026").replace(
            "* Canvis d'operaris.",
            "* Canvis d'operaris.\n* **Projectes:** [[A10Pro|A10]], [[A10Pro#Resum]], [[R4G]]",
        )
        self.assertEqual(parse_ordre_del_dia(text).updated_topics[0].projects, ["A10Pro", "R4G"])

    def test_without_projects_line_is_backward_compatible(self):
        text = (
            "### Resum de la reunió 05/10/2026\n\n"
            "#### *1) Tema*\n* Resum.\n* **Conclusió:** Fet. [[A10Pro]]\n"
        )
        topic = parse_ordre_del_dia(text).updated_topics[0]
        self.assertEqual(topic.projects, [])
        # Els links inline antics (prova manual) es conserven al text.
        self.assertEqual(topic.conclusion, "Fet. [[A10Pro]]")


if __name__ == "__main__":
    unittest.main()
