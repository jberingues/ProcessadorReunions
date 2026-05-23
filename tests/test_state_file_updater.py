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

    def test_updates_topic_and_no_closed(self):
        self.temes.write_text(
            "### Tema A\n- punt previ\n\n## Altres temes\n", encoding="utf-8"
        )
        result = MeetingAnalysisResult(
            updated_topics=[ActiveTopicUpdate(topic_name="Tema A", summary="nou estat")],
            new_other_topics=[],
        )
        block = self.updater.update(self.temes, result, "260520")
        # Cap tema "Tancat" → bloc buit retornat
        self.assertEqual(block, "")
        # El fitxer Temes oberts conté el nou bullet datat
        text = self.temes.read_text(encoding="utf-8")
        self.assertIn("- **260520:** nou estat", text)

    def test_extracts_closed_topic_to_block(self):
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
        # Bloc retornat conté el tema tancat
        self.assertIn("Tema A (Tancat)", block)
        # El fitxer Temes oberts ja no conté el tema tancat
        text = self.temes.read_text(encoding="utf-8")
        self.assertNotIn("Tema A (Tancat)", text)
        self.assertIn("Tema B", text)

    def test_new_other_topics_appended_to_altres(self):
        self.temes.write_text(
            "### Tema A\n- punt\n\n## Altres temes\n", encoding="utf-8"
        )
        result = MeetingAnalysisResult(
            updated_topics=[],
            new_other_topics=["Tema nou X"],
        )
        block = self.updater.update(self.temes, result, "260520")
        text = self.temes.read_text(encoding="utf-8")
        self.assertIn("- Tema nou X", text)
        # No hi ha temes tancats → bloc buit
        self.assertEqual(block, "")


if __name__ == "__main__":
    unittest.main()
