"""Tests de la nota principal (hub) dels projectes: `Projectes/<X>/<X>.md`.

Només es crea automàticament per a sèries de `Projectes/` (decisió 2026-10).
Executar amb:
    uv run python -m unittest discover -s tests
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from obsidian_writer import ObsidianWriter


class TestProjectHub(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.projectes = self.tmp / "Reunions" / "Projectes"
        self.projectes.mkdir(parents=True)
        self.writer = ObsidianWriter(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _series(self, rel: str, *subdirs: str) -> Path:
        d = self.tmp / "Reunions" / rel
        (d / "Reunions").mkdir(parents=True)
        for s in subdirs:
            (d / s).mkdir()
        return d

    # -- ensure_project_hub --

    def test_creates_hub_when_missing(self):
        d = self._series("Projectes/KAIMAI", "Correus")
        path = self.writer.ensure_project_hub(d)
        self.assertEqual(path, d / "KAIMAI.md")
        text = path.read_text(encoding="utf-8")
        self.assertIn("type: hub", text)
        self.assertIn("tipus: projecte", text)
        self.assertIn("aliases: []", text)
        self.assertIn("# KAIMAI", text)
        self.assertIn("## Resum", text)
        self.assertIn("## On trobar la informació", text)
        self.assertIn("`<Any> KAIMAI.md`", text)
        self.assertIn("`Correus/`", text)
        self.assertIn("`[[KAIMAI`", text)

    def test_does_not_overwrite_existing_hub(self):
        d = self._series("Projectes/A10Pro")
        (d / "A10Pro.md").write_text("contingut de l'usuari", encoding="utf-8")
        self.assertIsNone(self.writer.ensure_project_hub(d))
        self.assertEqual((d / "A10Pro.md").read_text(encoding="utf-8"),
                         "contingut de l'usuari")

    def test_only_lists_existing_locations(self):
        d = self._series("Projectes/UWB")
        text = self.writer.ensure_project_hub(d).read_text(encoding="utf-8")
        self.assertNotIn("Correus/", text)
        self.assertNotIn("Temes oberts", text)
        self.assertNotIn("Documents:", text)

    def test_lists_temes_oberts_documents_and_subseries(self):
        d = self._series("Projectes/ARIN", "Fitxers", "Documentació")
        (d / "Temes oberts.md").write_text("### Altres temes\n", encoding="utf-8")
        self._series("Projectes/ARIN/Enfoc nova gama ARIN")
        text = self.writer.ensure_project_hub(d).read_text(encoding="utf-8")
        self.assertIn("`Temes oberts.md`", text)
        self.assertIn("`Fitxers/`, `Documentació/`", text)
        self.assertIn("[[Enfoc nova gama ARIN]]", text)

    def test_nested_project_series(self):
        d = self._series("Projectes/ARIN/Enfoc nova gama ARIN")
        self.assertEqual(self.writer.ensure_project_hub(d),
                         d / "Enfoc nova gama ARIN.md")

    def test_skips_non_project_series(self):
        for rel in ("Persones/Joan", "Proveïdors/CELO", "Clients/Profalux",
                    "Reunions vàries/Reunió qualitat"):
            d = self._series(rel)
            self.assertIsNone(self.writer.ensure_project_hub(d), rel)
            self.assertFalse((d / f"{d.name}.md").exists(), rel)

    def test_skips_templates(self):
        d = self._series("Projectes/xProjecte")
        self.assertIsNone(self.writer.ensure_project_hub(d))
        self.assertFalse((d / "xProjecte.md").exists())

    def test_skips_project_type_folder_itself(self):
        self.assertIsNone(self.writer.ensure_project_hub(self.projectes))

    # -- ensure_project_hubs (escombrat) --

    def test_sweep_creates_missing_hubs_only_in_projectes(self):
        a = self._series("Projectes/A10Pro")
        (a / "A10Pro.md").write_text("existent", encoding="utf-8")
        k = self._series("Projectes/KAIMAI")
        nested = self._series("Projectes/ARIN/Enfoc nova gama ARIN")
        self._series("Projectes/xProjecte")
        p = self._series("Persones/Joan")
        # Carpeta de projecte encara sense Reunions/ (acabada de crear): també compta.
        (self.projectes / "NOU").mkdir()

        created = self.writer.ensure_project_hubs()

        self.assertCountEqual(created, [
            k / "KAIMAI.md",
            self.projectes / "ARIN" / "ARIN.md",
            nested / "Enfoc nova gama ARIN.md",
            self.projectes / "NOU" / "NOU.md",
        ])
        self.assertEqual((a / "A10Pro.md").read_text(encoding="utf-8"), "existent")
        self.assertFalse((p / "Joan.md").exists())
        self.assertFalse((self.projectes / "xProjecte" / "xProjecte.md").exists())

    def test_sweep_ignores_structural_subfolders(self):
        d = self._series("Projectes/VDPJCM", "Documentació", "Fitxers", "Correus")
        (d / "Documentació" / "Reunions").mkdir()  # per si de cas
        created = self.writer.ensure_project_hubs()
        self.assertEqual(created, [d / "VDPJCM.md"])

    def test_sweep_idempotent(self):
        self._series("Projectes/KAIMAI")
        self.assertEqual(len(self.writer.ensure_project_hubs()), 1)
        self.assertEqual(self.writer.ensure_project_hubs(), [])

    def test_sweep_without_projectes_folder(self):
        shutil.rmtree(self.projectes)
        self.assertEqual(self.writer.ensure_project_hubs(), [])


if __name__ == "__main__":
    unittest.main()
