"""Tests unitaris per a meeting_recording_matcher. Executar amb:
    uv run python -m unittest discover -s tests
"""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from meeting_recording_matcher import (  # noqa: E402
    MatchResult,
    Pair,
    PairStatus,
    match,
)
from plaud_client import PlaudRecording  # noqa: E402


UTC = timezone.utc
# Madrid és UTC+2 al maig (CEST). Faig servir tz fix UTC+2 per simplicitat.
CEST = timezone(timedelta(hours=2))


def make_event(title: str, start: datetime, duration_min: int) -> dict:
    return {
        "title": title,
        "start": start,
        "end": start + timedelta(minutes=duration_min),
        "duration": str(timedelta(minutes=duration_min)),
        "attendees": [],
    }


def make_rec(file_id: str, start_utc: datetime, duration_s: int, name: str = "rec") -> PlaudRecording:
    return PlaudRecording(
        file_id=file_id,
        name=name,
        date=start_utc.astimezone(UTC).date().isoformat(),
        duration_seconds=duration_s,
        start_at=start_utc,
    )


class TestMatchBasic(unittest.TestCase):
    def test_inputs_buits(self):
        r = match([], [])
        self.assertEqual(r.pairs, [])
        self.assertEqual(r.unmatched_events, [])
        self.assertEqual(r.unmatched_recordings, [])

    def test_un_aparellament_perfecte_auto(self):
        ev = make_event("Setmanal", datetime(2026, 5, 18, 8, 15, tzinfo=CEST), 30)
        rec = make_rec("a", datetime(2026, 5, 18, 6, 19, tzinfo=UTC), 30 * 60 + 5)
        # 8:19 CEST == 6:19 UTC → 4 min offset, durada quasi exacta
        r = match([ev], [rec])
        self.assertEqual(len(r.pairs), 1)
        self.assertEqual(r.pairs[0].status, PairStatus.AUTO)
        self.assertGreater(r.pairs[0].score, 0.85)
        self.assertEqual(r.unmatched_events, [])
        self.assertEqual(r.unmatched_recordings, [])

    def test_offset_temporal_intermedi_suggerit(self):
        ev = make_event("Reunió", datetime(2026, 5, 18, 10, 0, tzinfo=CEST), 30)
        # Gravació 25 min tard → fora del rang auto però dins del suggerit
        rec = make_rec("a", datetime(2026, 5, 18, 8, 25, tzinfo=UTC), 30 * 60)
        r = match([ev], [rec])
        self.assertEqual(len(r.pairs), 1)
        self.assertEqual(r.pairs[0].status, PairStatus.SUGGESTED)

    def test_offset_temporal_massa_gran_sense_aparellament(self):
        ev = make_event("Reunió", datetime(2026, 5, 18, 10, 0, tzinfo=CEST), 30)
        # Gravació 3 hores després
        rec = make_rec("a", datetime(2026, 5, 18, 11, 0, tzinfo=UTC), 30 * 60)
        r = match([ev], [rec])
        self.assertEqual(r.pairs, [])
        self.assertEqual(len(r.unmatched_events), 1)
        self.assertEqual(len(r.unmatched_recordings), 1)


class TestMatchConflictes(unittest.TestCase):
    def test_dues_reunions_una_gravacio_va_a_la_millor(self):
        ev_propera = make_event("A", datetime(2026, 5, 18, 10, 0, tzinfo=CEST), 30)
        ev_llunyana = make_event("B", datetime(2026, 5, 18, 10, 45, tzinfo=CEST), 30)
        # Gravació coincideix amb ev_propera
        rec = make_rec("r1", datetime(2026, 5, 18, 8, 2, tzinfo=UTC), 30 * 60)
        r = match([ev_propera, ev_llunyana], [rec])
        self.assertEqual(len(r.pairs), 1)
        self.assertEqual(r.pairs[0].event["title"], "A")
        self.assertEqual(len(r.unmatched_events), 1)
        self.assertEqual(r.unmatched_events[0]["title"], "B")

    def test_dues_gravacions_una_reunio_pren_la_millor(self):
        ev = make_event("A", datetime(2026, 5, 18, 10, 0, tzinfo=CEST), 30)
        rec_bona = make_rec("r1", datetime(2026, 5, 18, 8, 1, tzinfo=UTC), 30 * 60)
        rec_dolenta = make_rec("r2", datetime(2026, 5, 18, 8, 20, tzinfo=UTC), 30 * 60)
        r = match([ev], [rec_bona, rec_dolenta])
        self.assertEqual(len(r.pairs), 1)
        self.assertEqual(r.pairs[0].recording.file_id, "r1")
        self.assertEqual(len(r.unmatched_recordings), 1)

    def test_assignament_creuat_correcte(self):
        # Dues reunions a hores diferents, dues gravacions a hores diferents.
        # Una assignació naïf podria fer cross-match; el greedy escull les millors primer.
        ev_a = make_event("A", datetime(2026, 5, 18, 10, 0, tzinfo=CEST), 30)
        ev_b = make_event("B", datetime(2026, 5, 18, 11, 0, tzinfo=CEST), 30)
        rec_a = make_rec("rA", datetime(2026, 5, 18, 8, 2, tzinfo=UTC), 30 * 60)   # 10:02 CEST
        rec_b = make_rec("rB", datetime(2026, 5, 18, 9, 3, tzinfo=UTC), 30 * 60)   # 11:03 CEST
        r = match([ev_a, ev_b], [rec_a, rec_b])
        self.assertEqual(len(r.pairs), 2)
        pairing = {p.event["title"]: p.recording.file_id for p in r.pairs}
        self.assertEqual(pairing, {"A": "rA", "B": "rB"})


class TestMatchEdgeCases(unittest.TestCase):
    def test_gravacio_sense_start_at_no_s_aparella(self):
        ev = make_event("A", datetime(2026, 5, 18, 10, 0, tzinfo=CEST), 30)
        rec = PlaudRecording(file_id="x", name="x", date="2026-05-18", duration_seconds=1800, start_at=None)
        r = match([ev], [rec])
        self.assertEqual(r.pairs, [])
        self.assertEqual(len(r.unmatched_events), 1)
        self.assertEqual(len(r.unmatched_recordings), 1)

    def test_temps_perfecte_meitat_de_durada_es_auto(self):
        # Reunió 60min, gravació 30min començant a l'hora exacta.
        # Amb pesos 0.85/0.15: time=1.0, dur=0.5 → 0.85 + 0.075 = 0.925 → AUTO
        ev = make_event("A", datetime(2026, 5, 18, 10, 0, tzinfo=CEST), 60)
        rec = make_rec("r", datetime(2026, 5, 18, 8, 0, tzinfo=UTC), 30 * 60)
        r = match([ev], [rec])
        self.assertEqual(len(r.pairs), 1)
        self.assertEqual(r.pairs[0].status, PairStatus.AUTO)

    def test_temps_perfecte_durada_triple_es_suggerit(self):
        # Reunió 30min, gravació 90min començant a l'hora exacta.
        # time=1.0, dur=0 (ratio=3) → 0.85. Per sota d'AUTO (0.9), SUGGESTED.
        ev = make_event("A", datetime(2026, 5, 18, 10, 0, tzinfo=CEST), 30)
        rec = make_rec("r", datetime(2026, 5, 18, 8, 0, tzinfo=UTC), 90 * 60)
        r = match([ev], [rec])
        self.assertEqual(len(r.pairs), 1)
        self.assertEqual(r.pairs[0].status, PairStatus.SUGGESTED)


if __name__ == "__main__":
    unittest.main()
