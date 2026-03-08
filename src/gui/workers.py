import os
import litellm
from datetime import datetime, timedelta
from PySide6.QtCore import QThread, Signal


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
            self.error.emit(str(e))


class CorrectionDetectWorker(QThread):
    finished = Signal(str, list)
    error = Signal(str)

    def __init__(self, corrector, transcript, reference_transcript=None, parent=None):
        super().__init__(parent)
        self.corrector = corrector
        self.transcript = transcript
        self.reference_transcript = reference_transcript

    def run(self):
        try:
            transcript, corrections = self.corrector.detect(
                self.transcript,
                reference_transcript=self.reference_transcript
            )
            self.finished.emit(transcript, corrections)
        except Exception as e:
            self.error.emit(str(e))


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
            self.error.emit(str(e))


class MeetingAnalyzerWorker(QThread):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, analyzer, topics, transcript, parent=None):
        super().__init__(parent)
        self.analyzer = analyzer
        self.topics = topics
        self.transcript = transcript

    def run(self):
        try:
            result = self.analyzer.analyze(self.topics, self.transcript)
            self.finished.emit(result)
        except Exception as e:
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
                        "Fes un resum breu en català dels punts principals tractats en aquesta reunió. "
                        "Usa llista de punts. Sense introducció ni conclusió.\n\n"
                        f"{self.transcript}"
                    )
                }]
            )
            summary = response.choices[0].message.content.strip()
            self.finished.emit(summary)
        except Exception as e:
            self.error.emit(str(e))
