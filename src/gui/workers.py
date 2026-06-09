import os
import errno
import socket
import time
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

# Errors de xarxa transitoris pels quals val la pena reintentar (el socket
# falla en obrir-se però la xarxa torna a estar disponible al cap d'un instant).
# EADDRNOTAVAIL (49 a macOS) = "Can't assign requested address", típic quan
# l'app arrenca mentre la xarxa/VPN encara s'estabilitza.
_TRANSIENT_ERRNOS = {
    errno.EADDRNOTAVAIL,   # 49 a macOS
    errno.ECONNRESET,
    errno.ECONNREFUSED,
    errno.ETIMEDOUT,
    errno.ENETUNREACH,
    errno.ENETDOWN,
    errno.EHOSTUNREACH,
}


def _is_transient_network_error(exc: BaseException) -> bool:
    """True si l'excepció sembla un hipo de xarxa transitori (per retry)."""
    if isinstance(exc, (socket.timeout, ConnectionError)):
        return True
    if isinstance(exc, OSError) and exc.errno in _TRANSIENT_ERRNOS:
        return True
    return False


def _retry_on_network_error(fn, *, attempts=3, base_delay=0.6):
    """Executa fn() reintentant fins a `attempts` cops davant errors de xarxa
    transitoris, amb backoff lineal. Re-llança l'última excepció si s'esgoten
    els intents o si l'error no és transitori."""
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 — filtrem per tipus a sota
            if attempt >= attempts or not _is_transient_network_error(e):
                raise
            delay = base_delay * attempt
            logger.warning(
                "Error de xarxa transitori (%s), reintent %d/%d en %.1fs",
                e, attempt, attempts, delay,
            )
            time.sleep(delay)


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

            events = _retry_on_network_error(
                lambda: self.calendar.service.events().list(
                    calendarId='primary',
                    timeMin=time_min.isoformat() + 'Z',
                    timeMax=time_max.isoformat() + 'Z',
                    singleEvents=True,
                    orderBy='startTime'
                ).execute()
            ).get('items', [])

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


class GmailLabelSyncWorker(QThread):
    """Sincronitza etiquetes vault → Gmail sense arxivar correus.

    Crea les etiquetes que falten per a sèries del vault, reporta orfes
    i tancades. No fa cap operació destructiva.

    Signals:
      log(str): missatges en text per al log live.
      finished(object): LabelSyncResult amb el resum.
      error(str): error fatal.
    """
    log = Signal(str)
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, fetcher, vault_path, include_sincro: bool, parent=None):
        super().__init__(parent)
        self.fetcher = fetcher
        from pathlib import Path as _P
        self.vault_path = _P(vault_path)
        self.include_sincro = include_sincro

    def run(self):
        try:
            from email_archiver import discover_vault_series, sync_gmail_labels
            self.log.emit("Escanejant el vault...")
            discovery = discover_vault_series(self.vault_path, include_sincro=self.include_sincro)
            self.log.emit(
                f"Trobades {len(discovery.active)} sèries actives, "
                f"{len(discovery.closed_by_active_label)} tancades."
            )
            self.log.emit("Sincronitzant etiquetes amb Gmail...")
            result = _retry_on_network_error(
                lambda: sync_gmail_labels(
                    self.fetcher, discovery, log=lambda m: self.log.emit(f"  {m}")
                )
            )
            self.finished.emit(result)
        except Exception as e:
            logger.exception("GmailLabelSyncWorker error")
            self.error.emit(str(e))


class EmailArchiveWorker(QThread):
    """Orquestra l'arxivat de correus: sync d'etiquetes, fetch de fils, dispatcher
    al vault i actualització del store d'idempotència.

    Signals:
      log(str): missatges en text per al log live.
      progress(int, int): (done, total) per a la barra de progrés.
      finished(dict): summary final amb counters i llistes.
      error(str): error fatal abans de poder començar.
    """
    log = Signal(str)
    progress = Signal(int, int)
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, fetcher, obsidian, vault_path, start_day, end_day,
                 include_sincro: bool, parent=None):
        super().__init__(parent)
        self.fetcher = fetcher
        self.obsidian = obsidian
        from pathlib import Path as _P
        self.vault_path = _P(vault_path)
        self.start_day = start_day
        self.end_day = end_day
        self.include_sincro = include_sincro
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        try:
            self._do_run()
        except Exception as e:
            logger.exception("EmailArchiveWorker error")
            self.error.emit(str(e))

    def _do_run(self):
        from email_archiver import (
            discover_vault_series, pick_destination,
            load_processed_store, save_processed_store,
            needs_archive, mark_archived, sync_gmail_labels,
        )

        summary = {
            'sync_created_labels': [],
            'sync_orphan_labels': [],
            'sync_closed_warnings': [],
            'archived_threads': [],
            'skipped_unchanged': 0,
            'skipped_no_vault_label': 0,
            'errors': [],
        }

        self.log.emit("Escanejant el vault...")
        discovery = discover_vault_series(self.vault_path, include_sincro=self.include_sincro)
        self.log.emit(
            f"Trobades {len(discovery.active)} sèries actives, "
            f"{len(discovery.closed_by_active_label)} tancades."
        )

        self.log.emit("Sincronitzant etiquetes amb Gmail...")
        sync = _retry_on_network_error(
            lambda: sync_gmail_labels(
                self.fetcher, discovery, log=lambda m: self.log.emit(f"  {m}")
            )
        )
        summary['sync_created_labels'] = sync.created
        summary['sync_orphan_labels'] = sync.orphan
        summary['sync_closed_warnings'] = sync.closed

        labels_index = {
            l['id']: l['name']
            for l in _retry_on_network_error(self.fetcher.list_user_labels)
        }

        self.log.emit(
            f"Cercant fils de {self.start_day.strftime('%Y-%m-%d')} "
            f"a {self.end_day.strftime('%Y-%m-%d')}..."
        )
        thread_ids = _retry_on_network_error(
            lambda: self.fetcher.list_thread_ids_for_range(self.start_day, self.end_day)
        )
        total = len(thread_ids)
        self.log.emit(f"Trobats {total} fils.")

        store = load_processed_store(self.vault_path)

        for i, tid in enumerate(thread_ids):
            if self._abort:
                self.log.emit("Avortat per l'usuari.")
                break
            self.progress.emit(i, total)
            try:
                peek = self.fetcher.peek_thread(tid, labels_index)
            except Exception as e:
                self.log.emit(f"  ! Error peek {tid}: {e}")
                summary['errors'].append({'thread_id': tid, 'msg': str(e)})
                continue

            relevant = [
                l for l in peek['label_names']
                if l in discovery.active or l in discovery.closed_by_active_label
            ]
            if not relevant:
                summary['skipped_no_vault_label'] += 1
                continue

            if not needs_archive(store, tid, peek['message_count']):
                summary['skipped_unchanged'] += 1
                continue

            try:
                thread = self.fetcher.fetch_thread_full(tid, labels_index)
                dispatch = pick_destination(thread['label_names'], discovery)
                if dispatch.dest is None:
                    summary['skipped_no_vault_label'] += 1
                    continue

                note_path, atts = self.obsidian.create_email_thread_note(
                    thread, dispatch.dest,
                    primary_label=dispatch.primary_label,
                    extra_labels=dispatch.extra_labels,
                )
                rel_dest = str(dispatch.dest.relative_to(self.vault_path))
                mark_archived(store, tid, len(thread['messages']), rel_dest)
                summary['archived_threads'].append({
                    'thread_id': tid,
                    'dest': rel_dest,
                    'primary_label': dispatch.primary_label,
                    'is_closed': dispatch.is_closed,
                    'extra_labels': dispatch.extra_labels,
                    'attachments': len(atts),
                    'messages': len(thread['messages']),
                    'subject': thread['messages'][0].get('subject') or '',
                    'note': note_path.name,
                })
                tag = " [TANCADA]" if dispatch.is_closed else ""
                self.log.emit(f"  ✓ {note_path.name} → {rel_dest}{tag}")
            except Exception as e:
                logger.exception("Error processant fil %s", tid)
                self.log.emit(f"  ! Error fil {tid}: {e}")
                summary['errors'].append({'thread_id': tid, 'msg': str(e)})

        save_processed_store(self.vault_path, store)
        self.progress.emit(total, total)
        self.log.emit("Acabat.")
        self.finished.emit(summary)


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
            # `list_for_date` resol `start_at` de cada candidat (la part lenta)
            # i emet progrés via el callback; les gravacions retornades ja duen
            # `start_at` poblat, així que no cal un segon bucle de fetch.
            recordings = self.client.list_for_date(
                self.target_date,
                progress_cb=lambda fets, total: self.progress.emit(fets, total),
            )
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
