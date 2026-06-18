"""Tests per al timing de la nota de transcripció (wizard_transcripcio).

El timing de la nota (data, hora, durada) ha de sortir de la **gravació**
(hora real), no de l'event programat al Calendar. `start_at` és UTC i el
contingut s'escriu amb el wall-clock, així que ha de quedar en hora local.

Executar amb: uv run python -m unittest discover -s tests
"""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "gui"))

from plaud_client import PlaudRecording  # noqa: E402
from meeting_recording_matcher import Pair, PairStatus  # noqa: E402
from gui.wizard_transcripcio import WizardTranscripcio  # noqa: E402


def _rec(start_at, dur=1800):
    return PlaudRecording(
        file_id="f1", name="Gravació X", date="2026-06-17",
        duration_seconds=dur, start_at=start_at,
    )


class TestRecordingTiming(unittest.TestCase):
    def test_start_at_es_converteix_a_local(self):
        # 22:30 UTC → local; comprovem que NO es queda en UTC.
        utc = datetime(2026, 6, 17, 22, 30, tzinfo=timezone.utc)
        timing = WizardTranscripcio._recording_timing(_rec(utc))
        self.assertEqual(timing['start'], utc.astimezone())
        self.assertEqual(timing['start'].tzinfo, utc.astimezone().tzinfo)

    def test_durada_des_de_la_gravacio(self):
        utc = datetime(2026, 6, 17, 9, 0, tzinfo=timezone.utc)
        timing = WizardTranscripcio._recording_timing(_rec(utc, dur=2700))
        self.assertEqual(timing['end'], timing['start'] + timedelta(seconds=2700))
        self.assertEqual(timing['duration'], str(timedelta(seconds=2700)))

    def test_sense_start_at(self):
        timing = WizardTranscripcio._recording_timing(_rec(None))
        self.assertIsNone(timing['start'])
        self.assertIsNone(timing['end'])
        self.assertEqual(timing['duration'], '')


class TestItemMeetingDict(unittest.TestCase):
    """`_item_meeting_dict` només usa self._recording_timing (staticmethod),
    així que el cridem amb la classe com a `self`."""

    def test_parell_pren_timing_de_la_gravacio_pero_identitat_del_calendar(self):
        ev_start = datetime(2026, 6, 17, 10, 0, tzinfo=timezone.utc)
        rec_start = datetime(2026, 6, 17, 10, 7, tzinfo=timezone.utc)  # començà tard
        event = {
            'title': 'Seguiment A10Pro',
            'start': ev_start,
            'end': ev_start + timedelta(hours=1),
            'duration': str(timedelta(hours=1)),
            'attendees': [{'name': 'Joan'}],
        }
        pair = Pair(event=event, recording=_rec(rec_start, dur=1500),
                    status=PairStatus.AUTO, score=0.95)
        d = WizardTranscripcio._item_meeting_dict(WizardTranscripcio, pair)
        # Identitat del Calendar
        self.assertEqual(d['title'], 'Seguiment A10Pro')
        self.assertEqual(d['attendees'], [{'name': 'Joan'}])
        # Timing real de la gravació (en local)
        self.assertEqual(d['start'], rec_start.astimezone())
        self.assertEqual(d['duration'], str(timedelta(seconds=1500)))
        # No hem mutat l'event original
        self.assertEqual(event['start'], ev_start)

    def test_parell_sense_start_at_conserva_event(self):
        ev_start = datetime(2026, 6, 17, 10, 0, tzinfo=timezone.utc)
        event = {
            'title': 'X', 'start': ev_start, 'end': ev_start,
            'duration': '1:00:00', 'attendees': [],
        }
        pair = Pair(event=event, recording=_rec(None),
                    status=PairStatus.MANUAL, score=0.0)
        d = WizardTranscripcio._item_meeting_dict(WizardTranscripcio, pair)
        self.assertEqual(d['start'], ev_start)
        self.assertEqual(d['duration'], '1:00:00')

    def test_orfe_fabrica_dict(self):
        rec_start = datetime(2026, 6, 17, 8, 30, tzinfo=timezone.utc)
        d = WizardTranscripcio._item_meeting_dict(WizardTranscripcio, _rec(rec_start))
        self.assertEqual(d['title'], 'Gravació X')
        self.assertEqual(d['attendees'], [])
        self.assertEqual(d['start'], rec_start.astimezone())


if __name__ == '__main__':
    unittest.main()
