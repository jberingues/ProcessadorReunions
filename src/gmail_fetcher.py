"""Embolcall de l'API Gmail per a l'arxivat de fils al vault.

Funcionalitat:
- Gestió d'etiquetes (`list_user_labels`, `create_label`).
- Cerca de fils per a un dia concret (`list_thread_ids_for_day`).
- Peek lleuger d'un fil (etiquetes + nombre de missatges) abans de
  descarregar-lo sencer.
- Fetch sencer d'un fil amb tots els missatges, headers, body pla
  (HTML → text si cal) i adjunts descarregats en binari.

La conversió HTML→text usa `html2text` si està disponible; si no, cau
a un strip de tags bàsic.
"""

import base64
import email.utils
import html as html_module
import logging
import re
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def _headers_to_dict(part: dict) -> dict[str, str]:
    """Normalitza els headers d'un payload Gmail a un dict case-insensitive."""
    return {h['name'].lower(): h['value'] for h in part.get('headers', [])}


def build_date_range_query(start_day: date, end_day: date) -> str:
    """Construeix la query Gmail per al rang [start_day, end_day] (ambdós inclusius).

    Gmail interpreta `after:` com a inclusiu i `before:` com a exclusiu, per
    això el `before` és `end_day + 1 dia`.
    """
    if isinstance(start_day, datetime):
        start_day = start_day.date()
    if isinstance(end_day, datetime):
        end_day = end_day.date()
    before = end_day + timedelta(days=1)
    return (f"after:{start_day.strftime('%Y/%m/%d')} "
            f"before:{before.strftime('%Y/%m/%d')}")


def is_inline_attachment(headers_lower: dict[str, str], mime: str) -> bool:
    """Heurística per detectar adjunts inline (logos de firma, icones HTML, etc.).

    Filtra quan es donen totes dues condicions:
    - MIME type és image/*
    - Hi ha Content-ID (la imatge és referenciada des del cos HTML)

    El `Content-ID` és el senyal fiable: indica que la imatge va embeguda al
    cos (signatura, logo, icona social), no que sigui un adjunt real. **No**
    es mira el `Content-Disposition`: en reenviar un correu, el client sovint
    canvia la disposició d'aquestes imatges de `inline` a `attachment` (o la
    treu), i exigir `inline` les deixava colar (vegeu thread de signatura EBV
    reenviada). Els documents reals (PDFs, .docx, .xlsx, .zip, ...) no tenen
    Content-ID; les imatges adjuntades explícitament tampoc.
    """
    if not mime.startswith('image/'):
        return False
    return 'content-id' in headers_lower


class GmailFetcher:
    def __init__(self, gmail_service):
        self.gmail = gmail_service

    # --- Etiquetes ---

    def list_user_labels(self) -> list[dict]:
        """Etiquetes type='user' (les que crea/veu l'usuari)."""
        labels = self.gmail.users().labels().list(userId='me').execute().get('labels', [])
        return [{'id': l['id'], 'name': l['name']} for l in labels if l.get('type') == 'user']

    def create_label(self, name: str) -> dict:
        """Crea una etiqueta. Idempotent."""
        for l in self.list_user_labels():
            if l['name'] == name:
                return l
        body = {
            'name': name,
            'labelListVisibility': 'labelShow',
            'messageListVisibility': 'show',
        }
        created = self.gmail.users().labels().create(userId='me', body=body).execute()
        return {'id': created['id'], 'name': created['name']}

    def rename_label(self, label_id: str, new_name: str) -> dict:
        """Renombra una etiqueta conservant el seu ID.

        Conserva totes les assignacions de fils/missatges (el rename és sobre
        la mateixa etiqueta, no en crea una de nova). Scope: `gmail.labels`.
        """
        updated = self.gmail.users().labels().patch(
            userId='me', id=label_id, body={'name': new_name}
        ).execute()
        return {'id': updated['id'], 'name': updated['name']}

    # --- Cerca de fils ---

    def list_thread_ids_for_range(self, start_day: date, end_day: date) -> list[str]:
        """IDs de fils amb missatges dins el rang [start_day, end_day] (ambdós inclusius).

        Un fil amb missatges en diversos dies del rang apareix una sola
        vegada (threads().list deduplica per fil).
        """
        q = build_date_range_query(start_day, end_day)
        ids: list[str] = []
        page_token = None
        while True:
            resp = self.gmail.users().threads().list(
                userId='me', q=q, pageToken=page_token, maxResults=500
            ).execute()
            ids.extend(t['id'] for t in resp.get('threads', []))
            page_token = resp.get('nextPageToken')
            if not page_token:
                break
        return ids

    def list_thread_ids_for_day(self, target_day: date) -> list[str]:
        """IDs de fils amb missatges del dia `target_day`. Delega a `list_thread_ids_for_range`."""
        if isinstance(target_day, datetime):
            target_day = target_day.date()
        return self.list_thread_ids_for_range(target_day, target_day)

    def peek_thread(self, thread_id: str, labels_index: dict[str, str]) -> dict:
        """Crida minimal: retorna {label_names, message_count} sense baixar bodies."""
        data = self.gmail.users().threads().get(
            userId='me', id=thread_id, format='minimal'
        ).execute()
        messages = data.get('messages', [])
        label_ids = set()
        for m in messages:
            label_ids.update(m.get('labelIds', []))
        return {
            'label_names': [labels_index[lid] for lid in label_ids if lid in labels_index],
            'message_count': len(messages),
        }

    # --- Fetch sencer ---

    def fetch_thread_full(self, thread_id: str, labels_index: dict[str, str]) -> dict:
        """Retorna el fil amb tots els missatges, ordenats cronològicament."""
        data = self.gmail.users().threads().get(
            userId='me', id=thread_id, format='full'
        ).execute()
        thread_label_ids: set[str] = set()
        messages: list[dict] = []
        for msg in data.get('messages', []):
            thread_label_ids.update(msg.get('labelIds', []))
            messages.append(self._parse_message(msg))
        messages.sort(key=lambda m: m['date'])
        return {
            'thread_id': thread_id,
            'label_names': [labels_index[lid] for lid in thread_label_ids if lid in labels_index],
            'messages': messages,
        }

    def _parse_message(self, msg: dict) -> dict:
        headers = {h['name']: h['value'] for h in msg['payload']['headers']}
        date_str = headers.get('Date', '')
        try:
            date_dt = email.utils.parsedate_to_datetime(date_str)
        except (TypeError, ValueError):
            date_dt = None
        # Sempre tz-aware: fetch_thread_full ordena els missatges per data i
        # barrejar naive/aware llança TypeError (n'hi ha prou amb un missatge
        # sense capçalera Date, o amb '-0000', per trencar tot el fil).
        if date_dt is None:
            date_dt = datetime.now(timezone.utc)
        elif date_dt.tzinfo is None:
            date_dt = date_dt.replace(tzinfo=timezone.utc)
        body_text, attachments = self._extract_body_and_attachments(msg['payload'], msg['id'])
        return {
            'message_id': msg['id'],
            'date': date_dt,
            'from': headers.get('From', ''),
            'to': headers.get('To', ''),
            'cc': headers.get('Cc', ''),
            'subject': headers.get('Subject', ''),
            'body_text': body_text,
            'attachments': attachments,
        }

    def _extract_body_and_attachments(self, payload: dict, message_id: str) -> tuple[str, list[dict]]:
        text_parts: list[str] = []
        html_parts: list[str] = []
        attachments: list[dict] = []
        self._walk_parts(payload, message_id, text_parts, html_parts, attachments)
        if text_parts:
            body = '\n\n'.join(text_parts).strip()
        elif html_parts:
            body = self._html_to_text('\n'.join(html_parts)).strip()
        else:
            body = ''
        return body, attachments

    def _walk_parts(self, part: dict, message_id: str,
                    text_parts: list[str], html_parts: list[str],
                    attachments: list[dict]) -> None:
        mime = part.get('mimeType', '')
        filename = part.get('filename') or ''
        body = part.get('body', {})

        if filename:
            headers_lower = _headers_to_dict(part)
            if is_inline_attachment(headers_lower, mime):
                logger.debug("Saltat adjunt inline (probable logo/firma): %s", filename)
                return
            data_b64 = body.get('data')
            attachment_id = body.get('attachmentId')
            if data_b64 is None and attachment_id:
                try:
                    resp = self.gmail.users().messages().attachments().get(
                        userId='me', messageId=message_id, id=attachment_id
                    ).execute()
                    data_b64 = resp.get('data')
                except Exception:
                    logger.exception("Error baixant adjunt %s del missatge %s", filename, message_id)
                    return
            if data_b64:
                try:
                    raw = base64.urlsafe_b64decode(data_b64)
                    attachments.append({'filename': filename, 'mime': mime, 'data': raw})
                except Exception:
                    logger.exception("No s'ha pogut descodificar l'adjunt %s", filename)
            return

        if mime.startswith('text/plain'):
            data_b64 = body.get('data')
            if data_b64:
                try:
                    text_parts.append(base64.urlsafe_b64decode(data_b64).decode('utf-8', errors='replace'))
                except Exception:
                    logger.exception("Error decoding text/plain")
            return

        if mime.startswith('text/html'):
            data_b64 = body.get('data')
            if data_b64:
                try:
                    html_parts.append(base64.urlsafe_b64decode(data_b64).decode('utf-8', errors='replace'))
                except Exception:
                    logger.exception("Error decoding text/html")
            return

        for sub in part.get('parts', []):
            self._walk_parts(sub, message_id, text_parts, html_parts, attachments)

    def _html_to_text(self, html_str: str) -> str:
        try:
            import html2text
            h = html2text.HTML2Text()
            h.ignore_images = True
            h.ignore_links = False
            h.body_width = 0
            return h.handle(html_str)
        except ImportError:
            text = re.sub(r'<[^>]+>', '', html_str)
            return html_module.unescape(text)
