#!/usr/bin/env python3
import os, sys
import litellm
from datetime import datetime, timedelta
from dotenv import load_dotenv
from colorama import Fore, init
from calendar_matcher import CalendarMatcher
from obsidian_writer import ObsidianWriter
from vocabulary_loader import VocabularyLoader
from transcript_corrector import TranscriptCorrector

litellm.drop_params = True

# Patch CrewAI LLM per eliminar el paràmetre 'stop' que alguns models no suporten
from crewai import LLM as CrewLLM
_orig_prepare = CrewLLM._prepare_completion_params
def _patched_prepare(self, messages, tools=None):
    params = _orig_prepare(self, messages, tools)
    params.pop('stop', None)
    return params
CrewLLM._prepare_completion_params = _patched_prepare

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
            elif opcio == 3:
                break

    def _main_menu(self):
        print(f"{Fore.CYAN}  1. Entrar transcripcions")
        print(f"{Fore.CYAN}  2. Processar reunions")
        print(f"{Fore.CYAN}  3. Sortir\n")
        try:
            opcio = int(input(f"{Fore.WHITE}Opció (1-3): "))
            if 1 <= opcio <= 3:
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
            type_folder = self._select_type()
            if not type_folder:
                return
            trans = self._get_transcript()
            if not trans:
                return
            self._save(sel, trans, type_folder)
            altra = input(f"{Fore.CYAN}Entrar una altra transcripció? (s/n): ").strip().lower()
            print()
            if altra != 's':
                break

    def _select_type(self):
        types = self.obsidian.find_meeting_types()
        if not types:
            print(f"{Fore.YELLOW}No hi ha carpetes de tipus de reunió\n")
            return None

        print(f"{Fore.GREEN}Tipus de reunió:\n")
        for i, t in enumerate(types, 1):
            print(f"{i:2d}. {Fore.CYAN}{t}")
        print()

        val = input(f"{Fore.CYAN}Tipus (1-{len(types)}, q per tornar): ").strip()
        if val.lower() == 'q':
            return None
        try:
            num = int(val)
            if 1 <= num <= len(types):
                print(f"{Fore.GREEN}✓ {types[num-1]}\n")
                return types[num-1]
        except ValueError:
            pass
        return None

    def _list_meetings(self):
        now = datetime.now()
        past = now - timedelta(days=7)
        tomorrow_end = (now + timedelta(days=1)).replace(hour=23, minute=59, second=59)

        events = self.calendar.service.events().list(
            calendarId='primary',
            timeMin=past.isoformat() + 'Z',
            timeMax=tomorrow_end.isoformat() + 'Z',
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

    def _save(self, reunio, trans, type_folder):
        if self.obsidian.create_meeting_note(reunio, trans, type_folder):
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
        # Buscar la darrera nota processada de la mateixa carpeta com a referència
        reference_transcript = None
        processed_siblings = sorted(
            [p for p in note['path'].parent.glob('*.md') if '*' in p.stem],
            key=lambda p: p.stem[:6],
            reverse=True
        )
        if processed_siblings:
            reference_transcript = self.obsidian.read_transcript(processed_siblings[0])

        print(f"{Fore.CYAN}Analitzant transcripció...\n")
        corrector = TranscriptCorrector(vocab, memorized_path=memorized_path)
        new_transcript = corrector.correct(transcript, reference_transcript=reference_transcript)

        self.obsidian.update_transcript(note['path'], new_transcript)

        mark_processed = True

        # Si és una reunió de Sincronització (Daily Scrum)
        if 'Sincronització' in note['path'].parts:
            from daily_processor import DailyProcessor
            attendees = self._extract_attendees_from_note(note['path'])
            speaker_emails = self._extract_speaker_emails_from_note(note['path'])
            # Fallback: si no hi ha mapa al frontmatter, extreure correus de la transcripció
            if not speaker_emails:
                import re
                found_emails = set(re.findall(r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b', new_transcript))
                for email in found_emails:
                    name = self.calendar._resolve_name(email)
                    if name != email:
                        speaker_emails[email] = name
            # Substituir correus per noms a la transcripció
            daily_transcript = new_transcript
            for email, name in speaker_emails.items():
                daily_transcript = daily_transcript.replace(email, name)

            # Complementar assistents amb parlants identificats a la transcripció
            import re as _re
            transcript_speakers = dict.fromkeys(
                _re.findall(r'^\d{2}:\d{2}:\d{2} (.+)$', daily_transcript, _re.MULTILINE)
            )
            seen_names = {a['name'] for a in attendees}
            for speaker in transcript_speakers:
                if not _re.match(r'^Speaker \d+$', speaker) and speaker not in seen_names:
                    attendees = attendees + [{'name': speaker}]
                    seen_names.add(speaker)

            processor = DailyProcessor(vocab)
            print(f"{Fore.CYAN}Analitzant Daily Scrum...\n")
            result = processor.process(daily_transcript, attendees)

            date_obj = datetime.strptime(note['date'], '%y%m%d')
            md_output = processor.format_markdown(result, note['title'], date_obj.strftime('%d/%m/%Y'))

            print(f"{Fore.GREEN}Resultat:\n")
            print(md_output)

            conf = input(f"{Fore.CYAN}Afegir al resum de reunions? (s/n): ").strip().lower()
            print()
            if conf == 's':
                year = date_obj.strftime('%Y')
                resum_path = note['path'].parent.parent / f'Resum reunions {year}.md'
                self._append_daily_to_resum(resum_path, md_output)
                print(f"{Fore.GREEN}✓ Resum afegit a {resum_path.name}\n")
            else:
                mark_processed = False
                print(f"{Fore.YELLOW}Resum no afegit. La nota no es marcarà com a processada.\n")

        # Si és una reunió de Seguiment, analitzar temes
        elif 'Seguiment' in note['path'].parts:
            estat_path = note['path'].parent.parent / 'Estat actual.md'
            if estat_path.exists():
                from meeting_analyzer import MeetingAnalyzer, StateFileUpdater, parse_active_topics, format_ordre_del_dia
                topics = parse_active_topics(estat_path)
                if topics:
                    print(f"{Fore.CYAN}Analitzant temes de seguiment...\n")
                    analyzer = MeetingAnalyzer()
                    result = analyzer.analyze(topics, new_transcript)

                    # Mostrar resultat
                    if result.updated_topics:
                        print(f"{Fore.GREEN}Temes tractats:\n")
                        for t in result.updated_topics:
                            print(f"  {Fore.CYAN}{t.topic_name}")
                            print(f"  {Fore.WHITE}{t.summary}\n")
                    if result.new_other_topics:
                        print(f"{Fore.GREEN}Nous temes:\n")
                        for t in result.new_other_topics:
                            print(f"  {Fore.CYAN}- {t}")
                        print()
                    if not result.updated_topics and not result.new_other_topics:
                        print(f"{Fore.YELLOW}Cap tema tractat.\n")

                    conf = input(f"{Fore.CYAN}Actualitzar Estat actual.md? (s/n): ").strip().lower()
                    print()
                    if conf == 's':
                        updater = StateFileUpdater()
                        updater.update(estat_path, result, note['date'])
                        print(f"{Fore.GREEN}✓ Estat actual actualitzat\n")

                        # Sobrescriure Ordre del dia propera reunió
                        date_obj = datetime.strptime(note['date'], '%y%m%d')
                        ordre_path = note['path'].parent.parent / 'Ordre del dia propera reunió.md'
                        ordre_content = format_ordre_del_dia(result, topics, date_obj.strftime('%d/%m/%Y'))
                        ordre_path.write_text(ordre_content, encoding='utf-8')
                        print(f"{Fore.GREEN}✓ Ordre del dia actualitzat\n")
                    else:
                        mark_processed = False
                        print(f"{Fore.YELLOW}Estat actual no actualitzat. La nota no es marcarà com a processada.\n")

        if mark_processed:
            new_path = self.obsidian.mark_as_processed(note['path'])
            print(f"{Fore.GREEN}✓ Nota processada: {new_path.name}\n")

    def _extract_speaker_emails_from_note(self, path) -> dict:
        """Retorna {email: name} del frontmatter speaker_emails."""
        import yaml
        content = path.read_text(encoding='utf-8')
        if content.startswith('---'):
            end = content.find('---', 3)
            if end != -1:
                frontmatter = yaml.safe_load(content[3:end])
                if frontmatter and 'speaker_emails' in frontmatter:
                    return frontmatter['speaker_emails'] or {}
        return {}

    def _extract_attendees_from_note(self, path) -> list[dict]:
        import yaml
        content = path.read_text(encoding='utf-8')
        # Extract YAML frontmatter
        if content.startswith('---'):
            end = content.find('---', 3)
            if end != -1:
                frontmatter = yaml.safe_load(content[3:end])
                if frontmatter and 'attendees' in frontmatter:
                    attendees = []
                    for entry in frontmatter['attendees']:
                        # Extract name from "[[Name]]" format
                        name = entry.strip().strip('"').strip()
                        if name.startswith('[[') and name.endswith(']]'):
                            name = name[2:-2]
                        attendees.append({'name': name})
                    return attendees
        return []

    def _append_daily_to_resum(self, resum_path, md_content: str):
        if not resum_path.exists():
            resum_path.parent.mkdir(parents=True, exist_ok=True)
            year = resum_path.stem.split()[-1]  # "Resum reunions 2026" -> "2026"
            header = f"---\ntype: resum-reunions\nyear: {year}\n---\n\n"
            resum_path.write_text(header + md_content + '\n', encoding='utf-8')
        else:
            existing = resum_path.read_text(encoding='utf-8')
            resum_path.write_text(existing + '\n---\n\n' + md_content + '\n', encoding='utf-8')


if __name__ == "__main__":
    try:
        ReunioInteractiva().run()
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Interromput")
        sys.exit(0)
