"""Tests del filtre d'events del CalendarWorker (_is_timed_meeting).

Regressió: els events "de tot el dia" (només 'date', sense 'dateTime') amb
assistents passaven el filtre i _parse_event en treia datetimes naive, que
feien petar (TypeError) l'ordenació i l'aparellament del PairingView en
comparar-los amb els start_at tz-aware de Plaud.

Executar amb: uv run python -m unittest discover -s tests
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "gui"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from workers import _is_timed_meeting


class TestIsTimedMeeting(unittest.TestCase):
    def test_timed_event_with_attendees_passes(self):
        event = {
            'start': {'dateTime': '2026-07-10T09:00:00+02:00'},
            'attendees': [{'email': 'a@b.c'}],
        }
        self.assertTrue(_is_timed_meeting(event))

    def test_all_day_event_with_attendees_is_filtered(self):
        event = {
            'start': {'date': '2026-07-10'},
            'attendees': [{'email': 'a@b.c'}],
        }
        self.assertFalse(_is_timed_meeting(event))

    def test_event_without_attendees_is_filtered(self):
        event = {'start': {'dateTime': '2026-07-10T09:00:00+02:00'}}
        self.assertFalse(_is_timed_meeting(event))

    def test_event_without_start_is_filtered(self):
        self.assertFalse(_is_timed_meeting({'attendees': []}))


if __name__ == "__main__":
    unittest.main()
