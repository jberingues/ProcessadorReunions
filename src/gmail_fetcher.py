"""Embolcall de l'API Gmail per a l'arxivat de fils al vault.

Funcionalitat:
- Gestió d'etiquetes (`list_user_labels`, `create_label`).
- Cerca de fils des d'una data (`list_thread_ids_since`).
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
from datetime import datetime

logger = logging.getLogger(__name__)


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

    # --- Cerca de fils ---

    def list_thread_ids_since(self, date_from: datetime) -> list[str]:
        """IDs de fils amb missatges des de `date_from`. Recorre paginació."""
        q = f"after:{date_from.strftime('%Y/%m/%d')}"
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
            date_dt = datetime.now()
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
