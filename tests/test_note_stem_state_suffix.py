"""Tests per a la salvaguarda de _note_stem: si el títol acaba en un sufix
d'estat (~ + *) s'hi afegeix un '_' final perquè no es confongui amb el marcador
d'estat (e.g. un títol "Vigik+" trencaria el cicle de vida de la nota).
Executar amb:
    uv run python -m unittest discover -s tests
"""
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from obsidian_writer import ObsidianWriter


class TestNoteStemStateSuffix(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.target = self.tmp / "Reunions" / "Reunions vàries" / "X" / "Reunions"
        self.target.mkdir(parents=True)
        self.writer = ObsidianWriter(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _meeting(self, title: str) -> dict:
        return {
            "title": title,
            "start": datetime(2026, 6, 19, 11, 34),
            "end": datetime(2026, 6, 19, 12, 0),
            "duration": "0:26:00",
            "attendees": [],
        }

    def test_plus_suffix_gets_underscore(self):
        stem = self.writer._note_stem(self._meeting("Desencallar Vigik+"))
        self.assertEqual(stem, "260619_Desencallar_Vigik+_")

    def test_tilde_suffix_gets_underscore(self):
        stem = self.writer._note_stem(self._meeting("Memòria~"))
        self.assertEqual(stem, "260619_Memòria~_")

    def test_normal_title_unchanged(self):
        stem = self.writer._note_stem(self._meeting("Reunió normal"))
        self.assertEqual(stem, "260619_Reunió_normal")

    def test_asterisk_already_stripped_by_clean(self):
        # '*' és caràcter prohibit en noms de fitxer i ja l'elimina _clean, així
        # que no cal sufix '_'.
        stem = self.writer._note_stem(self._meeting("Producte*"))
        self.assertEqual(stem, "260619_Producte")

    def test_created_note_does_not_collide_with_state(self):
        # La nota creada per a un títol "Vigik+" NO ha d'acabar en '+' (estat).
        m = self._meeting("Desencallar Vigik+")
        self.writer.create_simple_note(m, "transcripció", self.target)
        created = list(self.target.glob("*.md"))
        self.assertEqual(len(created), 1)
        self.assertFalse(created[0].stem.endswith("+"))
        # No apareix com a pendent de consolidar...
        self.assertEqual(self.writer.find_pending_consolidation_notes(), [])
        # ...sinó com a no corregida (pendent de correcció).
        uncorrected = self.writer.find_uncorrected_notes()
        self.assertEqual(len(uncorrected), 1)

    def test_roundtrip_find_existing_note(self):
        # find_existing_note usa el mateix _note_stem → detecta el fitxer creat.
        m = self._meeting("Desencallar Vigik+")
        self.writer.create_simple_note(m, "transcripció", self.target)
        self.assertIsNotNone(self.writer.find_existing_note(m, self.target))


if __name__ == "__main__":
    unittest.main()
