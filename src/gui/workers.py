import os
import logging
import litellm
from datetime import datetime, timedelta
from PySide6.QtCore import QThread, Signal

from plaud_client import (
    PlaudCLINotInstalled,
    PlaudError,
    PlaudNotAuthenticated,
)

logger = logging.getLogger(__name__)


class CalendarWorker(QThread):
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, calendar, date_from=None, date_to=None, parent=None):
        super().__init__(parent)
        self.calendar = calendar
        self.date_from = date_from
        self.date_to = date_to

    def run(self):
        try:
            now = datetime.now()
            time_min = self.date_from if self.date_from else now - timedelta(days=7)
            time_max = (self.date_to if self.date_to else now).replace(hour=23, minute=59, second=59)

            events = self.calendar.service.events().list(
                calendarId='primary',
                timeMin=time_min.isoformat() + 'Z',
                timeMax=time_max.isoformat() + 'Z',
                singleEvents=True,
                orderBy='startTime'
            ).execute().get('items', [])

            reunions = [self.calendar._parse_event(e) for e in events if 'attendees' in e]
            self.finished.emit(reunions)
        except Exception as e:
            logger.exception("CalendarWorker error")
            self.error.emit(str(e))


class CorrectionDetectWorker(QThread):
    finished = Signal(str, list)
    error = Signal(str)

    def __init__(self, corrector, transcript, reference_transcript=None,
                 semantic_context=None, parent=None):
        super().__init__(parent)
        self.corrector = corrector
        self.transcript = transcript
        self.reference_transcript = reference_transcript
        self.semantic_context = semantic_context

    def run(self):
        try:
            transcript, corrections = self.corrector.detect(
                self.transcript,
                reference_transcript=self.reference_transcript,
                semantic_context=self.semantic_context
            )
            self.finished.emit(transcript, corrections)
        except Exception as e:
            logger.exception("CorrectionDetectWorker error")
            self.error.emit(str(e))


class BatchCorrectionDetectWorker(QThread):
    note_started = Signal(int)
    note_finished = Signal(int, str, list)
    note_error = Signal(int, str)
    all_finished = Signal()

    def __init__(self, tasks: list, parent=None):
        super().__init__(parent)
        self.tasks = tasks
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        for task in self.tasks:
            if self._abort:
                break
            self.note_started.emit(task['index'])
            try:
                transcript, corrections = task['corrector'].detect(
                    task['transcript'],
                    reference_transcript=task['reference_transcript'],
                    semantic_context=task['semantic_context']
                )
                self.note_finished.emit(task['index'], transcript, corrections)
            except Exception as e:
                logger.exception("BatchCorrectionDetectWorker error a nota index=%d", task['index'])
                self.note_error.emit(task['index'], str(e))
        self.all_finished.emit()


class DailyProcessorWorker(QThread):
    finished = Signal(object, str)
    error = Signal(str)

    def __init__(self, processor, transcript, attendees, meeting_title, date_str, parent=None):
        super().__init__(parent)
        self.processor = processor
        self.transcript = transcript
        self.attendees = attendees
        self.meeting_title = meeting_title
        self.date_str = date_str

    def run(self):
        try:
            result = self.processor.process(self.transcript, self.attendees)
            md_output = self.processor.format_markdown(result, self.meeting_title, self.date_str)
            self.finished.emit(result, md_output)
        except Exception as e:
            logger.exception("DailyProcessorWorker error")
            self.error.emit(str(e))


class MeetingAnalyzerWorker(QThread):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, analyzer, topics, transcript, parent=None, brief=False):
        super().__init__(parent)
        self.analyzer = analyzer
        self.topics = topics
        self.transcript = transcript
        self.brief = brief

    def run(self):
        try:
            result = self.analyzer.analyze(self.topics, self.transcript, brief=self.brief)
            self.finished.emit(result)
        except Exception as e:
            logger.exception("MeetingAnalyzerWorker error")
            self.error.emit(str(e))


class GmailWorker(QThread):
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, fetcher, date_from, date_to, parent=None):
        super().__init__(parent)
        self.fetcher = fetcher
        self.date_from = date_from
        self.date_to = date_to

    def run(self):
        try:
            threads = self.fetcher.fetch_threads(self.date_from, self.date_to)
            self.finished.emit(threads)
        except Exception as e:
            logger.exception("GmailWorker error")
            self.error.emit(str(e))


class ProjectInitWorker(QThread):
    finished = Signal(object)  # ProjectDefinition
    error = Signal(str)

    def __init__(self, project_name: str, sources: list, parent=None):
        super().__init__(parent)
        self.project_name = project_name
        self.sources = sources

    def run(self):
        try:
            from project_definition_extractor import ProjectDefinitionExtractor
            extractor = ProjectDefinitionExtractor()
            result = extractor.extract(self.project_name, self.sources)
            self.finished.emit(result)
        except Exception as e:
            logger.exception("ProjectInitWorker error")
            self.error.emit(str(e))


class SummaryWorker(QThread):
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, transcript, parent=None):
        super().__init__(parent)
        self.transcript = transcript

    def run(self):
        try:
            response = litellm.completion(
                model=os.getenv('LLM_MODELH'),
                messages=[{
                    "role": "user",
                    "content": (
                        "Analitza el text següent i fes un resum estructurat en català.\n"
                        "Per cada tema diferent que s'hagi tractat:\n"
                        "1. Posa un titular amb el format exacte: ##### Nom del tema\n"
                        "2. Sota el titular, afegeix un resum de màxim 3 bullets (-) amb els punts més importants.\n"
                        "Detecta els temes de forma natural a partir del contingut.\n"
                        "Sense introducció ni conclusió. Sense línies buides entre temes.\n\n"
                        f"{self.transcript}"
                    )
                }]
            )
            summary = response.choices[0].message.content.strip()
            self.finished.emit(summary)
        except Exception as e:
            logger.exception("SummaryWorker error")
            self.error.emit(str(e))


class PlaudListWorker(QThread):
    """Llista gravacions Plaud d'un dia i resol `start_at` UTC per cadascuna.

    Aquest pre-càlcul deixa les gravacions a punt per al MeetingRecordingMatcher
    (que necessita `start_at` per puntuar parells). Emet un senyal de progrés
    per cada metadada resolta perquè la UI pugui mostrar "3/5 carregades".
    """
    progress = Signal(int, int)        # (carregades, total)
    finished = Signal(list)            # list[PlaudRecording]
    error = Signal(str)
    not_authenticated = Signal()

    def __init__(self, client, target_date, parent=None):
        super().__init__(parent)
        self.client = client
        self.target_date = target_date

    def run(self):
        try:
            recordings = self.client.list_for_date(self.target_date)
            total = len(recordings)
            self.progress.emit(0, total)
            for i, rec in enumerate(recordings, start=1):
                if rec.start_at is None:
                    rec.start_at = self.client.get_start_at_utc(rec.file_id)
                self.progress.emit(i, total)
            self.finished.emit(recordings)
        except PlaudNotAuthenticated:
            self.not_authenticated.emit()
        except (PlaudCLINotInstalled, PlaudError) as e:
            logger.exception("PlaudListWorker error")
            self.error.emit(str(e))
        except Exception as e:
            logger.exception("PlaudListWorker unexpected error")
            self.error.emit(str(e))


class PlaudTranscriptWorker(QThread):
    """Baixa la transcripció d'una gravació Plaud concreta."""
    finished = Signal(str, str)        # (file_id, transcript)
    error = Signal(str, str)           # (file_id, msg)
    not_authenticated = Signal()

    def __init__(self, client, file_id, parent=None):
        super().__init__(parent)
        self.client = client
        self.file_id = file_id

    def run(self):
        try:
            text = self.client.get_transcript(self.file_id)
            self.finished.emit(self.file_id, text)
        except PlaudNotAuthenticated:
            self.not_authenticated.emit()
        except (PlaudCLINotInstalled, PlaudError) as e:
            logger.exception("PlaudTranscriptWorker error")
            self.error.emit(self.file_id, str(e))
        except Exception as e:
            logger.exception("PlaudTranscriptWorker unexpected error")
            self.error.emit(self.file_id, str(e))
