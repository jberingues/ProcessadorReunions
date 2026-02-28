from pathlib import Path


class ObsidianWriter:
    def __init__(self, vault_path):
        self.vault = Path(vault_path).expanduser()
        if not self.vault.exists():
            raise FileNotFoundError(f"Vault no trobat: {self.vault}")

    def find_subfolders(self, type_folder: str) -> list:
        type_dir = self.vault / 'Reunions' / type_folder
        if not type_dir.exists():
            return []
        return sorted([d.name for d in type_dir.iterdir() if d.is_dir() and not d.name.startswith('.')])

    def create_meeting_note(self, meeting, transcripcio, type_folder, sub_folder=None, subtype=None):
        path = self._gen_path(meeting, type_folder, sub_folder)
        content = self._gen_content(meeting, transcripcio, subtype)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')

        if type_folder == 'Seguiment':
            meeting_dir = path.parent.parent
            if subtype == 'puntual':
                notes_to_create = ['Històric']
            else:
                title = meeting['title']
                estat_nom = title[len('Seguiment '):] if title.startswith('Seguiment ') else 'Estat actual'
                notes_to_create = [estat_nom, 'Històric']
            for nom_nota in notes_to_create:
                nota_path = meeting_dir / f"{nom_nota}.md"
                if not nota_path.exists():
                    nota_path.write_text("", encoding='utf-8')

        return True

    def append_to_provider_note(self, note_path: Path, date_str: str, meeting_title: str, summary: str):
        provider_name = note_path.parent.parent.name
        provider_note = note_path.parent.parent / f"{provider_name}.md"

        if not provider_note.exists():
            provider_note.write_text(f"# {provider_name}\n\n", encoding='utf-8')

        content = provider_note.read_text(encoding='utf-8')
        section_title = f"{date_str}_{meeting_title.replace(' ', '_')}"
        date_prefix = f"## {date_str}_"

        if date_prefix in content:
            idx = content.find(date_prefix)
            next_section = content.find('\n## ', idx + 1)
            if next_section == -1:
                new_content = content.rstrip('\n') + f"\n\n#### Resum reunió:\n{summary}\n"
            else:
                new_content = (content[:next_section].rstrip('\n') +
                               f"\n\n#### Resum reunió:\n{summary}\n\n" +
                               content[next_section:].lstrip('\n'))
        else:
            new_content = content.rstrip('\n') + f"\n\n## {section_title}\n\n{summary}\n"

        provider_note.write_text(new_content, encoding='utf-8')

    def append_to_historic(self, note_path: Path, title: str, summary: str):
        historic_path = note_path.parent.parent / 'Històric.md'
        entry = f"\n## {title}\n\n{summary}\n"
        if not historic_path.exists():
            historic_path.parent.mkdir(parents=True, exist_ok=True)
            historic_path.write_text(entry.lstrip(), encoding='utf-8')
        else:
            content = historic_path.read_text(encoding='utf-8')
            historic_path.write_text(content + entry, encoding='utf-8')

    def _gen_path(self, m, type_folder, sub_folder=None):
        data = m['start'].strftime('%y%m%d')
        if sub_folder:
            nom_fitxer = self._clean(m['title'])
            return self.vault / 'Reunions' / type_folder / sub_folder / 'Reunions' / f"{data}_{nom_fitxer}.md"
        else:
            nom = self._clean(m['title'])
            return self.vault / 'Reunions' / type_folder / nom / 'Reunions' / f"{data}_{nom}.md"

    def _clean(self, s):
        for c in '<>:"/\\|?*': s = s.replace(c, '')
        return ' '.join(s.split()).replace(' ', '_')

    def find_meeting_types(self) -> list:
        reunions_dir = self.vault / 'Reunions'
        return sorted([
            d.name for d in reunions_dir.iterdir()
            if d.is_dir() and d.name != 'zConfig' and not d.name.startswith('.')
        ])

    def find_unprocessed_notes(self) -> list:
        notes = []
        for p in (self.vault / 'Reunions').rglob('*.md'):
            if 'zConfig' in p.parts:
                continue
            if p.parent.name != 'Reunions':
                continue
            if not p.stem.endswith('*'):
                parts = p.stem.split('_', 1)
                date_str = parts[0] if len(parts[0]) == 6 else ''
                title = parts[1].replace('_', ' ') if len(parts) > 1 else p.stem
                notes.append({'path': p, 'title': title, 'date': date_str})
        return sorted(notes, key=lambda n: n['date'], reverse=True)

    def read_transcript(self, path: Path) -> str:
        content = path.read_text(encoding='utf-8')
        marker = '## Transcripció'
        idx = content.find(marker)
        if idx == -1:
            return content
        return content[idx + len(marker):].strip()

    def update_transcript(self, path: Path, new_transcript: str):
        content = path.read_text(encoding='utf-8')
        marker = '## Transcripció'
        idx = content.find(marker)
        if idx == -1:
            return
        new_content = content[:idx + len(marker)] + '\n\n' + new_transcript + '\n'
        path.write_text(new_content, encoding='utf-8')

    def mark_as_processed(self, path: Path) -> Path:
        new_path = path.with_stem(path.stem + '*')
        path.rename(new_path)
        return new_path

    def _gen_content(self, m, t, subtype=None):
        data = m['start'].strftime('%Y-%m-%d')
        hora = m['start'].strftime('%H:%M')
        atts = '\n'.join([f'  - "[[{a["name"]}]]"' for a in m['attendees']])
        names = ', '.join([f"[[{a['name']}]]" for a in m['attendees']])
        email_entries = [a for a in m['attendees'] if a.get('email')]
        speaker_emails_block = ''
        if email_entries:
            email_lines = '\n'.join([f'  {a["email"]}: "{a["name"]}"' for a in email_entries])
            speaker_emails_block = f'speaker_emails:\n{email_lines}\n'
        subtype_line = f'subtype: {subtype}\n' if subtype else ''
        return f"""---
date: {data}
time: {hora}
type: reunio
{subtype_line}title: "{m['title']}"
attendees:
{atts}
{speaker_emails_block}---

# {m['title']}

**Data:** {data} {hora}
**Assistents:** {names}
**Durada:** {m['duration']}

---

## Transcripció

{t}

"""
