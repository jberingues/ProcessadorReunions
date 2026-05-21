"""Tests del VocabularyLoader amb format de sublistes per aliases.

Executar amb:
    uv run python -m unittest discover -s tests
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from vocabulary_loader import VocabularyLoader  # noqa: E402


SAMPLE_VOCAB = """---
type: configuracio
updated: 2026-05-21
---

# Vocabulari

## Configuració
- threshold_auto: 0.85

## Persones

- Bonache
  - Monatxa
  - Borracho
- Judith
  - ajudit

## Projectes

- HONOADOOR
  - congeladors
  - conelador
- HONOA
  - Honoa
  - Genoa
- A10Pro

## Abreviatures i Acrònims

- IA → Intel·ligència Artificial
  - IEA
"""


class TestVocabularyLoader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile('w', suffix='.md', delete=False, encoding='utf-8')
        self.tmp.write(SAMPLE_VOCAB)
        self.tmp.close()
        self.loader = VocabularyLoader(Path(self.tmp.name))

    def tearDown(self):
        Path(self.tmp.name).unlink()

    def test_load_returns_main_terms_only(self):
        """load() retorna només termes principals, no aliases."""
        vocab = self.loader.load()
        self.assertIn('Persones', vocab)
        self.assertIn('Bonache', vocab['Persones'])
        self.assertIn('Judith', vocab['Persones'])
        # Els aliases NO han d'aparèixer com a termes
        self.assertNotIn('Monatxa', vocab['Persones'])
        self.assertNotIn('Borracho', vocab['Persones'])
        self.assertNotIn('ajudit', vocab['Persones'])

    def test_load_preserves_sections(self):
        vocab = self.loader.load()
        self.assertIn('Projectes', vocab)
        self.assertIn('HONOADOOR', vocab['Projectes'])
        self.assertIn('A10Pro', vocab['Projectes'])

    def test_load_terms_without_aliases(self):
        """Termes sense aliases han d'aparèixer igualment."""
        vocab = self.loader.load()
        self.assertIn('A10Pro', vocab['Projectes'])

    def test_load_aliases_mapping(self):
        """load_aliases() retorna mapping alias → terme correcte."""
        aliases = self.loader.load_aliases()
        self.assertEqual(aliases['Monatxa'], 'Bonache')
        self.assertEqual(aliases['Borracho'], 'Bonache')
        self.assertEqual(aliases['ajudit'], 'Judith')
        self.assertEqual(aliases['congeladors'], 'HONOADOOR')
        self.assertEqual(aliases['Honoa'], 'HONOA')

    def test_load_aliases_for_arrow_acronyms_uses_canonical(self):
        """Acrònims format 'X → Y' amb aliases: el target ha de ser X (canònic),
        no la línia sencera. Així la substitució no corromp la transcripció."""
        aliases = self.loader.load_aliases()
        self.assertEqual(aliases['IEA'], 'IA')

    def test_load_config(self):
        config = self.loader.load_config()
        self.assertEqual(config.get('threshold_auto'), '0.85')

    def test_empty_aliases_when_no_indented_lines(self):
        empty_vocab = "# Sense aliases\n\n## Test\n- Sol\n- Sol2\n"
        f = tempfile.NamedTemporaryFile('w', suffix='.md', delete=False, encoding='utf-8')
        f.write(empty_vocab)
        f.close()
        try:
            loader = VocabularyLoader(Path(f.name))
            self.assertEqual(loader.load_aliases(), {})
        finally:
            Path(f.name).unlink()

    def test_missing_file_returns_empty(self):
        loader = VocabularyLoader(Path('/no/existeix.md'))
        self.assertEqual(loader.load(), {})
        self.assertEqual(loader.load_aliases(), {})

    def test_canonical_form_strips_arrow_definition(self):
        """Defensiu: si una entrada té format antic 'X → Y' i té aliases,
        el target ha de ser X (canònic), no la línia sencera."""
        legacy_vocab = """# V

## Acrònims
- IA → Intel·ligència Artificial
  - IEA
- RiD / R+D / RmesD → Recerca i Desenvolupament
  - REMESD
- Plain (definició entre parèntesis)
  - alies
"""
        import tempfile
        f = tempfile.NamedTemporaryFile('w', suffix='.md', delete=False, encoding='utf-8')
        f.write(legacy_vocab)
        f.close()
        try:
            loader = VocabularyLoader(Path(f.name))
            aliases = loader.load_aliases()
            self.assertEqual(aliases['IEA'], 'IA')
            self.assertEqual(aliases['REMESD'], 'RiD')  # primera alternativa
            self.assertEqual(aliases['alies'], 'Plain')
        finally:
            Path(f.name).unlink()

    def test_indented_entries_without_parent_treated_as_section_entries(self):
        """La secció '## Configuració' usa entries indentades sense terme pare.
        Aquestes han de tractar-se com a entries de la secció, no com a aliases."""
        config_vocab = """# V

## Configuració

  - threshold_auto: 0.95
  - altra_clau: valor

## Persones
- Bonache
  - Monatxa
"""
        import tempfile
        f = tempfile.NamedTemporaryFile('w', suffix='.md', delete=False, encoding='utf-8')
        f.write(config_vocab)
        f.close()
        try:
            loader = VocabularyLoader(Path(f.name))
            vocab = loader.load()
            self.assertIn('threshold_auto: 0.95', vocab['Configuració'])
            self.assertIn('altra_clau: valor', vocab['Configuració'])
            # I els aliases reals segueixen funcionant
            aliases = loader.load_aliases()
            self.assertEqual(aliases.get('Monatxa'), 'Bonache')
            # Però les entries de Configuració NO són aliases
            self.assertNotIn('threshold_auto: 0.95', aliases)
        finally:
            Path(f.name).unlink()


class TestAddAlias(unittest.TestCase):
    """Tests del mètode add_alias que escriu al Vocabulari.md."""

    SAMPLE = """---
type: configuracio
---

# Vocabulari

## Persones

- Bonache
  - Monatxa
- Judith

## Projectes

- HONOADOOR
  - congeladors
- KAIMAI
"""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile('w', suffix='.md', delete=False, encoding='utf-8')
        self.tmp.write(self.SAMPLE)
        self.tmp.close()
        self.loader = VocabularyLoader(Path(self.tmp.name))

    def tearDown(self):
        Path(self.tmp.name).unlink()

    def test_adds_alias_to_existing_term(self):
        changed, _ = self.loader.add_alias("queimei", "KAIMAI")
        self.assertTrue(changed)
        aliases = self.loader.load_aliases()
        self.assertEqual(aliases.get("queimei"), "KAIMAI")

    def test_adds_alias_after_existing_aliases(self):
        """El nou alias va just al final del bloc d'aliases del terme."""
        self.loader.add_alias("conelador", "HONOADOOR")
        content = Path(self.tmp.name).read_text(encoding='utf-8')
        # Conserva l'alias original i n'afegeix un de nou
        self.assertIn("- congeladors", content)
        self.assertIn("- conelador", content)
        # 'conelador' apareix DESPRÉS de 'congeladors'
        idx_first = content.index("congeladors")
        idx_second = content.index("conelador")
        self.assertLess(idx_first, idx_second)

    def test_does_not_duplicate_existing_alias(self):
        changed1, _ = self.loader.add_alias("Monatxa", "Bonache")
        self.assertFalse(changed1)  # ja existeix

    def test_creates_orphan_section_when_target_unknown(self):
        changed, _ = self.loader.add_alias("nou_alias", "TermeDesconegut")
        self.assertTrue(changed)
        content = Path(self.tmp.name).read_text(encoding='utf-8')
        self.assertIn("## Altres (per revisar)", content)
        self.assertIn("- TermeDesconegut", content)
        self.assertIn("  - nou_alias", content)

    def test_adds_to_existing_orphan_section(self):
        # Primera vegada: crea la secció
        self.loader.add_alias("alias1", "TermeA")
        # Segona vegada: s'afegeix a la mateixa secció
        self.loader.add_alias("alias2", "TermeB")
        content = Path(self.tmp.name).read_text(encoding='utf-8')
        # Només una capçalera ## Altres
        self.assertEqual(content.count("## Altres (per revisar)"), 1)
        self.assertIn("- TermeA", content)
        self.assertIn("- TermeB", content)

    def test_canonical_form_matching(self):
        """Si target té format 'X → Y' o 'X (Y)', empareix amb el terme X."""
        # Afegim un terme amb format antic per provar
        with open(self.tmp.name, 'a', encoding='utf-8') as f:
            f.write("\n## Acrònims\n- IA → Intel·ligència Artificial\n")
        loader = VocabularyLoader(Path(self.tmp.name))
        changed, _ = loader.add_alias("IEA", "IA")
        self.assertTrue(changed)
        # L'alias s'ha de poder llegir
        aliases = loader.load_aliases()
        self.assertEqual(aliases.get("IEA"), "IA")

    def test_empty_args_return_false(self):
        changed, _ = self.loader.add_alias("", "X")
        self.assertFalse(changed)
        changed, _ = self.loader.add_alias("X", "")
        self.assertFalse(changed)

    def test_preserves_frontmatter(self):
        self.loader.add_alias("queimei", "KAIMAI")
        content = Path(self.tmp.name).read_text(encoding='utf-8')
        self.assertTrue(content.startswith("---\ntype: configuracio"))


class TestAddTerm(unittest.TestCase):
    """Tests del mètode add_term: afegeix paraula al Vocabulari sense alias."""

    SAMPLE = """---
---

# V

## Persones
- Bonache

## Projectes
- HONOADOOR
"""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile('w', suffix='.md', delete=False, encoding='utf-8')
        self.tmp.write(self.SAMPLE)
        self.tmp.close()
        self.loader = VocabularyLoader(Path(self.tmp.name))

    def tearDown(self):
        Path(self.tmp.name).unlink()

    def test_adds_new_term_to_orphan_section(self):
        changed, _ = self.loader.add_term("Ferran")
        self.assertTrue(changed)
        content = Path(self.tmp.name).read_text(encoding='utf-8')
        self.assertIn("## Altres (per revisar)", content)
        self.assertIn("- Ferran", content)

    def test_term_added_without_aliases(self):
        """add_term NO ha de crear cap sublista — només el terme principal."""
        self.loader.add_term("Ferran")
        aliases = self.loader.load_aliases()
        # Cap alias mapeja a "Ferran" perquè no s'ha creat cap sublista
        for alias, target in aliases.items():
            self.assertNotEqual(target, "Ferran")

    def test_rejects_existing_term(self):
        changed, _ = self.loader.add_term("Bonache")
        self.assertFalse(changed)  # ja existeix

    def test_rejects_empty_term(self):
        changed, _ = self.loader.add_term("")
        self.assertFalse(changed)

    def test_multiple_terms_reuse_orphan_section(self):
        self.loader.add_term("Ferran")
        self.loader.add_term("Berta")
        content = Path(self.tmp.name).read_text(encoding='utf-8')
        self.assertEqual(content.count("## Altres (per revisar)"), 1)
        self.assertIn("- Ferran", content)
        self.assertIn("- Berta", content)


if __name__ == '__main__':
    unittest.main()
