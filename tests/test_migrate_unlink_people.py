"""Tests de scripts/migrate_unlink_people.py: treu els links de persona
(attendees del frontmatter, línia **Assistents:**, encapçalaments per persona
dels anuals de Sincronització) i deixa la resta de links intactes.
Executar amb: uv run python -m unittest discover -s tests
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from migrate_unlink_people import unlink_people, migrate

NOTE = """---
date: 2026-10-05
title: "Reunió [[no és assistent]]"
attendees:
  - "[[Jordi Beringues]]"
  - "[[Jordi Beringues ]]"
  - "Maria"
  - "[[adv@trc.com]]"
speaker_emails:
  j@x.com: "Jordi Beringues"
---

# Reunió

**Data:** 2026-10-05 09:30
**Assistents:** [[Jordi Beringues]], [[Pere Coma|Pere]], Maria
**Durada:** 1:00:00

Text amb [[un link qualsevol]].
"""

EXPECTED = """---
date: 2026-10-05
title: "Reunió [[no és assistent]]"
attendees:
  - "Jordi Beringues"
  - "Jordi Beringues"
  - "Maria"
  - "adv@trc.com"
speaker_emails:
  j@x.com: "Jordi Beringues"
---

# Reunió

**Data:** 2026-10-05 09:30
**Assistents:** Jordi Beringues, Pere, Maria
**Durada:** 1:00:00

Text amb [[un link qualsevol]].
"""

YEAR = """---
type: resum_anual
---
## 261005 - Sincro
##### [[Raül Trullà]]
**Ahir:**
- Feina [[A10Pro]]
## [[Jordi Beringues]]
- **Projectes:** [[A10Pro]], [[R4G]]
- [[Fitxers/260422_doc.pdf]]
"""


class TestUnlinkPeople(unittest.TestCase):
    def test_meeting_note(self):
        new, n = unlink_people(NOTE)
        self.assertEqual(new, EXPECTED)
        self.assertEqual(n, 5)  # 3 a attendees + 2 a Assistents

    def test_person_headings_only(self):
        new, n = unlink_people(YEAR)
        self.assertIn("##### Raül Trullà\n", new)
        self.assertIn("## Jordi Beringues\n", new)
        # Links a projectes, fitxers i text no es toquen.
        self.assertIn("- Feina [[A10Pro]]", new)
        self.assertIn("- **Projectes:** [[A10Pro]], [[R4G]]", new)
        self.assertIn("- [[Fitxers/260422_doc.pdf]]", new)
        self.assertEqual(n, 2)

    def test_heading_with_text_besides_link_untouched(self):
        text = "## 261005 - [[Algú]] i més\n"
        self.assertEqual(unlink_people(text), (text, 0))

    def test_idempotent(self):
        once, _ = unlink_people(NOTE)
        self.assertEqual(unlink_people(once), (once, 0))

    def test_attendees_block_ends_at_next_key(self):
        text = '---\nattendees:\n  - "[[A]]"\naltres:\n  - "[[B]]"\n---\n'
        self.assertEqual(unlink_people(text)[0], '---\nattendees:\n  - "A"\naltres:\n  - "[[B]]"\n---\n')

    def test_several_links_in_one_attendee_item(self):
        text = '---\nattendees:\n  - "[[Karel Vogel]], [[Jordi Beringues]]"\n---\n'
        self.assertEqual(unlink_people(text), ('---\nattendees:\n  - "Karel Vogel, Jordi Beringues"\n---\n', 2))

    def test_attendees_outside_frontmatter_untouched(self):
        text = '# Nota\n\nattendees:\n  - "[[A]]"\n'
        self.assertEqual(unlink_people(text), (text, 0))


class TestMigrate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        r = self.tmp / "Reunions"
        self.note = r / "Persones" / "Joan" / "Reunions" / "261005_Joan*.md"
        self.note.parent.mkdir(parents=True)
        self.note.write_text(NOTE, encoding="utf-8")
        self.year = r / "Sincronització" / "OT" / "2026 OT.md"
        self.year.parent.mkdir(parents=True)
        self.year.write_text(YEAR, encoding="utf-8")
        self.tpl = r / "Persones" / "xSeguiment" / "x.md"
        self.tpl.parent.mkdir(parents=True)
        self.tpl.write_text(NOTE, encoding="utf-8")
        self.clean = r / "Projectes" / "A10Pro" / "A10Pro.md"
        self.clean.parent.mkdir(parents=True)
        self.clean.write_text("# A10Pro\n- **Projectes:** [[R4G]]\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_dry_run_writes_nothing(self):
        files, links = migrate(self.tmp, apply=False, log=lambda m: None)
        self.assertEqual((files, links), (2, 7))
        self.assertEqual(self.note.read_text(encoding="utf-8"), NOTE)

    def test_apply(self):
        migrate(self.tmp, apply=True, log=lambda m: None)
        self.assertEqual(self.note.read_text(encoding="utf-8"), EXPECTED)
        self.assertIn("##### Raül Trullà", self.year.read_text(encoding="utf-8"))
        # Plantilles x… i fitxers sense links de persona no es toquen.
        self.assertEqual(self.tpl.read_text(encoding="utf-8"), NOTE)
        self.assertEqual(migrate(self.tmp, apply=True, log=lambda m: None), (0, 0))


if __name__ == "__main__":
    unittest.main()
