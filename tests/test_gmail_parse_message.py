"""Tests de GmailFetcher._parse_message: la data ha de ser sempre tz-aware.

Regressió: un missatge sense capçalera Date (o amb data naive tipus '-0000')
donava un datetime naive que feia petar l'ordenació cronològica del fil a
fetch_thread_full (TypeError en comparar naive amb aware).

Executar amb: uv run python -m unittest discover -s tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from gmail_fetcher import GmailFetcher


def _msg(headers: dict) -> dict:
    """Missatge Gmail mínim (payload text/plain sense body)."""
    return {
        'id': 'm1',
        'payload': {
            'headers': [{'name': k, 'value': v} for k, v in headers.items()],
            'mimeType': 'text/plain',
            'body': {},
        },
    }


class TestParseMessageDate(unittest.TestCase):
    def setUp(self):
        self.fetcher = GmailFetcher(gmail_service=None)

    def test_normal_date_is_aware(self):
        parsed = self.fetcher._parse_message(
            _msg({'Date': 'Thu, 09 Jul 2026 10:30:00 +0200', 'From': 'a@b.c'})
        )
        self.assertIsNotNone(parsed['date'].tzinfo)

    def test_missing_date_falls_back_to_aware_now(self):
        parsed = self.fetcher._parse_message(_msg({'From': 'a@b.c'}))
        self.assertIsNotNone(parsed['date'].tzinfo)

    def test_naive_date_header_becomes_aware(self):
        # '-0000' → parsedate_to_datetime retorna un datetime naive.
        parsed = self.fetcher._parse_message(
            _msg({'Date': 'Thu, 09 Jul 2026 10:30:00 -0000', 'From': 'a@b.c'})
        )
        self.assertIsNotNone(parsed['date'].tzinfo)

    def test_mixed_dates_are_sortable(self):
        msgs = [
            self.fetcher._parse_message(_msg({'From': 'a@b.c'})),
            self.fetcher._parse_message(
                _msg({'Date': 'Thu, 09 Jul 2026 10:30:00 +0200', 'From': 'a@b.c'})
            ),
            self.fetcher._parse_message(
                _msg({'Date': 'Thu, 09 Jul 2026 10:30:00 -0000', 'From': 'a@b.c'})
            ),
        ]
        # No ha de llançar TypeError.
        msgs.sort(key=lambda m: m['date'])


if __name__ == "__main__":
    unittest.main()
