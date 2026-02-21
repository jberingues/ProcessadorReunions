#!/usr/bin/env python3
import os, sys
from datetime import datetime, timedelta
from dotenv import load_dotenv
from colorama import Fore, init
from calendar_matcher import CalendarMatcher
from obsidian_writer import ObsidianWriter

init(autoreset=True)

class ReunioInteractiva:
    def __init__(self):
        load_dotenv()
        print(f"\n{Fore.CYAN}{'='*60}")
        print(f"{Fore.CYAN}  PROCESSADOR DE REUNIONS")
        print(f"{Fore.CYAN}{'='*60}\n")
        
        vault = os.getenv('OBSIDIAN_VAULT_PATH')
        if not vault:
            print(f"{Fore.RED}OBSIDIAN_VAULT_PATH no configurat al .env")
            sys.exit(1)
        
        self.calendar = CalendarMatcher()
        self.obsidian = ObsidianWriter(vault)
        print(f"{Fore.GREEN}✓ Sistema inicialitzat\n")
    
    def run(self):
        reunions = self._list_meetings()
        if not reunions: return
        
        sel = self._select(reunions)
        if not sel: return
        
        trans = self._get_transcript()
        if not trans: return
        
        self._save(sel, trans)
    
    def _list_meetings(self):
        now = datetime.now()
        past = now - timedelta(days=7)
        
        events = self.calendar.service.events().list(
            calendarId='primary',
            timeMin=past.isoformat() + 'Z',
            timeMax=now.isoformat() + 'Z',
            singleEvents=True,
            orderBy='startTime'
        ).execute().get('items', [])
        
        reunions = [self.calendar._parse_event(e) for e in events if 'attendees' in e]
        
        if not reunions:
            print(f"{Fore.YELLOW}No hi ha reunions recents")
            return []
        
        print(f"{Fore.GREEN}Reunions:\n")
        for i, r in enumerate(reunions, 1):
            data = r['start'].strftime('%d/%m/%Y %H:%M')
            noms = [a['name'] for a in r['attendees'][:3]]
            print(f"{i:2d}. {Fore.CYAN}{data} {Fore.WHITE}| {r['title']}")
            print(f"     {Fore.YELLOW}{', '.join(noms)}")
        print()
        return reunions
    
    def _select(self, reunions):
        try:
            num = int(input(f"{Fore.CYAN}Reunió (1-{len(reunions)}): "))
            if 1 <= num <= len(reunions):
                print(f"{Fore.GREEN}✓ {reunions[num-1]['title']}\n")
                return reunions[num-1]
        except: pass
        return None
    
    def _get_transcript(self):
        print(f"{Fore.CYAN}Enganxa transcripció (Ctrl+D per acabar):\n")
        try:
            lines = []
            while True:
                try: lines.append(input())
                except EOFError: break
            text = '\n'.join(lines).strip()
            if text:
                print(f"\n{Fore.GREEN}✓ {len(lines)} línies\n")
                return text
        except: pass
        return None
    
    def _save(self, reunio, trans):
        if self.obsidian.create_meeting_note(reunio, trans):
            print(f"{Fore.GREEN}✓ Nota guardada a Obsidian!\n")
        else:
            print(f"{Fore.RED}✗ Error guardant\n")

if __name__ == "__main__":
    try:
        ReunioInteractiva().run()
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Interromput")
        sys.exit(0)
