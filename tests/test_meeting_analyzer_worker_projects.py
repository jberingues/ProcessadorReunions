"""Tests de MeetingAnalyzerWorker: passa la llista de projectes (llegida dins
del worker, fora del fil de la GUI) a analyze/summarize per etiquetar temes.
Executar amb: uv run python -m unittest discover -s tests
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "gui"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from workers import MeetingAnalyzerWorker

PROJECTS = [("A10Pro", ["A10"])]
SERIES = Path("/vault/Reunions/Reunions vàries/Reunió qualitat")


class TestMeetingAnalyzerWorkerProjects(unittest.TestCase):
    def _run(self, worker):
        got = []
        worker.finished.connect(got.append)
        worker.run()
        return got

    def test_analyze_receives_projects_and_excludes_own_series(self):
        analyzer, obsidian = MagicMock(), MagicMock()
        obsidian.list_projects.return_value = PROJECTS
        w = MeetingAnalyzerWorker(analyzer, ["Tema"], "txt", brief=True,
                                  obsidian=obsidian, series_dir=SERIES)
        self._run(w)
        obsidian.list_projects.assert_called_once_with(exclude=SERIES)
        analyzer.analyze.assert_called_once_with(["Tema"], "txt", brief=True, projects=PROJECTS)

    def test_summarize_receives_projects(self):
        analyzer, obsidian = MagicMock(), MagicMock()
        obsidian.list_projects.return_value = PROJECTS
        w = MeetingAnalyzerWorker(analyzer, [], "txt", summarize=True,
                                  obsidian=obsidian, series_dir=SERIES)
        self._run(w)
        analyzer.summarize.assert_called_once_with("txt", brief=False, projects=PROJECTS)

    def test_without_obsidian_no_projects(self):
        analyzer = MagicMock()
        self._run(MeetingAnalyzerWorker(analyzer, [], "txt"))
        analyzer.analyze.assert_called_once_with([], "txt", brief=False, projects=[])

    def test_list_failure_still_analyzes(self):
        analyzer, obsidian = MagicMock(), MagicMock()
        obsidian.list_projects.side_effect = OSError("Drive no disponible")
        w = MeetingAnalyzerWorker(analyzer, [], "txt", obsidian=obsidian, series_dir=SERIES)
        with self.assertLogs("workers", level="ERROR"):
            got = self._run(w)
        analyzer.analyze.assert_called_once_with([], "txt", brief=False, projects=[])
        self.assertEqual(got, [analyzer.analyze.return_value])


if __name__ == "__main__":
    unittest.main()
