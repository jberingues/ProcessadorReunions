"""Tests del script de migració Vocabulari + Canvis-Memoritzats → unificat.

Executar amb:
    uv run python -m unittest discover -s tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from migrate_vocabulary import (  # noqa: E402
    ORPHAN_SECTION,
    build_term_lookup,
    is_suspicious,
    migrate,
    normalize,
)


class TestIsSuspicious(unittest.TestCase):
    def test_too_short(self):
        s, reason = is_suspicious("TE", "OT")
        self.assertTrue(s)
        self.assertIn("curt", reason)

    def test_dangerous_alias(self):
        s, _ = is_suspicious("Max", "Macsa")
        self.assertTrue(s)
        s, _ = is_suspicious("Maxi", "Macsa")
        self.assertTrue(s)
        s, _ = is_suspicious("DEP", "DEV")
        self.assertTrue(s)

    def test_only_case_change(self):
        # tremol → Tremol és només cas, sospitós
        s, reason = is_suspicious("tremol", "Tremol")
        self.assertTrue(s)
        self.assertIn("cas", reason)

    def test_acronym_case_change_allowed(self):
        # Honoa → HONOA: target tot majúscules, NO és sospitós
        s, _ = is_suspicious("Honoa", "HONOA")
        self.assertFalse(s)

    def test_normal_alias_passes(self):
        s, _ = is_suspicious("queimei", "KAIMAI")
        self.assertFalse(s)
        s, _ = is_suspicious("congeladors", "HONOADOOR")
        self.assertFalse(s)

    def test_format_change_with_space_allowed(self):
        # Cloud Assistant → CloudAssistant: més que canvi de cas (treu espai)
        s, _ = is_suspicious("Cloud Assistant", "CloudAssistant")
        self.assertFalse(s)


class TestNormalize(unittest.TestCase):
    def test_lowercase_and_accent_strip(self):
        self.assertEqual(normalize("HONOA"), "honoa")
        self.assertEqual(normalize("Bulgària"), "bulgaria")
        self.assertEqual(normalize("Pérez"), "perez")


class TestBuildTermLookup(unittest.TestCase):
    def test_simple_terms_indexed(self):
        sections = {"Projectes": ["HONOADOOR", "KAIMAI"]}
        lookup = build_term_lookup(sections)
        self.assertIn("honoadoor", lookup)
        self.assertEqual(lookup["honoadoor"], ("Projectes", "HONOADOOR"))

    def test_arrow_acronym_left_side_indexed(self):
        # "RiD / R+D / RmesD → ..." → cada alternant de l'esquerra és cercable
        sections = {"Acrònims": ["RiD / R+D / RmesD → Recerca i Desenvolupament"]}
        lookup = build_term_lookup(sections)
        self.assertIn(normalize("RmesD"), lookup)
        self.assertIn(normalize("RiD"), lookup)
        # I el target preserva la línia sencera
        section, term = lookup[normalize("RiD")]
        self.assertEqual(section, "Acrònims")
        self.assertEqual(term, "RiD / R+D / RmesD → Recerca i Desenvolupament")


class TestMigrate(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.vocab_file = tempfile.NamedTemporaryFile('w', suffix='.md', delete=False, encoding='utf-8')
        self.vocab_file.write("""---
updated: 2026-05-21
---

## Persones
- Bonache
- Gemma

## Projectes
- HONOA
- KAIMAI

## Abreviatures i Acrònims
- IA → Intel·ligència Artificial
""")
        self.vocab_file.close()

        self.canvis_file = tempfile.NamedTemporaryFile('w', suffix='.md', delete=False, encoding='utf-8')
        self.canvis_file.write("""# Canvis Memoritzats

- Monatxa → Bonache
- Jemma → Gemma
- queimei → KAIMAI
- IEA → IA
- TE → OT
- Max → Macsa
- Persona_Nova → Cas_Orfe
""")
        self.canvis_file.close()

    def tearDown(self):
        Path(self.vocab_file.name).unlink()
        Path(self.canvis_file.name).unlink()

    def test_aliases_attached_to_correct_term(self):
        new_sections, kept, filtered = migrate(
            Path(self.vocab_file.name), Path(self.canvis_file.name)
        )
        # Monatxa hauria d'estar sota Bonache
        bonache_aliases = dict(new_sections['Persones'])['Bonache']
        self.assertIn('Monatxa', bonache_aliases)

    def test_arrow_acronym_receives_alias(self):
        new_sections, _, _ = migrate(
            Path(self.vocab_file.name), Path(self.canvis_file.name)
        )
        # IEA → IA: IA és un acrònim al Vocabulari ('IA → Intel·ligència Artificial')
        section_dict = dict(new_sections['Abreviatures i Acrònims'])
        full_term = 'IA → Intel·ligència Artificial'
        self.assertIn(full_term, section_dict)
        self.assertIn('IEA', section_dict[full_term])

    def test_orphan_target_goes_to_orphan_section(self):
        new_sections, kept, _ = migrate(
            Path(self.vocab_file.name), Path(self.canvis_file.name)
        )
        # 'Cas_Orfe' no és al Vocabulari → va a "Altres"
        self.assertIn(ORPHAN_SECTION, new_sections)
        orphan = dict(new_sections[ORPHAN_SECTION])
        self.assertIn('Cas_Orfe', orphan)
        self.assertIn('Persona_Nova', orphan['Cas_Orfe'])

    def test_suspicious_filtered(self):
        _, kept, filtered = migrate(
            Path(self.vocab_file.name), Path(self.canvis_file.name)
        )
        aliases_filtered = {f['alias'] for f in filtered}
        self.assertIn('TE', aliases_filtered)
        self.assertIn('Max', aliases_filtered)

    def test_kept_count_matches(self):
        _, kept, filtered = migrate(
            Path(self.vocab_file.name), Path(self.canvis_file.name)
        )
        # 7 aliases originals, 2 filtrats (TE, Max), 5 acceptats
        self.assertEqual(len(filtered), 2)
        self.assertEqual(len(kept), 5)


if __name__ == '__main__':
    unittest.main()
