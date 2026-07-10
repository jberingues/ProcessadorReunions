"""Tests d'email_archiver.trim_quoted_reply (retall de cites en respostes).

Executar amb: uv run python -m unittest discover -s tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from email_archiver import trim_quoted_reply


class TestTrimQuotedReply(unittest.TestCase):
    def test_no_markers_unchanged(self):
        body = "Hola,\n\nD'acord amb la proposta.\n\nSalutacions,\nJordi"
        self.assertEqual(trim_quoted_reply(body), body)

    def test_catalan_attribution_line(self):
        body = (
            "Perfecte, quedem dijous.\n"
            "\n"
            "El dia 9 de jul. 2026, a les 10:30, Anna Puig va escriure:\n"
            "\n"
            "text antic del fil\n"
            "més text antic"
        )
        self.assertEqual(trim_quoted_reply(body), "Perfecte, quedem dijous.")

    def test_english_attribution_line(self):
        body = (
            "Sounds good, thanks!\n"
            "\n"
            "On Mon, Jul 6, 2026 at 9:12 AM John Smith <john@ebv.com> wrote:\n"
            "old content"
        )
        self.assertEqual(trim_quoted_reply(body), "Sounds good, thanks!")

    def test_original_message_separator(self):
        body = (
            "Adjunto la versió final.\n"
            "\n"
            "-----Missatge original-----\n"
            "De: Pere\n"
            "contingut antic"
        )
        self.assertEqual(trim_quoted_reply(body), "Adjunto la versió final.")

    def test_outlook_inline_header_block(self):
        body = (
            "Confirmat per part nostra.\n"
            "\n"
            "**De:** Maria Soler <maria@jcm-tech.com>\n"
            "**Enviat:** dimarts, 7 de juliol de 2026 16:02\n"
            "**Per a:** Jordi Beringues\n"
            "cos del missatge antic"
        )
        self.assertEqual(trim_quoted_reply(body), "Confirmat per part nostra.")

    def test_run_of_quoted_lines(self):
        body = (
            "Sí, endavant.\n"
            "\n"
            "> línia citada 1\n"
            "> línia citada 2\n"
            "> línia citada 3"
        )
        self.assertEqual(trim_quoted_reply(body), "Sí, endavant.")

    def test_single_quoted_line_not_cut(self):
        # Una sola línia amb '>' pot ser contingut legítim (p.ex. codi).
        body = "Mira aquest operador:\n> resultat = a\ni després segueix."
        self.assertEqual(trim_quoted_reply(body), body)

    def test_body_starting_with_quote_kept_whole(self):
        # Bottom-posting: si el tall cauria a la línia 0, es conserva tot.
        body = "> pregunta original\n> segona línia\n\nLa resposta és sí."
        self.assertEqual(trim_quoted_reply(body), body)

    def test_from_line_without_sent_line_not_cut(self):
        # "De:" sol (sense bloc de capçaleres a prop) no és marcador fiable.
        body = "Parlant del proveïdor:\nDe: moment no tenim resposta.\nSeguim."
        self.assertEqual(trim_quoted_reply(body), body)


if __name__ == "__main__":
    unittest.main()
