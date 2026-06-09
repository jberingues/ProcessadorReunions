"""Tests unitaris per a plaud_client. Executar amb:
    uv run python -m unittest discover -s tests
"""
import os
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from plaud_client import (  # noqa: E402
    PlaudCLINotInstalled,
    PlaudClient,
    PlaudError,
    PlaudNotAuthenticated,
    _resolve_executable,
    parse_duration,
    parse_file_output,
    parse_list_output,
    strip_transcript_header,
)


SAMPLE_TODAY = (
    "- Fetching today's recordings...\n"
    "\n"
    "Today's recordings: 2\n"
    "\n"
    "  75caa11ec58668095c2e6389d21f2717  05-18 Reunió Setmanal: Projectes R4G, Biprox, Eurotrack, Videoporter, Fonoenac  2026-05-18  22m19s\n"
    "  c5aa899d581cda43a73558e4e5cf0347  05-18 Entrevista: Candidat a pràctiques d'electrònica  2026-05-18  38m02s\n"
    "\n"
)

SAMPLE_EMPTY_LIST = (
    "- Fetching today's recordings...\n"
    "\n"
    "Today's recordings: 0\n"
    "\n"
)

SAMPLE_FILE = (
    "- Fetching file...\n"
    "\n"
    "File Details:\n"
    "\n"
    "  id:           75caa11ec58668095c2e6389d21f2717\n"
    "  name:         05-18 Reunió Setmanal\n"
    "  created_at:   2026-05-18T10:27:12\n"
    "  start_at:     2026-05-18T06:19:04\n"
    "  duration:     22m19s\n"
    "  serial_number: 888316597710719884\n"
    "  audio:        available\n"
    "  transcript:   available\n"
    "  summary:      available\n"
)

SAMPLE_TRANSCRIPT = (
    "- Fetching transcript...\n"
    "\n"
    "Transcript: 05-18 Reunió Setmanal\n"
    "\n"
    "[00:01 - 00:04] Speaker 1: Som-hi, la R4G.\n"
    "[00:04 - 00:38] Gemma Reverter: R4G, l'electrònica...\n"
)


class TestParseDuration(unittest.TestCase):
    def test_minuts_segons(self):
        self.assertEqual(parse_duration("22m19s"), 22 * 60 + 19)

    def test_amb_hores(self):
        self.assertEqual(parse_duration("1h23m45s"), 3600 + 23 * 60 + 45)

    def test_nomes_segons(self):
        self.assertEqual(parse_duration("45s"), 45)

    def test_nomes_minuts(self):
        self.assertEqual(parse_duration("5m"), 300)

    def test_buit(self):
        with self.assertRaises(ValueError):
            parse_duration("")

    def test_invalid(self):
        with self.assertRaises(ValueError):
            parse_duration("abc")


class TestParseListOutput(unittest.TestCase):
    def test_dues_files(self):
        recs = parse_list_output(SAMPLE_TODAY)
        self.assertEqual(len(recs), 2)
        self.assertEqual(recs[0].file_id, "75caa11ec58668095c2e6389d21f2717")
        self.assertEqual(
            recs[0].name,
            "05-18 Reunió Setmanal: Projectes R4G, Biprox, Eurotrack, Videoporter, Fonoenac",
        )
        self.assertEqual(recs[0].date, "2026-05-18")
        self.assertEqual(recs[0].duration_seconds, 22 * 60 + 19)
        self.assertEqual(recs[1].duration_seconds, 38 * 60 + 2)

    def test_sortida_buida(self):
        self.assertEqual(parse_list_output(""), [])

    def test_sense_files(self):
        self.assertEqual(parse_list_output(SAMPLE_EMPTY_LIST), [])


class TestParseFileOutput(unittest.TestCase):
    def test_claus_principals(self):
        data = parse_file_output(SAMPLE_FILE)
        self.assertEqual(data["id"], "75caa11ec58668095c2e6389d21f2717")
        self.assertEqual(data["start_at"], "2026-05-18T06:19:04")
        self.assertEqual(data["created_at"], "2026-05-18T10:27:12")
        self.assertEqual(data["duration"], "22m19s")
        self.assertEqual(data["audio"], "available")


class TestStripTranscriptHeader(unittest.TestCase):
    def test_elimina_capcalera(self):
        body = strip_transcript_header(SAMPLE_TRANSCRIPT)
        self.assertTrue(body.startswith("[00:01"))
        self.assertNotIn("Fetching", body)
        self.assertNotIn("Transcript:", body)

    def test_buit(self):
        self.assertEqual(strip_transcript_header(""), "")


class TestResolveExecutable(unittest.TestCase):
    def test_troba_via_path_estandard(self):
        # `ls` és present a /bin/ls a tots els Unix.
        resolved = _resolve_executable("ls")
        self.assertIsNotNone(resolved)
        self.assertTrue(os.path.isabs(resolved))

    def test_troba_via_path_ampliat(self):
        # Crea un binari fals a un dir, treu-lo del PATH normal, comprova fallback.
        import stat
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "plaud_fake_xyz"
            fake.write_text("#!/bin/sh\necho ok\n")
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            # PATH minimal sense el tmp dir → resolve via fallback list
            with patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}, clear=False), \
                 patch("plaud_client._EXTRA_BIN_PATHS", [tmp]):
                resolved = _resolve_executable("plaud_fake_xyz")
            self.assertEqual(resolved, str(fake))

    def test_no_es_troba(self):
        self.assertIsNone(_resolve_executable("plaud_inexistent_xyz_12345"))


class TestPlaudClientSubprocess(unittest.TestCase):
    def test_cli_no_instal_lat(self):
        client = PlaudClient(executable="plaud_inexistent_xyz_12345")
        with self.assertRaises(PlaudCLINotInstalled):
            client._run(["me"])

    def test_constructor_resol_ruta_absoluta(self):
        # Si el binari es troba (e.g. "ls"), el constructor guarda la ruta absoluta.
        client = PlaudClient(executable="ls")
        self.assertTrue(os.path.isabs(client.executable))

    @patch("plaud_client.subprocess.run")
    def test_no_autenticat_per_missatge(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="Error: please login first"
        )
        with self.assertRaises(PlaudNotAuthenticated):
            PlaudClient()._run(["me"])

    @patch("plaud_client.subprocess.run")
    def test_error_generic(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="Network error: unreachable"
        )
        with self.assertRaises(PlaudError):
            PlaudClient()._run(["me"])

    @patch("plaud_client.subprocess.run")
    def test_is_authenticated_true(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="User info", stderr="")
        self.assertTrue(PlaudClient().is_authenticated())

    @patch("plaud_client.subprocess.run")
    def test_is_authenticated_false(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="login required")
        self.assertFalse(PlaudClient().is_authenticated())


class TestPlaudClientHighLevel(unittest.TestCase):
    @patch("plaud_client.subprocess.run")
    def test_get_start_at_utc(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout=SAMPLE_FILE, stderr="")
        start = PlaudClient().get_start_at_utc("75ca")
        self.assertEqual(start, datetime(2026, 5, 18, 6, 19, 4, tzinfo=timezone.utc))

    @patch("plaud_client.subprocess.run")
    def test_get_transcript(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout=SAMPLE_TRANSCRIPT, stderr="")
        body = PlaudClient().get_transcript("75ca")
        self.assertIn("Som-hi", body)
        self.assertNotIn("Fetching", body)

    @patch("plaud_client.subprocess.run")
    def test_list_for_date_today_filtra(self, mock_run):
        # SAMPLE_TODAY no parseja com a `file`, així que get_start_at_utc retorna
        # None i el filtre cau al fallback de data del CLI (comportament antic).
        mock_run.return_value = MagicMock(returncode=0, stdout=SAMPLE_TODAY, stderr="")
        with patch("plaud_client.datetime") as mock_dt:
            mock_dt.now.return_value.date.return_value = date(2026, 5, 18)
            recs = PlaudClient().list_for_date(date(2026, 5, 18))
        self.assertEqual(len(recs), 2)
        # Cap fila té data 2026-05-17
        with patch("plaud_client.datetime") as mock_dt:
            mock_dt.now.return_value.date.return_value = date(2026, 5, 18)
            recs = PlaudClient().list_for_date(date(2026, 5, 17))
        # No s'ha filtrat cap fila amb 2026-05-17 al sample
        self.assertEqual(len(recs), 0)

    @patch("plaud_client.subprocess.run")
    def test_list_for_date_filtra_per_start_at_no_per_pujada(self, mock_run):
        # Gravació feta el 06-08 (start_at migdia UTC → data local 06-08 a
        # qualsevol fus) però pujada el 06-09 (el CLI la llista sota 06-09).
        list_out = (
            "- Fetching recordings...\n"
            "\n"
            "Recordings in the last 3 days: 1\n"
            "\n"
            "  b3be3d80c14f254502eca31d1e4a337f  06-08 Reunió tard  2026-06-09  3h04m\n"
            "\n"
        )
        file_out = (
            "File Details:\n"
            "  id:           b3be3d80c14f254502eca31d1e4a337f\n"
            "  name:         06-08 Reunió tard\n"
            "  created_at:   2026-06-09T13:05:40\n"
            "  start_at:     2026-06-08T12:00:00\n"
            "  duration:     3h04m\n"
        )
        # 1a crida = llistat; següents = `file <id>`.
        def side_effect(args, **kwargs):
            is_file = "file" in args
            return MagicMock(
                returncode=0,
                stdout=file_out if is_file else list_out,
                stderr="",
            )
        mock_run.side_effect = side_effect

        # Carregant el 06-08 SÍ ha de sortir (filtra per start_at local).
        with patch("plaud_client.datetime") as mock_dt:
            mock_dt.now.return_value.date.return_value = date(2026, 6, 9)
            mock_dt.fromisoformat = datetime.fromisoformat
            recs = PlaudClient().list_for_date(date(2026, 6, 8))
        self.assertEqual([r.file_id for r in recs], ["b3be3d80c14f254502eca31d1e4a337f"])
        self.assertIsNotNone(recs[0].start_at)  # queda poblat per al matcher

        # Carregant el 06-09 (la data de pujada) NO ha de sortir.
        with patch("plaud_client.datetime") as mock_dt:
            mock_dt.now.return_value.date.return_value = date(2026, 6, 9)
            mock_dt.fromisoformat = datetime.fromisoformat
            recs = PlaudClient().list_for_date(date(2026, 6, 9))
        self.assertEqual(recs, [])


if __name__ == "__main__":
    unittest.main()
