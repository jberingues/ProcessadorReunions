"""Tests del cicle de vida de notes amb el sufix '+' (pendent de consolidar).

Estats: sense sufix (introduïda) → '~' (corregida) → '+' (ordre del dia
generat, pendent de consolidar) → '*' (consolidada). Executar amb:
    uv run python -m unittest discover -s tests
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from obsidian_writer import ObsidianWriter


class TestNoteLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.reunions = self.tmp / "Reunions" / "Seguiment" / "A10Pro" / "Reunions"
        self.reunions.mkdir(parents=True)
        self.writer = ObsidianWriter(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _note(self, name: str) -> Path:
        p = self.reunions / name
        p.write_text("x", encoding="utf-8")
        return p

    # -- mark_as_ordre_generated: ~ → + --

    def test_mark_ordre_generated_from_corrected(self):
        p = self._note("260520_Reunio~.md")
        new = self.writer.mark_as_ordre_generated(p)
        self.assertEqual(new.name, "260520_Reunio+.md")
        self.assertFalse(p.exists())

    def test_mark_ordre_generated_without_suffix(self):
        p = self._note("260520_Reunio.md")
        new = self.writer.mark_as_ordre_generated(p)
        self.assertEqual(new.name, "260520_Reunio+.md")

    # -- mark_as_processed: + → * (i ~ → *) --

    def test_mark_processed_from_pending(self):
        p = self._note("260520_Reunio+.md")
        new = self.writer.mark_as_processed(p)
        self.assertEqual(new.name, "260520_Reunio*.md")

    def test_mark_processed_from_corrected(self):
        p = self._note("260520_Reunio~.md")
        new = self.writer.mark_as_processed(p)
        self.assertEqual(new.name, "260520_Reunio*.md")

    def test_mark_processed_without_suffix(self):
        p = self._note("260520_Reunio.md")
        new = self.writer.mark_as_processed(p)
        self.assertEqual(new.name, "260520_Reunio*.md")

    # -- find_pending_consolidation_notes --

    def test_find_pending_only_plus(self):
        self._note("260520_Reunio_A~.md")        # corregida
        self._note("260521_Reunio_B+.md")        # pendent
        self._note("260522_Reunio_C*.md")        # consolidada
        self._note("260523_Reunio_D.md")         # introduïda
        pending = self.writer.find_pending_consolidation_notes()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["date"], "260521")
        self.assertEqual(pending[0]["title"], "Reunio B")
        self.assertEqual(pending[0]["path"].name, "260521_Reunio_B+.md")

    def test_find_pending_sorted_desc(self):
        self._note("260101_Antiga+.md")
        self._note("260601_Recent+.md")
        pending = self.writer.find_pending_consolidation_notes()
        self.assertEqual([n["date"] for n in pending], ["260601", "260101"])

    def test_find_pending_ignores_zconfig(self):
        cfg = self.tmp / "Reunions" / "zConfig" / "Reunions"
        cfg.mkdir(parents=True)
        (cfg / "260520_X+.md").write_text("x", encoding="utf-8")
        self.assertEqual(self.writer.find_pending_consolidation_notes(), [])

    # -- ensure_temes_oberts --

    def test_ensure_temes_oberts_creates_when_missing(self):
        series = self.reunions.parent  # .../A10Pro
        path = self.writer.ensure_temes_oberts(series)
        self.assertTrue(path.exists())
        self.assertEqual(path.read_text(encoding="utf-8"), "### Altres temes\n")

    def test_ensure_temes_oberts_idempotent(self):
        series = self.reunions.parent
        existing = series / "Temes oberts.md"
        existing.write_text("### Tema A\n\n### Altres temes\n", encoding="utf-8")
        path = self.writer.ensure_temes_oberts(series)
        # No sobreescriu el contingut existent.
        self.assertEqual(path.read_text(encoding="utf-8"), "### Tema A\n\n### Altres temes\n")

    # -- find_uncorrected_notes exclou '+' --

    def test_uncorrected_excludes_pending(self):
        self._note("260520_Pendent+.md")
        self._note("260521_Nova.md")
        uncorrected = self.writer.find_uncorrected_notes()
        names = {n["path"].name for n in uncorrected}
        self.assertEqual(names, {"260521_Nova.md"})


if __name__ == "__main__":
    unittest.main()
