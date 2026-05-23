import re
from pathlib import Path


def series_name_for_file(folder_name: str) -> str:
    """Converteix el nom d'una subcarpeta de sèrie a la versió apta per a noms de fitxer.

    Aplica: '_' → ' ', '[' → '', ']' → ''. Mantenir aquesta lògica alineada amb
    scripts/migrate_vault.py:folder_label perquè el codi nou generi els mateixos
    noms que la migració del vault.
    """
    return folder_name.replace("_", " ").replace("[", "").replace("]", "")


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
        return True

    def _read_attendees_from_note(self, note_path: Path) -> str:
        try:
            import yaml
            content = note_path.read_text(encoding='utf-8')
            if not content.startswith('---'):
                return ''
            end = content.find('---', 3)
            if end == -1:
                return ''
            fm = yaml.safe_load(content[3:end]) or {}
            attendees = fm.get('attendees', [])
            names = [a.strip('[]" ').replace('[[', '').replace(']]', '') for a in attendees]
            return ', '.join(names)
        except Exception:
            return ''

    def append_email_to_provider_note(self, note_path: Path, date_str: str, email_title: str, summary: str, project_dir: Path = None):
        if project_dir is None:
            project_dir = note_path.parent.parent
        provider_name = project_dir.name
        provider_note = project_dir / f"{provider_name}.md"

        if not provider_note.exists():
            provider_note.write_text(f"# {provider_name}\n\n", encoding='utf-8')

        content = provider_note.read_text(encoding='utf-8')
        section_title = f"{date_str}_{email_title.replace(' ', '_')} (correu)"
        new_content = content.rstrip('\n') + f"\n\n## {section_title}\n\n#### Resum correu:\n{summary}\n"
        provider_note.write_text(new_content, encoding='utf-8')

    def append_to_historic(self, note_path: Path, title: str, summary: str, project_dir: Path = None):
        if project_dir is None:
            project_dir = note_path.parent.parent
        historic_path = project_dir / 'Històric.md'
        entry = f"\n## {title}\n\n{summary}\n"
        if not historic_path.exists():
            historic_path.parent.mkdir(parents=True, exist_ok=True)
            historic_path.write_text(entry.lstrip(), encoding='utf-8')
        else:
            content = historic_path.read_text(encoding='utf-8')
            historic_path.write_text(content + entry, encoding='utf-8')

    def append_to_year_note(self, meeting_note_path: Path, date_label: str,
                            title: str, attendees: str, content_block: str) -> Path:
        """Afegeix un bloc al fitxer anual de la sèrie ('<year> <series>.md').

        El path es deriva del path de la nota de reunió:
        - subfolder = meeting_note_path.parent.parent (puja de Reunions/ al subfolder de la sèrie)
        - year = 2000 + YY (extret dels primers 2 dígits del nom de fitxer YYMMDD_*.md)
        - series = series_name_for_file(subfolder.name)

        Format del bloc:

            ## <date_label> - <title>
            Assistents: <attendees>     ← només si attendees no és buit

            <content_block>
        """
        year = 2000 + int(meeting_note_path.name[:2])
        subfolder = meeting_note_path.parent.parent
        series = series_name_for_file(subfolder.name)
        year_note = subfolder / f"{year} {series}.md"

        header_lines = [f"## {date_label} - {title}"]
        if attendees:
            header_lines.append(f"Assistents: {attendees}")
        block = "\n".join(header_lines) + "\n\n" + content_block.rstrip() + "\n"

        if year_note.exists():
            existing = year_note.read_text(encoding='utf-8')
            year_note.write_text(existing.rstrip() + "\n\n" + block, encoding='utf-8')
        else:
            year_note.parent.mkdir(parents=True, exist_ok=True)
            year_note.write_text(block, encoding='utf-8')

        return year_note

    def create_simple_note(self, meeting: dict, transcripcio: str, target_dir) -> bool:
        from pathlib import Path
        target_dir = Path(target_dir)
        data = meeting['start'].strftime('%y%m%d')
        nom_fitxer = self._clean(meeting['title'])
        path = target_dir / f"{data}_{nom_fitxer}.md"
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(self._gen_content(meeting, transcripcio), encoding='utf-8')
            return True
        except Exception:
            return False

    def create_email_note(self, thread: dict, target_dir) -> bool:
        target_dir = Path(target_dir)
        data = thread['date'].strftime('%y%m%d')
        nom = self._clean(thread['subject'])
        path = target_dir / f"{data}_{nom}.md"
        date_fmt = thread['date'].strftime('%Y-%m-%d')
        cc = thread.get('cc', '')
        cc_line_yaml = f'cc: "{cc}"\n' if cc else ''
        cc_line_body = f'**CC:** {cc}\n' if cc else ''
        content = f"""---
date: {date_fmt}
type: correu
subject: "{thread['subject']}"
from: "{thread['from']}"
{cc_line_yaml}---

# {thread['subject']}

**De:** {thread['from']}
{cc_line_body}**Data:** {date_fmt}

---

{thread['body']}
"""
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
            return True
        except Exception:
            return False

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

    def find_unprocessed_email_notes(self) -> list:
        """Notes de correu (type: correu) sense * al stem."""
        notes = []
        for p in (self.vault / 'Reunions').rglob('*.md'):
            if 'zConfig' in p.parts:
                continue
            if p.stem.endswith('*'):
                continue
            try:
                content = p.read_text(encoding='utf-8')
            except Exception:
                continue
            if not content.startswith('---'):
                continue
            end = content.find('---', 3)
            if end == -1:
                continue
            if 'type: correu' not in content[3:end]:
                continue
            parts = p.stem.split('_', 1)
            date_str = parts[0] if len(parts) > 1 and len(parts[0]) == 6 else ''
            title = parts[1].replace('_', ' ') if len(parts) > 1 else p.stem
            notes.append({'path': p, 'title': title, 'date': date_str})
        return sorted(notes, key=lambda n: n['date'], reverse=True)

    def read_email_body(self, path: Path) -> str:
        """Retorna el cos del correu (contingut després del darrer --- separador)."""
        content = path.read_text(encoding='utf-8')
        idx = content.rfind('\n---\n')
        if idx != -1:
            return content[idx + 5:].strip()
        return content

    def find_uncorrected_notes(self) -> list:
        """Notes sense ~ ni * (originals, no corregides)."""
        notes = []
        for p in (self.vault / 'Reunions').rglob('*.md'):
            if 'zConfig' in p.parts:
                continue
            if p.parent.name != 'Reunions':
                continue
            if not p.stem.endswith('~') and not p.stem.endswith('*'):
                parts = p.stem.split('_', 1)
                date_str = parts[0] if len(parts[0]) == 6 else ''
                title = parts[1].replace('_', ' ') if len(parts) > 1 else p.stem
                notes.append({'path': p, 'title': title, 'date': date_str})
        return sorted(notes, key=lambda n: n['date'], reverse=True)

    def mark_as_corrected(self, path: Path) -> Path:
        """Afegeix ~ al stem per indicar que la transcripció ha estat corregida."""
        new_path = path.with_stem(path.stem + '~')
        path.rename(new_path)
        return new_path

    def find_corrected_notes(self) -> list:
        """Notes amb ~ al stem (corregides, pendents de processar)."""
        notes = []
        for p in (self.vault / 'Reunions').rglob('*.md'):
            if 'zConfig' in p.parts:
                continue
            if p.parent.name != 'Reunions':
                continue
            if p.stem.endswith('~'):
                stem = p.stem[:-1]
                parts = stem.split('_', 1)
                date_str = parts[0] if len(parts[0]) == 6 else ''
                title = parts[1].replace('_', ' ') if len(parts) > 1 else stem
                notes.append({'path': p, 'title': title, 'date': date_str})
        return sorted(notes, key=lambda n: n['date'], reverse=True)

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
        stem = path.stem
        if stem.endswith('~'):
            new_stem = stem[:-1] + '*'
        else:
            new_stem = stem + '*'
        new_path = path.with_stem(new_stem)
        path.rename(new_path)
        return new_path

    def update_project_fields(self, note_path: Path, data_inici: str, resum: str):
        content = note_path.read_text(encoding='utf-8')
        content = re.sub(r'^Data inici:.*$', f'Data inici: {data_inici}', content, flags=re.MULTILINE)
        content = re.sub(
            r'## Resum\n[\s\S]*?\n---',
            f'## Resum\n\n{resum}\n\n---',
            content
        )
        note_path.write_text(content, encoding='utf-8')

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
