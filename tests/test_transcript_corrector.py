"""Tests unitaris per a transcript_corrector. Executar amb:
    uv run python -m unittest discover -s tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from transcript_corrector import TranscriptCorrector  # noqa: E402


class TestReplaceWholeWord(unittest.TestCase):
    """Verifica que el reemplaçament respecta límits de paraula.

    Important: les correccions memoritzades (globals i locals) i `apply()`
    han d'usar el mateix mecanisme, sinó un alias com 'cabo → KAIMAI' també
    afectaria 'acabo'.
    """

    def test_no_match_inside_longer_word(self):
        result = TranscriptCorrector._replace_whole_word(
            "Quan acabo la feina", "cabo", "KAIMAI"
        )
        self.assertEqual(result, "Quan acabo la feina")

    def test_match_whole_word(self):
        result = TranscriptCorrector._replace_whole_word(
            "El cabo arriba demà", "cabo", "KAIMAI"
        )
        self.assertEqual(result, "El KAIMAI arriba demà")

    def test_match_multiple_occurrences(self):
        result = TranscriptCorrector._replace_whole_word(
            "queimei i queimei són el mateix", "queimei", "KAIMAI"
        )
        self.assertEqual(result, "KAIMAI i KAIMAI són el mateix")

    def test_match_at_start_and_end(self):
        result = TranscriptCorrector._replace_whole_word(
            "onea és diferent de HONOA però no de onea", "onea", "HONOA"
        )
        self.assertEqual(result, "HONOA és diferent de HONOA però no de HONOA")

    def test_match_with_punctuation(self):
        result = TranscriptCorrector._replace_whole_word(
            "Parlem d'onea, després d'HONOA.", "onea", "HONOA"
        )
        self.assertEqual(result, "Parlem d'HONOA, després d'HONOA.")

    def test_empty_original_returns_text(self):
        result = TranscriptCorrector._replace_whole_word(
            "text qualsevol", "", "X"
        )
        self.assertEqual(result, "text qualsevol")

    def test_case_sensitive(self):
        # El reemplaçament és case-sensitive (coherent amb apply() i editor).
        result = TranscriptCorrector._replace_whole_word(
            "Onea i onea", "onea", "HONOA"
        )
        self.assertEqual(result, "Onea i HONOA")

    def test_replacement_with_backslash_is_literal(self):
        # La correcció s'ha d'inserir literalment: re.sub interpretaria '\1'
        # o '\g' com a backreference i corrompria el text (o petaria).
        result = TranscriptCorrector._replace_whole_word(
            "el directori arrel", "arrel", r"C:\1\grup"
        )
        self.assertEqual(result, r"el directori C:\1\grup")

    def test_apply_uses_same_mechanism(self):
        """`apply()` ha de respectar límits de paraula igual que les memoritzades."""
        corrector = TranscriptCorrector.__new__(TranscriptCorrector)  # sense __init__ (evita LLM)
        result = corrector.apply(
            "Quan acabo el cabo",
            [{"original": "cabo", "correccio": "KAIMAI"}]
        )
        self.assertEqual(result, "Quan acabo el KAIMAI")


if __name__ == "__main__":
    unittest.main()
