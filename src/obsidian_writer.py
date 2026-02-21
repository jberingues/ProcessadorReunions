from pathlib import Path

class ObsidianWriter:
    def __init__(self, vault_path):
        self.vault = Path(vault_path).expanduser()
        if not self.vault.exists():
            raise FileNotFoundError(f"Vault no trobat: {self.vault}")
    
    def create_meeting_note(self, meeting, transcripcio):
        path = self._gen_path(meeting)
        content = self._gen_content(meeting, transcripcio)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return True
    
    def _gen_path(self, m):
        nom = self._clean(m['title'])
        data = m['start'].strftime('%y%m%d')
        return self.vault / 'Reunions' / nom / f"{data}_{nom}.md"
    
    def _clean(self, s):
        for c in '<>:"/\\|?*': s = s.replace(c, '')
        return ' '.join(s.split()).replace(' ', '_')
    
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
