"""Tests de l'etiquetatge de projectes a la fase 1 (decisió 2026-10):
- ObsidianWriter.list_projects: llegeix nom + àlies de les notes principals.
- projects_prompt_section: bloc del prompt amb la llista de projectes.
- normalize_projects: àlies → nom canònic, descarta noms inexistents.
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
from meeting_analyzer import (
    ActiveTopicUpdate,
    MeetingAnalysisResult,
    normalize_projects,
    projects_prompt_section,
)


def _hub(d: Path, frontmatter: str | None):
    (d / "Reunions").mkdir(parents=True)
    if frontmatter is not None:
        (d / f"{d.name}.md").write_text(f"---\n{frontmatter}\n---\n# {d.name}\n", encoding="utf-8")


class TestListProjects(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.p = self.tmp / "Reunions" / "Projectes"
        self.p.mkdir(parents=True)
        self.writer = ObsidianWriter(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_reads_names_and_aliases(self):
        _hub(self.p / "A10Pro", "type: hub\naliases: [A10 Pro, A10]")
        _hub(self.p / "KAIMAI", "type: hub\naliases: []")
        self.assertEqual(self.writer.list_projects(),
                         [("A10Pro", ["A10 Pro", "A10"]), ("KAIMAI", [])])

    def test_alias_as_single_string_and_block_list(self):
        _hub(self.p / "R4G", "aliases:\n  - Radioband4\n  - RBAND4")
        _hub(self.p / "UWB", "aliases: Ultra Wide Band")
        self.assertEqual(self.writer.list_projects(),
                         [("R4G", ["Radioband4", "RBAND4"]), ("UWB", ["Ultra Wide Band"])])

    def test_project_without_hub_or_frontmatter(self):
        _hub(self.p / "NOU", None)
        (self.p / "VELL" / "Reunions").mkdir(parents=True)
        (self.p / "VELL" / "VELL.md").write_text("# VELL sense frontmatter\n", encoding="utf-8")
        self.assertEqual(self.writer.list_projects(), [("NOU", []), ("VELL", [])])

    def test_broken_frontmatter_does_not_fail(self):
        _hub(self.p / "ROT", "aliases: [sense tancar")
        self.assertEqual(self.writer.list_projects(), [("ROT", [])])

    def test_nested_series_and_templates(self):
        _hub(self.p / "ARIN", "aliases: []")
        _hub(self.p / "ARIN" / "Enfoc nova gama ARIN", "aliases: [Nova gama]")
        _hub(self.p / "xProjecte", None)
        (self.p / "VDPJCM" / "Documentació").mkdir(parents=True)
        self.assertEqual(self.writer.list_projects(), [
            ("ARIN", []), ("Enfoc nova gama ARIN", ["Nova gama"]), ("VDPJCM", []),
        ])

    def test_exclude_own_series(self):
        _hub(self.p / "A10Pro", "aliases: [A10]")
        _hub(self.p / "R4G", "aliases: []")
        self.assertEqual(self.writer.list_projects(exclude=self.p / "A10Pro"), [("R4G", [])])

    def test_no_projectes_folder(self):
        shutil.rmtree(self.p)
        self.assertEqual(self.writer.list_projects(), [])


PROJECTS = [("A10Pro", ["A10 Pro", "A10"]), ("VDPJCM", ["HONOACALL"]), ("KAIMAI", [])]


class TestProjectsPromptSection(unittest.TestCase):
    def test_empty_when_no_projects(self):
        self.assertEqual(projects_prompt_section([]), "")

    def test_lists_projects_with_aliases(self):
        text = projects_prompt_section(PROJECTS)
        self.assertIn("- A10Pro (també: A10 Pro, A10)", text)
        self.assertIn("- VDPJCM (també: HONOACALL)", text)
        self.assertIn("- KAIMAI\n", text + "\n")
        self.assertIn("projects", text)


class TestNormalizeProjects(unittest.TestCase):
    def _r(self, projects, others=None):
        return MeetingAnalysisResult(
            updated_topics=[ActiveTopicUpdate(topic_name="T", summary="S", projects=projects)],
            new_other_topics=others or [],
        )

    def test_keeps_canonical_names(self):
        r = normalize_projects(self._r(["A10Pro", "VDPJCM"]), PROJECTS)
        self.assertEqual(r.updated_topics[0].projects, ["A10Pro", "VDPJCM"])

    def test_alias_to_canonical_case_insensitive(self):
        r = normalize_projects(self._r(["honoacall", "A10 Pro"]), PROJECTS)
        self.assertEqual(r.updated_topics[0].projects, ["VDPJCM", "A10Pro"])

    def test_strips_brackets_and_drops_unknown(self):
        r = normalize_projects(self._r(["[[A10Pro]]", "Inventat"]), PROJECTS)
        self.assertEqual(r.updated_topics[0].projects, ["A10Pro"])

    def test_dedupes(self):
        r = normalize_projects(self._r(["A10", "A10Pro", "a10pro"]), PROJECTS)
        self.assertEqual(r.updated_topics[0].projects, ["A10Pro"])

    def test_no_projects_list_clears_all(self):
        # Sense llista (lectura fallida) no es pot validar res → sense links.
        r = normalize_projects(self._r(["A10Pro"]), [])
        self.assertEqual(r.updated_topics[0].projects, [])

    def test_inline_links_in_other_topics_validated(self):
        r = normalize_projects(
            self._r([], others=["Tema nou de l'A10 [[A10]]", "Un altre [[Inventat]]", "Sense link"]),
            PROJECTS,
        )
        self.assertEqual(r.new_other_topics,
                         ["Tema nou de l'A10 [[A10Pro]]", "Un altre", "Sense link"])


if __name__ == "__main__":
    unittest.main()
