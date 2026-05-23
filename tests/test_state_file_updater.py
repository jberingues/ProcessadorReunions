"""Tests unitaris per a StateFileUpdater i parse_active_topics. Executar amb:
    uv run python -m unittest discover -s tests
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from meeting_analyzer import (
    ActiveTopicUpdate,
    MeetingAnalysisResult,
    StateFileUpdater,
    parse_active_topics,
)


class TestParseActiveTopics(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "Temes oberts.md"

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_extracts_topic_headers(self):
        self.path.write_text(
            "### Tema 1\n- detall\n### Tema 2\n- detall\n## Altres temes\n- altre\n",
            encoding="utf-8",
        )
        self.assertEqual(parse_active_topics(self.path), ["Tema 1", "Tema 2"])

    def test_stops_at_altres_temes(self):
        self.path.write_text(
            "### A\n## Altres temes\n### B (ignorat — després de Altres temes)\n",
            encoding="utf-8",
        )
        self.assertEqual(parse_active_topics(self.path), ["A"])

    def test_empty_file(self):
        self.path.write_text("", encoding="utf-8")
        self.assertEqual(parse_active_topics(self.path), [])


class TestStateFileUpdater(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.temes = self.tmp / "Temes oberts.md"
        self.updater = StateFileUpdater()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_no_changes_returns_empty(self):
        self.temes.write_text("### Tema A\n- existent\n", encoding="utf-8")
        result = MeetingAnalysisResult(updated_topics=[], new_other_topics=[])
        block = self.updater.update(self.temes, result, "260520")
        self.assertEqual(block, "")
        # El fitxer no s'ha de tocar
        self.assertEqual(
            self.temes.read_text(encoding="utf-8"), "### Tema A\n- existent\n"
        )

    def test_update_topic_returns_meeting_block(self):
        self.temes.write_text(
            "### Tema A\n- punt previ\n\n## Altres temes\n", encoding="utf-8"
        )
        result = MeetingAnalysisResult(
            updated_topics=[ActiveTopicUpdate(topic_name="Tema A", summary="nou estat")],
            new_other_topics=[],
        )
        block = self.updater.update(self.temes, result, "260520")
        # El fitxer Temes oberts conté el nou bullet datat (s'actualitza com sempre)
        text = self.temes.read_text(encoding="utf-8")
        self.assertIn("- **260520:** nou estat", text)
        # El bloc retornat conté el tema tractat amb el resum
        self.assertIn("### Tema A", block)
        self.assertIn("- nou estat", block)

    def test_closed_topic_stays_in_file(self):
        """Els temes marcats com a (Tancat) NO s'eliminen del fitxer.
        L'usuari els treurà manualment quan ho decideixi."""
        self.temes.write_text(
            "### Tema A (Tancat)\n- detalls finals\n\n### Tema B\n- en curs\n\n## Altres temes\n",
            encoding="utf-8",
        )
        result = MeetingAnalysisResult(
            updated_topics=[
                ActiveTopicUpdate(topic_name="Tema A (Tancat)", summary="resolt")
            ],
            new_other_topics=[],
        )
        block = self.updater.update(self.temes, result, "260520")
        # El fitxer continua tenint tots dos temes
        text = self.temes.read_text(encoding="utf-8")
        self.assertIn("Tema A (Tancat)", text)
        self.assertIn("Tema B", text)
        # El bloc retornat conté el resum del tema tractat
        self.assertIn("### Tema A (Tancat)", block)
        self.assertIn("- resolt", block)

    def test_new_other_topics_appended_to_file_and_block(self):
        self.temes.write_text(
            "### Tema A\n- punt\n\n## Altres temes\n", encoding="utf-8"
        )
        result = MeetingAnalysisResult(
            updated_topics=[],
            new_other_topics=["Tema nou X"],
        )
        block = self.updater.update(self.temes, result, "260520")
        text = self.temes.read_text(encoding="utf-8")
        # El nou tema queda a la secció Altres temes del fitxer
        self.assertIn("- Tema nou X", text)
        # I també apareix al bloc del fitxer anual sota '#### Altres temes'
        self.assertIn("#### Altres temes", block)
        self.assertIn("- Tema nou X", block)

    def test_old_altres_cleared_when_updating(self):
        """La secció '## Altres temes' es buida a cada processat — els antics
        ja s'han escrit al fitxer anual quan van aparèixer."""
        self.temes.write_text(
            "### Tema A\n- punt\n\n## Altres temes\n- vell tema\n", encoding="utf-8"
        )
        result = MeetingAnalysisResult(
            updated_topics=[ActiveTopicUpdate(topic_name="Tema A", summary="resum")],
            new_other_topics=["Tema nou X"],
        )
        self.updater.update(self.temes, result, "260520")
        text = self.temes.read_text(encoding="utf-8")
        # El vell ja no hi és, només el nou
        self.assertNotIn("- vell tema", text)
        self.assertIn("- Tema nou X", text)

    def test_old_altres_cleared_even_without_new_topics(self):
        """Si no hi ha nous temes però sí temes tractats, la secció Altres temes
        es buida igualment."""
        self.temes.write_text(
            "### Tema A\n- punt\n\n## Altres temes\n- vell tema\n", encoding="utf-8"
        )
        result = MeetingAnalysisResult(
            updated_topics=[ActiveTopicUpdate(topic_name="Tema A", summary="resum")],
            new_other_topics=[],
        )
        self.updater.update(self.temes, result, "260520")
        text = self.temes.read_text(encoding="utf-8")
        self.assertNotIn("- vell tema", text)
        # La capçalera segueix existint
        self.assertIn("## Altres temes", text)

    def test_meeting_block_combines_topics_and_altres(self):
        self.temes.write_text(
            "### Tema A\n- punt\n\n### Tema B\n- punt\n\n## Altres temes\n",
            encoding="utf-8",
        )
        result = MeetingAnalysisResult(
            updated_topics=[
                ActiveTopicUpdate(topic_name="Tema A", summary="resum A"),
                ActiveTopicUpdate(topic_name="Tema B", summary="resum B"),
            ],
            new_other_topics=["Nou X", "Nou Y"],
        )
        block = self.updater.update(self.temes, result, "260520")
        # Ordre: temes tractats abans, després '#### Altres temes' amb els nous
        idx_a = block.index("### Tema A")
        idx_b = block.index("### Tema B")
        idx_altres = block.index("#### Altres temes")
        idx_x = block.index("- Nou X")
        idx_y = block.index("- Nou Y")
        self.assertLess(idx_a, idx_b)
        self.assertLess(idx_b, idx_altres)
        self.assertLess(idx_altres, idx_x)
        self.assertLess(idx_x, idx_y)


if __name__ == "__main__":
    unittest.main()
