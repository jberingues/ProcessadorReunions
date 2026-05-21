"""Tests unitaris per a phonetic_filter. Executar amb:
    uv run python -m unittest discover -s tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from phonetic_filter import (  # noqa: E402
    find_fuzzy_candidates,
    is_likely_phonetic,
    levenshtein,
    normalized_distance,
    similarity,
)


class TestLevenshtein(unittest.TestCase):
    def test_identical(self):
        self.assertEqual(levenshtein("abc", "abc"), 0)

    def test_empty(self):
        self.assertEqual(levenshtein("", "abc"), 3)
        self.assertEqual(levenshtein("abc", ""), 3)
        self.assertEqual(levenshtein("", ""), 0)

    def test_single_edit(self):
        self.assertEqual(levenshtein("casa", "cosa"), 1)   # substitució
        self.assertEqual(levenshtein("casa", "cas"), 1)    # esborrat
        self.assertEqual(levenshtein("cas", "casa"), 1)    # inserció

    def test_known_examples(self):
        # queimei → KAIMAI (case-sensitive a nivell base): k→q, ...
        self.assertEqual(levenshtein("queimei", "kaimai"), 4)


class TestNormalizedDistance(unittest.TestCase):
    def test_case_insensitive(self):
        # La normalització passa a minúscules, així que onea i HONOA es comparen
        # com 'onea' vs 'honoa'.
        self.assertEqual(normalized_distance("Onea", "ONEA"), 0.0)

    def test_accent_insensitive(self):
        self.assertEqual(normalized_distance("àlex", "alex"), 0.0)

    def test_range(self):
        # Distància normalitzada està entre 0 i 1
        for a, b in [("casa", "cosa"), ("HONOA", "onea"), ("gestor", "administrador")]:
            d = normalized_distance(a, b)
            self.assertGreaterEqual(d, 0.0)
            self.assertLessEqual(d, 1.0)


class TestIsLikelyPhonetic(unittest.TestCase):
    def test_phonetic_errors_pass(self):
        # Errors típics d'ASR: similitud raonable (distància <= 0.75)
        self.assertTrue(is_likely_phonetic("queimei", "KAIMAI"))   # dist ~0.57
        self.assertTrue(is_likely_phonetic("onea", "HONOA"))       # dist ~0.40
        self.assertTrue(is_likely_phonetic("bidpfox", "bidprox"))  # dist ~0.14

    def test_semantic_substitution_blocked(self):
        # Sinònims sense relació fonètica clara: filtrats (distància > 0.75)
        self.assertFalse(is_likely_phonetic("cotxe", "automòbil"))
        self.assertFalse(is_likely_phonetic("casa", "habitatge"))
        self.assertFalse(is_likely_phonetic("petit", "enorme"))

    def test_empty_inputs(self):
        self.assertFalse(is_likely_phonetic("", "KAIMAI"))
        self.assertFalse(is_likely_phonetic("queimei", ""))

    def test_multi_word_passes(self):
        # No filtrem correccions multi-paraula amb el ratio simple
        self.assertTrue(is_likely_phonetic("una cosa", "altra cosa"))


class TestFindFuzzyCandidates(unittest.TestCase):
    def test_detects_phonetic_error(self):
        # Errors lleus (1-2 chars de diferència) són típicament el cas del fuzzy.
        # Errors severs (queimei→KAIMAI) queden per al LLM.
        transcript = "El sistema bidpfox falla sovint a l'arrencada."
        vocab = ["BIDPROX", "HONOA"]
        candidates = find_fuzzy_candidates(transcript, vocab)
        originals = {c['original'] for c in candidates}
        self.assertIn("bidpfox", originals)

    def test_skips_term_already_present(self):
        # Si el terme ja apareix literalment, no proposem candidata
        transcript = "Hem provat KAIMAI amb èxit."
        candidates = find_fuzzy_candidates(transcript, ["KAIMAI"])
        self.assertEqual(candidates, [])

    def test_skips_term_present_case_insensitive(self):
        # 'kaimai' al text equival a 'KAIMAI' al vocab → no proposem
        transcript = "Hem provat kaimai amb èxit."
        candidates = find_fuzzy_candidates(transcript, ["KAIMAI"])
        self.assertEqual(candidates, [])

    def test_no_false_match_for_short_words(self):
        # Paraules curtes (< 4 chars) s'ignoren per evitar soroll
        transcript = "Va dir si o no."
        candidates = find_fuzzy_candidates(transcript, ["sí"])
        self.assertEqual(candidates, [])

    def test_returns_correction_shape(self):
        transcript = "El sistema bidpfox té problemes."
        candidates = find_fuzzy_candidates(transcript, ["BIDPROX"])
        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        self.assertIn('original', c)
        self.assertIn('correccio', c)
        self.assertIn('motiu', c)
        self.assertIn('frase', c)
        self.assertIn('confiança', c)
        self.assertEqual(c['source'], 'fuzzy')
        self.assertEqual(c['correccio'], 'BIDPROX')

    def test_empty_inputs(self):
        self.assertEqual(find_fuzzy_candidates("", ["KAIMAI"]), [])
        self.assertEqual(find_fuzzy_candidates("text qualsevol", []), [])

    def test_no_match_below_threshold(self):
        # Paraules massa diferents: no proposem
        transcript = "Avui hem parlat de meteorologia i futbol."
        candidates = find_fuzzy_candidates(transcript, ["KAIMAI"])
        self.assertEqual(candidates, [])

    def test_dedup_originals(self):
        # Un mateix `original` no s'ha de proposar dos cops (si dos termes del
        # vocab són similars entre ells, només surt una candidata).
        transcript = "Va dir bidpfox diverses vegades."
        candidates = find_fuzzy_candidates(transcript, ["BIDPROX", "BIDPRAX"])
        originals = [c['original'] for c in candidates]
        self.assertEqual(len(originals), len(set(originals)))


if __name__ == "__main__":
    unittest.main()
