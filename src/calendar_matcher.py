import os, pickle
from datetime import datetime, timedelta
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/directory.readonly',
]

class CalendarMatcher:
    def __init__(self, creds_file='config/google_credentials.json'):
        self.creds_file = creds_file
        self.token_file = 'config/token.pickle'
        self._name_cache = {}
        self._auth()

    def _auth(self):
        creds = None
        if os.path.exists(self.token_file):
            with open(self.token_file, 'rb') as f:
                creds = pickle.load(f)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.creds_file, SCOPES
                )
                creds = flow.run_local_server(port=0)
            with open(self.token_file, 'wb') as f:
                pickle.dump(creds, f)
        self.service = build('calendar', 'v3', credentials=creds)
        self.people = build('people', 'v1', credentials=creds)

    def _resolve_name(self, email):
        if email in self._name_cache:
            return self._name_cache[email]
        try:
            result = self.people.people().searchDirectoryPeople(
                query=email,
                readMask='names',
                sources=['DIRECTORY_SOURCE_TYPE_DOMAIN_PROFILE']
            ).execute()
            people = result.get('people', [])
            if people:
                names = people[0].get('names', [])
                if names:
                    name = names[0].get('displayName', email)
                    self._name_cache[email] = name
                    return name
        except Exception:
            pass
        self._name_cache[email] = email
        return email

    def _parse_event(self, event):
        start = event['start'].get('dateTime', event['start'].get('date'))
        end = event['end'].get('dateTime', event['end'].get('date'))
        start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
        attendees = [{'name': self._resolve_name(a.get('email', '')), 'email': a.get('email')}
                     for a in event.get('attendees', [])]
        return {
            'title': event.get('summary', ''),
            'start': start_dt,
            'end': end_dt,
            'duration': str(end_dt - start_dt),
            'attendees': attendees
        }
