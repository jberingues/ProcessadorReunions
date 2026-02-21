import os, pickle
from datetime import datetime, timedelta
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

class CalendarMatcher:
    def __init__(self, creds_file='config/google_credentials.json'):
        self.creds_file = creds_file
        self.token_file = 'config/token.pickle'
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
                    self.creds_file,
                    ['https://www.googleapis.com/auth/calendar.readonly']
                )
                creds = flow.run_local_server(port=0)
            with open(self.token_file, 'wb') as f:
                pickle.dump(creds, f)
        self.service = build('calendar', 'v3', credentials=creds)
    
    def _parse_event(self, event):
        start = event['start'].get('dateTime', event['start'].get('date'))
        end = event['end'].get('dateTime', event['end'].get('date'))
        start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
        attendees = [{'name': a.get('displayName', a.get('email')), 'email': a.get('email')}
                     for a in event.get('attendees', [])]
        return {
            'title': event.get('summary', ''),
            'start': start_dt,
            'end': end_dt,
            'duration': str(end_dt - start_dt),
            'attendees': attendees
        }
