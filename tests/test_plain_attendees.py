"""Assistents sense links (decisió 2026-10): els noms de persona s'escriuen en
text pla al frontmatter, a la línia **Assistents:** i als encapçalaments per
persona dels anuals de Sincronització. Els links es reserven per a projectes.
Executar amb: uv run python -m unittest discover -s tests
"""
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from obsidian_writer import ObsidianWriter
from daily_processor import DailyProcessor, DailyScrumResult


class TestMeetingNoteAttendees(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "Reunions").mkdir()
        self.writer = ObsidianWriter(self.tmp)
        self.meeting = {
            "title": "Reunió qualitat",
            "start": datetime(2026, 10, 5, 9, 30),
            "duration": "1:00:00",
            "attendees": [{"name": "Jordi Beringues", "email": "j@x.com"},
                          {"name": "Pere Coma"}],
        }

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_no_links_in_new_note(self):
        content = self.writer._gen_content(self.meeting, "text")
        self.assertNotIn("[[", content)
        self.assertIn('attendees:\n  - "Jordi Beringues"\n  - "Pere Coma"\n', content)
        self.assertIn("**Assistents:** Jordi Beringues, Pere Coma\n", content)

    def test_read_attendees_roundtrip(self):
        target = self.tmp / "Reunions" / "S" / "Reunions"
        self.assertTrue(self.writer.create_simple_note(self.meeting, "text", target))
        note = next(target.glob("*.md"))
        self.assertEqual(self.writer.read_attendees(note), ["Jordi Beringues", "Pere Coma"])


class TestDailyHeadings(unittest.TestCase):
    def test_person_headings_without_links(self):
        dp = object.__new__(DailyProcessor)  # sense LLM: només formatació
        result = DailyScrumResult.model_validate({
            "participants": [{"name": "Raül Trullà", "ahir": ["a"], "avui": []}],
            "altres_temes": [],
        })
        md = dp.format_markdown(result, "Sincro", "2026-10-05")
        self.assertIn("##### Raül Trullà\n", md)
        self.assertNotIn("[[", md)


if __name__ == "__main__":
    unittest.main()
