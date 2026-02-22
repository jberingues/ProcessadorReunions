from pathlib import Path


class ObsidianWriter:
    def __init__(self, vault_path):
        self.vault = Path(vault_path).expanduser()
        if not self.vault.exists():
            raise FileNotFoundError(f"Vault no trobat: {self.vault}")

    def create_meeting_note(self, meeting, transcripcio, type_folder):
        path = self._gen_path(meeting, type_folder)
        content = self._gen_content(meeting, transcripcio)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')

        if type_folder == 'Seguiment':
            meeting_dir = path.parent.parent
            for nom_nota in ['Estat actual', 'Històric']:
                nota_path = meeting_dir / f"{nom_nota}.md"
                if not nota_path.exists():
                    nota_path.write_text(f"# {nom_nota}\n\n", encoding='utf-8')

        return True

    def _gen_path(self, m, type_folder):
        nom = self._clean(m['title'])
        data = m['start'].strftime('%y%m%d')
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

    def _gen_content(self, m, t):
        data = m['start'].strftime('%Y-%m-%d')
        hora = m['start'].strftime('%H:%M')
        atts = '\n'.join([f'  - "[[{a["name"]}]]"' for a in m['attendees']])
        names = ', '.join([f"[[{a['name']}]]" for a in m['attendees']])
        return f"""---
date: {data}
time: {hora}
type: reunio
title: "{m['title']}"
attendees:
{atts}
---

# {m['title']}

**Data:** {data} {hora}
**Assistents:** {names}
**Durada:** {m['duration']}

---

## Transcripció

{t}

"""
