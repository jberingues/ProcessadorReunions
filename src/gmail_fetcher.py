import base64
import email.utils
from datetime import datetime


class GmailFetcher:
    def __init__(self, gmail_service):
        self.gmail = gmail_service
        self._label_id = None

    def _get_label_id(self, name='Arxivar') -> str | None:
        if self._label_id:
            return self._label_id
        labels = self.gmail.users().labels().list(userId='me').execute().get('labels', [])
        for l in labels:
            if l['name'] == name:
                self._label_id = l['id']
                return self._label_id
        return None

    def fetch_threads(self, date_from: datetime, date_to: datetime) -> list[dict]:
        label_id = self._get_label_id()
        if not label_id:
            return []
        q = f"after:{date_from.strftime('%Y/%m/%d')} before:{date_to.strftime('%Y/%m/%d')}"
        result = self.gmail.users().threads().list(
            userId='me', labelIds=[label_id], q=q
        ).execute()
        threads = result.get('threads', [])
        return [self._parse_thread(t['id']) for t in threads]

    def _parse_thread(self, thread_id: str) -> dict:
        data = self.gmail.users().threads().get(
            userId='me', id=thread_id, format='full'
        ).execute()
        messages = data.get('messages', [])
        last = messages[-1]
        headers = {h['name']: h['value'] for h in last['payload']['headers']}
        subject = headers.get('Subject', '(sense assumpte)')
        from_ = headers.get('From', '')
        cc = headers.get('Cc', '')
        date_str = headers.get('Date', '')
        try:
            date_dt = email.utils.parsedate_to_datetime(date_str)
        except Exception:
            date_dt = datetime.now()
        body = self._extract_body(last['payload'])
        return {
            'thread_id': thread_id,
            'subject': subject,
            'from': from_,
            'cc': cc,
            'date': date_dt,
            'num_messages': len(messages),
            'body': body,
        }

    def _extract_body(self, payload) -> str:
        if payload.get('mimeType', '').startswith('text/plain'):
            data = payload.get('body', {}).get('data', '')
            if data:
                return base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')
        for part in payload.get('parts', []):
            result = self._extract_body(part)
            if result:
                return result
        return ''
