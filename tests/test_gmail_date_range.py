"""Tests per a la construcció de la query Gmail de rang de dates."""
import sys
import unittest
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from gmail_fetcher import build_date_range_query


class TestBuildDateRangeQuery(unittest.TestCase):
    def test_single_day_range(self):
        # Un sol dia: after:dia before:dia+1 (before exclusiu a Gmail).
        q = build_date_range_query(date(2026, 6, 8), date(2026, 6, 8))
        self.assertEqual(q, "after:2026/06/08 before:2026/06/09")

    def test_seven_day_window(self):
        # Finestra de 7 dies acabant el 8: del 2 al 8 inclusius.
        q = build_date_range_query(date(2026, 6, 2), date(2026, 6, 8))
        self.assertEqual(q, "after:2026/06/02 before:2026/06/09")

    def test_month_boundary(self):
        # El before exclusiu salta correctament de mes.
        q = build_date_range_query(date(2026, 5, 28), date(2026, 5, 31))
        self.assertEqual(q, "after:2026/05/28 before:2026/06/01")

    def test_accepts_datetime(self):
        # Accepta datetime i en pren la part date.
        q = build_date_range_query(
            datetime(2026, 6, 2, 9, 30), datetime(2026, 6, 8, 18, 0)
        )
        self.assertEqual(q, "after:2026/06/02 before:2026/06/09")


if __name__ == "__main__":
    unittest.main()
