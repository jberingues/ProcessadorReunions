"""Tests de la preparació del batch de correcció fora del fil de la GUI.

Regressió (2026-08-28): `_prepare_and_start_batch` feia tota la I/O del vault
al fil principal — vocabulari, transcripció, resums anuals de referència i
`build_if_stale` de la memòria semàntica, per cada nota seleccionada. Amb el
vault a Google Drive (CloudStorage) cada lectura pot ser una descàrrega: una
mostra del procés amb `sample` mostrava el fil de la GUI bloquejat dins d'un
`read()` cridat des del slot d'un clic → finestra congelada minuts sense cap
pista. Ara tot això viu a `BatchCorrectionPrepareWorker` i la GUI només pinta
el progrés.

Executar amb: uv run python -m unittest discover -s tests
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "gui"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
    _HAS_QT = True
except Exception:  # pragma: no cover - entorn sense Qt
    _HAS_QT = False


def _note(path_str, date, title):
    return {'path': Path(path_str), 'date': date, 'title': title}


def _notes(n=2):
    base = "/v/Reunions/Seguiment/A/Reunions"
    return [_note(f"{base}/26060{i}_n{i}~.md", f'26060{i}', f'n{i}')
            for i in range(1, n + 1)]


@unittest.skipUnless(_HAS_QT, "PySide6 no disponible")
class TestPrepareWorker(unittest.TestCase):
    """El worker fa la I/O i reporta per nota, sense tallar el batch als errors."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _worker(self, notes, obsidian):
        from workers import BatchCorrectionPrepareWorker
        return BatchCorrectionPrepareWorker(obsidian, notes, Path('/v/Vocabulari.md'))

    def _obsidian(self):
        o = MagicMock()
        o.read_transcript.side_effect = lambda p: f"transcript de {p.name}"
        o.read_recent_year_blocks.return_value = "## 2026-06-01 - ref"
        return o

    def _run(self, worker):
        """Executa run() en aquest fil i recull els senyals emesos."""
        prepared, errors, progress, failed, finished = [], [], [], [], []
        worker.note_prepared.connect(lambda i, t: prepared.append((i, t)))
        worker.note_error.connect(lambda i, m: errors.append((i, m)))
        worker.progress.connect(lambda d, t: progress.append((d, t)))
        worker.failed.connect(failed.append)
        worker.all_finished.connect(lambda: finished.append(True))
        with patch('vocabulary_loader.VocabularyLoader') as loader_cls, \
             patch('transcript_corrector.TranscriptCorrector') as corrector_cls, \
             patch('semantic_memory_builder.SemanticMemoryBuilder') as builder_cls, \
             patch('semantic_context_retriever.SemanticContextRetriever') as retriever_cls:
            loader_cls.return_value.load.return_value = {'JCM': []}
            loader_cls.return_value.load_config.return_value = {'threshold_auto': '0.9'}
            worker.run()
        return {
            'prepared': prepared, 'errors': errors, 'progress': progress,
            'failed': failed, 'finished': finished,
            'loader_cls': loader_cls, 'corrector_cls': corrector_cls,
            'builder_cls': builder_cls, 'retriever_cls': retriever_cls,
        }

    def test_prepara_totes_les_notes(self):
        obsidian = self._obsidian()
        out = self._run(self._worker(_notes(2), obsidian))

        self.assertEqual(len(out['prepared']), 2)
        self.assertEqual(out['errors'], [])
        self.assertEqual(out['progress'], [(1, 2), (2, 2)])
        self.assertTrue(out['finished'])

        idx, task = out['prepared'][0]
        self.assertEqual(idx, 0)
        self.assertEqual(task['index'], 0)
        self.assertEqual(task['transcript'], "transcript de 260601_n1~.md")
        self.assertEqual(task['reference_summary'], "## 2026-06-01 - ref")
        self.assertEqual(task['meeting_dir'], Path("/v/Reunions/Seguiment/A"))
        self.assertIsNotNone(task['corrector'])
        self.assertIsNotNone(task['semantic_context'])

        # La memòria semàntica es (re)construeix aquí, no a la GUI.
        out['builder_cls'].return_value.build_if_stale.assert_called_with(
            Path("/v/Reunions/Seguiment/A"))
        # El threshold surt de la config del Vocabulari.
        self.assertEqual(
            out['corrector_cls'].call_args.kwargs['threshold_auto'], 0.9)

    def test_error_en_una_nota_no_atura_la_resta(self):
        obsidian = self._obsidian()
        obsidian.read_transcript.side_effect = [
            IOError("Google Drive no respon"), "transcript ok"
        ]
        out = self._run(self._worker(_notes(2), obsidian))

        self.assertEqual([i for i, _ in out['errors']], [0])
        self.assertIn("Google Drive", out['errors'][0][1])
        self.assertEqual([i for i, _ in out['prepared']], [1])
        self.assertEqual(out['progress'], [(1, 2), (2, 2)])
        self.assertTrue(out['finished'])

    def test_vocabulari_illegible_avorta_amb_failed(self):
        worker = self._worker(_notes(2), self._obsidian())
        failed, prepared, finished = [], [], []
        worker.failed.connect(failed.append)
        worker.note_prepared.connect(lambda i, t: prepared.append(i))
        worker.all_finished.connect(lambda: finished.append(True))
        with patch('vocabulary_loader.VocabularyLoader') as loader_cls:
            loader_cls.return_value.load.side_effect = IOError("vocabulari KO")
            worker.run()

        self.assertEqual(len(failed), 1)
        self.assertIn("vocabulari KO", failed[0])
        self.assertEqual(prepared, [])
        self.assertEqual(finished, [], "sense batch a fer, no s'emet all_finished")

    def test_abort_atura_el_bucle(self):
        worker = self._worker(_notes(3), self._obsidian())
        worker.abort()
        out = self._run(worker)

        self.assertEqual(out['prepared'], [])
        self.assertTrue(out['finished'])


@unittest.skipUnless(_HAS_QT, "PySide6 no disponible")
class TestWizardNoIOAlFilPrincipal(unittest.TestCase):
    """El wizard delega: cap lectura del vault al slot del botó."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _wizard(self, notes):
        from wizard_correccio import WizardCorreccio
        obsidian = MagicMock()
        obsidian.vault = Path('/v')
        obsidian.find_uncorrected_notes.return_value = notes
        return WizardCorreccio(obsidian), obsidian

    def test_prepare_delega_al_worker_i_no_llegeix_el_vault(self):
        notes = _notes(2)
        wizard, obsidian = self._wizard(notes)
        with patch('wizard_correccio.BatchCorrectionPrepareWorker') as worker_cls, \
             patch('wizard_correccio.BatchCorrectionDetectWorker') as detect_cls:
            wizard._prepare_and_start_batch([0, 1])

        obsidian.read_transcript.assert_not_called()
        obsidian.read_recent_year_blocks.assert_not_called()
        detect_cls.assert_not_called()

        worker_cls.assert_called_once()
        args = worker_cls.call_args.args
        self.assertIs(args[0], obsidian)
        self.assertEqual(args[1], notes)
        self.assertEqual(args[2], Path('/v/Reunions/zConfig/Vocabulari.md'))
        worker_cls.return_value.start.assert_called_once()

        # Files pintades i marcades com a "preparant" abans de tenir dades.
        self.assertEqual(wizard.table_batch.rowCount(), 2)
        self.assertEqual(wizard.table_batch.item(0, 2).text(), "Preparant...")
        self.assertEqual(
            [r.status for r in wizard.batch_results.values()],
            ['preparing', 'preparing'])
        wizard.deleteLater()

    def test_note_prepared_omple_la_fila_i_acumula_la_tasca(self):
        notes = _notes(1)
        wizard, _ = self._wizard(notes)
        with patch('wizard_correccio.BatchCorrectionPrepareWorker'):
            wizard._prepare_and_start_batch([0])

        corrector = MagicMock()
        wizard._on_note_prepared(0, {
            'index': 0, 'corrector': corrector, 'transcript': 'text',
            'reference_summary': None, 'semantic_context': None,
            'meeting_dir': Path('/v/Reunions/Seguiment/A'),
        })

        result = wizard.batch_results[0]
        self.assertEqual(result.status, 'pending')
        self.assertEqual(result.transcript, 'text')
        self.assertIs(result.corrector, corrector)
        self.assertEqual(wizard.table_batch.item(0, 2).text(), "Pendent")
        self.assertEqual(len(wizard._prepared_tasks), 1)
        wizard.deleteLater()

    def test_finish_arrenca_la_deteccio_amb_les_tasques_preparades(self):
        notes = _notes(2)
        wizard, _ = self._wizard(notes)
        with patch('wizard_correccio.BatchCorrectionPrepareWorker'):
            wizard._prepare_and_start_batch([0, 1])
        wizard._on_note_prepared(0, {
            'index': 0, 'corrector': MagicMock(), 'transcript': 't0',
            'reference_summary': None, 'semantic_context': None,
            'meeting_dir': Path('/v/Reunions/Seguiment/A'),
        })
        wizard._on_note_error(1, "lectura fallida")

        with patch('wizard_correccio.BatchCorrectionDetectWorker') as detect_cls:
            wizard._on_prepare_finished()

        detect_cls.assert_called_once()
        tasks = detect_cls.call_args.args[0]
        self.assertEqual([t['index'] for t in tasks], [0])
        detect_cls.return_value.start.assert_called_once()
        # La nota que ha fallat preparant-se ja compta com a feta a la barra.
        self.assertEqual(wizard.progress_batch.value(), 1)
        self.assertIsNone(wizard.prepare_worker)
        wizard.deleteLater()

    def test_sense_tasques_preparades_no_arrenca_la_deteccio(self):
        notes = _notes(1)
        wizard, _ = self._wizard(notes)
        with patch('wizard_correccio.BatchCorrectionPrepareWorker'):
            wizard._prepare_and_start_batch([0])
        wizard._on_note_error(0, "lectura fallida")

        with patch('wizard_correccio.BatchCorrectionDetectWorker') as detect_cls:
            wizard._on_prepare_finished()

        detect_cls.assert_not_called()
        self.assertIn("Cap nota preparada", wizard.lbl_batch_status.text())
        wizard.deleteLater()

    def test_failed_marca_totes_les_notes_com_a_error(self):
        notes = _notes(2)
        wizard, _ = self._wizard(notes)
        with patch('wizard_correccio.BatchCorrectionPrepareWorker'):
            wizard._prepare_and_start_batch([0, 1])

        wizard._on_prepare_failed("vocabulari KO")

        self.assertEqual(
            [r.status for r in wizard.batch_results.values()], ['error', 'error'])
        self.assertIn("vocabulari KO", wizard.lbl_batch_status.text())
        self.assertIsNone(wizard.prepare_worker)
        wizard.deleteLater()


@unittest.skipUnless(_HAS_QT, "PySide6 no disponible")
class TestAbortarLaPreparacio(unittest.TestCase):
    """Enrere/tancar han de desvincular el worker de preparació.

    Si només s'abortés, una lectura penjada a Google Drive pot tornar minuts
    després i escriure dins d'un batch_results que la selecció nova ja ha
    reiniciat."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _wizard_preparant(self):
        from wizard_correccio import WizardCorreccio
        obsidian = MagicMock()
        obsidian.vault = Path('/v')
        obsidian.find_uncorrected_notes.return_value = _notes(2)
        wizard = WizardCorreccio(obsidian)
        with patch('wizard_correccio.BatchCorrectionPrepareWorker') as worker_cls:
            worker_cls.return_value.wait.return_value = False  # no acaba a temps
            wizard.stack.setCurrentIndex(1)
            wizard._prepare_and_start_batch([0, 1])
        return wizard, wizard.prepare_worker

    def test_go_back_desvincula_el_worker(self):
        wizard, worker = self._wizard_preparant()
        with patch('wizard_correccio.QMessageBox.question') as q, \
             patch('wizard_correccio.detach_worker') as detach:
            from PySide6.QtWidgets import QMessageBox
            q.return_value = QMessageBox.StandardButton.Yes
            wizard._go_back()

        worker.abort.assert_called_once()
        detach.assert_called_once_with(worker)
        self.assertIsNone(wizard.prepare_worker)
        self.assertEqual(wizard.stack.currentIndex(), 0)
        wizard.deleteLater()

    def test_go_back_cancellat_manté_la_preparacio(self):
        wizard, worker = self._wizard_preparant()
        with patch('wizard_correccio.QMessageBox.question') as q, \
             patch('wizard_correccio.detach_worker') as detach:
            from PySide6.QtWidgets import QMessageBox
            q.return_value = QMessageBox.StandardButton.No
            wizard._go_back()

        worker.abort.assert_not_called()
        detach.assert_not_called()
        self.assertIs(wizard.prepare_worker, worker)
        self.assertEqual(wizard.stack.currentIndex(), 1)
        wizard.deleteLater()

    def test_confirm_close_desvincula_el_worker(self):
        wizard, worker = self._wizard_preparant()
        with patch('wizard_correccio.QMessageBox.question') as q, \
             patch('wizard_correccio.detach_worker') as detach:
            from PySide6.QtWidgets import QMessageBox
            q.return_value = QMessageBox.StandardButton.Yes
            self.assertTrue(wizard._confirm_close())

        worker.abort.assert_called_once()
        detach.assert_called_once_with(worker)
        self.assertIsNone(wizard.prepare_worker)
        wizard.deleteLater()


if __name__ == '__main__':
    unittest.main()
