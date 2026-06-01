"""Tests unitaris per a ObsidianWriter.find_existing_note (protecció contra
re-imports duplicats al wizard de transcripcions). Executar amb:
    uv run python -m unittest discover -s tests
"""
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from obsidian_writer import ObsidianWriter


class TestFindExistingNote(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.target = self.tmp / "Reunions" / "Seguiment" / "A10Pro" / "Reunions"
        self.target.mkdir(parents=True)
        self.writer = ObsidianWriter(self.tmp)
        # Reunió del 2026-05-20 amb títol que dóna stem '260520_Reunio_A10Pro'.
        self.meeting = {
            "title": "Reunio A10Pro",
            "start": datetime(2026, 5, 20, 9, 0),
            "end": datetime(2026, 5, 20, 10, 0),
            "duration": "1:00:00",
            "attendees": [],
        }

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _stem(self) -> str:
        return "260520_Reunio_A10Pro"

    def test_returns_none_when_no_note(self):
        self.assertIsNone(self.writer.find_existing_note(self.meeting, self.target))

    def test_detects_uncorrected_note(self):
        p = self.target / f"{self._stem()}.md"
        p.write_text("x", encoding="utf-8")
        self.assertEqual(self.writer.find_existing_note(self.meeting, self.target), p)

    def test_detects_corrected_note(self):
        p = self.target / f"{self._stem()}~.md"
        p.write_text("x", encoding="utf-8")
        self.assertEqual(self.writer.find_existing_note(self.meeting, self.target), p)

    def test_detects_processed_note(self):
        p = self.target / f"{self._stem()}*.md"
        p.write_text("x", encoding="utf-8")
        self.assertEqual(self.writer.find_existing_note(self.meeting, self.target), p)

    def test_different_title_does_not_match(self):
        (self.target / "260520_Altra_Reunio.md").write_text("x", encoding="utf-8")
        self.assertIsNone(self.writer.find_existing_note(self.meeting, self.target))

    def test_different_date_does_not_match(self):
        # Mateix títol, dia diferent → stem diferent.
        other = dict(self.meeting, start=datetime(2026, 5, 21, 9, 0))
        (self.target / f"{self._stem()}.md").write_text("x", encoding="utf-8")
        self.assertIsNone(self.writer.find_existing_note(other, self.target))

    def test_none_start_returns_none(self):
        # Gravació orfe sense start_at resolt: no es pot calcular el nom.
        broken = dict(self.meeting, start=None)
        self.assertIsNone(self.writer.find_existing_note(broken, self.target))

    def test_matches_create_simple_note_filename(self):
        # find_existing_note ha de detectar el fitxer que create_simple_note crea.
        self.writer.create_simple_note(self.meeting, "transcripció", self.target)
        found = self.writer.find_existing_note(self.meeting, self.target)
        self.assertIsNotNone(found)
        self.assertEqual(found.name, f"{self._stem()}.md")


if __name__ == "__main__":
    unittest.main()
