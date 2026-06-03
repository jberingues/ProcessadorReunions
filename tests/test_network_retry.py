"""Tests unitaris per al retry d'errors de xarxa transitoris a workers.py.
Executar amb:
    uv run python -m unittest discover -s tests
"""
import errno
import socket
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "gui"))

from gui.workers import (  # noqa: E402
    _is_transient_network_error,
    _retry_on_network_error,
)


class TestIsTransientNetworkError(unittest.TestCase):
    def test_eaddrnotavail_es_transitori(self):
        exc = OSError(errno.EADDRNOTAVAIL, "Can't assign requested address")
        self.assertTrue(_is_transient_network_error(exc))

    def test_connectionerror_es_transitori(self):
        self.assertTrue(_is_transient_network_error(ConnectionResetError()))

    def test_socket_timeout_es_transitori(self):
        self.assertTrue(_is_transient_network_error(socket.timeout()))

    def test_oserror_no_transitori(self):
        # ENOENT (fitxer no trobat) no és un error de xarxa.
        exc = OSError(errno.ENOENT, "No such file")
        self.assertFalse(_is_transient_network_error(exc))

    def test_valueerror_no_transitori(self):
        self.assertFalse(_is_transient_network_error(ValueError("x")))


class TestRetryOnNetworkError(unittest.TestCase):
    def test_retorna_a_la_primera_si_va_be(self):
        calls = []

        def fn():
            calls.append(1)
            return "ok"

        self.assertEqual(_retry_on_network_error(fn, attempts=3, base_delay=0), "ok")
        self.assertEqual(len(calls), 1)

    def test_reintenta_i_acaba_be(self):
        calls = []

        def fn():
            calls.append(1)
            if len(calls) < 3:
                raise OSError(errno.EADDRNOTAVAIL, "transient")
            return "ok"

        self.assertEqual(_retry_on_network_error(fn, attempts=3, base_delay=0), "ok")
        self.assertEqual(len(calls), 3)

    def test_esgota_intents_i_rellança(self):
        calls = []

        def fn():
            calls.append(1)
            raise OSError(errno.EADDRNOTAVAIL, "transient")

        with self.assertRaises(OSError):
            _retry_on_network_error(fn, attempts=3, base_delay=0)
        self.assertEqual(len(calls), 3)

    def test_error_no_transitori_no_reintenta(self):
        calls = []

        def fn():
            calls.append(1)
            raise ValueError("boom")

        with self.assertRaises(ValueError):
            _retry_on_network_error(fn, attempts=3, base_delay=0)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
