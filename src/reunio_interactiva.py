#!/usr/bin/env python3
import os, sys
from datetime import datetime, timedelta
from dotenv import load_dotenv
from colorama import Fore, init
from calendar_matcher import CalendarMatcher
from obsidian_writer import ObsidianWriter
from vocabulary_loader import VocabularyLoader
from transcript_corrector import TranscriptCorrector

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
        while True:
            opcio = self._main_menu()
            if opcio == 1:
                self._flux_transcripcions()
            elif opcio == 2:
                self._flux_processar()
            else:
                break

    def _main_menu(self):
        print(f"{Fore.CYAN}  1. Entrar transcripcions")
        print(f"{Fore.CYAN}  2. Processar reunions\n")
        try:
            opcio = int(input(f"{Fore.WHITE}Opció (1-2): "))
            if 1 <= opcio <= 2:
                print()
                return opcio
        except ValueError:
            pass
        return None

    def _flux_transcripcions(self):
        reunions = self._list_meetings()
        if not reunions:
            return
        while True:
            sel = self._select(reunions)
            if not sel:
                return
            trans = self._get_transcript()
            if not trans:
                return
            self._save(sel, trans)
            altra = input(f"{Fore.CYAN}Entrar una altra transcripció? (s/n): ").strip().lower()
            print()
            if altra != 's':
                break

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
            val = input(f"{Fore.CYAN}Reunió (1-{len(reunions)}, q per tornar): ").strip()
            if val.lower() == 'q':
                return None
            num = int(val)
            if 1 <= num <= len(reunions):
                print(f"{Fore.GREEN}✓ {reunions[num-1]['title']}\n")
                return reunions[num-1]
        except ValueError:
            pass
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

    def _flux_processar(self):
        notes = self.obsidian.find_unprocessed_notes()
        if not notes:
            print(f"{Fore.YELLOW}No hi ha reunions per processar\n")
            return

        print(f"{Fore.GREEN}Reunions per processar:\n")
        for i, n in enumerate(notes, 1):
            print(f"{i:2d}. {Fore.CYAN}{n['date']} {Fore.WHITE}| {n['title']}")
        print()

        val = input(f"{Fore.CYAN}Reunió (1-{len(notes)}, q per tornar): ").strip()
        if val.lower() == 'q':
            return
        try:
            num = int(val)
            if not 1 <= num <= len(notes):
                return
        except ValueError:
            return

        note = notes[num - 1]
        print(f"\n{Fore.GREEN}✓ {note['title']}\n")

        vocab_path = self.obsidian.vault / 'Reunions' / 'zConfig' / 'Vocabulari.md'
        vocab = VocabularyLoader(vocab_path).load()
        transcript = self.obsidian.read_transcript(note['path'])

        memorized_path = self.obsidian.vault / 'Reunions' / 'zConfig' / 'Canvis-Memoritzats.md'
        print(f"{Fore.CYAN}Analitzant transcripció...\n")
        corrector = TranscriptCorrector(vocab, memorized_path=memorized_path)
        new_transcript = corrector.correct(transcript)

        self.obsidian.update_transcript(note['path'], new_transcript)
        new_path = self.obsidian.mark_as_processed(note['path'])
        print(f"{Fore.GREEN}✓ Nota processada: {new_path.name}\n")

if __name__ == "__main__":
    try:
        ReunioInteractiva().run()
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Interromput")
        sys.exit(0)
