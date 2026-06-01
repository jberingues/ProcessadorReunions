import re
from pathlib import Path


def series_name_for_file(folder_name: str) -> str:
    """Converteix el nom d'una subcarpeta de sèrie a la versió apta per a noms de fitxer.

    Aplica: '_' → ' ', '[' → '', ']' → ''.
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

    def _note_stem(self, meeting: dict) -> str:
        """Stem del fitxer d'una nota de reunió: 'YYMMDD_<títol net>'.

        Compartit entre `create_simple_note` (on escriu) i `find_existing_note`
        (on comprova si ja existeix) perquè el nom es calculi en un sol lloc.
        """
        data = meeting['start'].strftime('%y%m%d')
        return f"{data}_{self._clean(meeting['title'])}"

    def find_existing_note(self, meeting: dict, target_dir) -> "Path | None":
        """Retorna la nota ja existent per a aquesta reunió a `target_dir`, o None.

        Considera els tres sufixos d'estat (sense sufix / '~' corregida /
        '*' processada) perquè un re-import no creï un duplicat: sense aquesta
        comprovació, re-desar una reunió ja corregida (`YYMMDD_Títol~.md`)
        escriuria un `YYMMDD_Títol.md` nou al costat.
        """
        if not meeting.get('start'):
            return None
        target_dir = Path(target_dir)
        stem = self._note_stem(meeting)
        for suffix in ('', '~', '*'):
            candidate = target_dir / f"{stem}{suffix}.md"
            if candidate.exists():
                return candidate
        return None

    def create_simple_note(self, meeting: dict, transcripcio: str, target_dir) -> bool:
        target_dir = Path(target_dir)
        path = target_dir / f"{self._note_stem(meeting)}.md"
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(self._gen_content(meeting, transcripcio), encoding='utf-8')
            return True
        except Exception:
            return False

    def create_email_thread_note(self, thread: dict, dest_dir,
                                 primary_label: str,
                                 extra_labels: list[str] | None = None) -> tuple[Path, list[Path]]:
        """Escriu una nota amb el fil sencer (tots els missatges + adjunts).

        Args:
            thread: dict amb claus `thread_id`, `label_names` (ignorat aquí
                — el caller passa explicitament primary/extra), `messages`.
                Cada missatge: `message_id`, `date`, `from`, `to`, `cc`,
                `subject`, `body_text`, `attachments` (list de
                `{filename, mime, data: bytes}`).
            dest_dir: directori de la sèrie (e.g. .../Seguiment/Joan).
            primary_label: etiqueta principal (la que ha decidit el destí).
            extra_labels: altres etiquetes vault del fil, van a `tags:`.

        Retorna: (path_de_la_nota, list[paths_d'adjunts_desats]).
        Sobreescriu si la nota ja existeix (regeneració completa).
        """
        from email_archiver import normalize_subject, place_attachment
        import email.utils as _email_utils

        extra_labels = extra_labels or []
        dest_dir = Path(dest_dir)
        correus_dir = dest_dir / 'Correus'
        fitxers_dir = dest_dir / 'Fitxers'
        correus_dir.mkdir(parents=True, exist_ok=True)

        messages = thread.get('messages') or []
        if not messages:
            raise ValueError("Fil sense missatges")

        first = messages[0]
        yymmdd = first['date'].strftime('%y%m%d')
        iso_date = first['date'].strftime('%Y-%m-%d')
        subject_raw = first.get('subject') or '(sense assumpte)'
        note_path = correus_dir / f"{yymmdd}_{normalize_subject(subject_raw)}.md"

        # Adjunts (descarregats abans d'escriure la nota perquè calen els paths).
        msg_attachment_paths: dict[str, list[Path]] = {}
        all_attachment_paths: list[Path] = []
        for m in messages:
            saved: list[Path] = []
            for att in m.get('attachments') or []:
                ap = place_attachment(fitxers_dir, yymmdd, att['filename'], att['data'])
                saved.append(ap)
                all_attachment_paths.append(ap)
            msg_attachment_paths[m['message_id']] = saved

        def yaml_list(items: list[str], key: str) -> str:
            if not items:
                return f"{key}: []"
            esc = [it.replace('"', '\\"') for it in items]
            return f"{key}:\n" + "\n".join(f'  - "{e}"' for e in esc)

        safe_subject = subject_raw.replace('"', '\\"')
        labels_block = yaml_list([primary_label] if primary_label else [], 'labels')
        tags_block = yaml_list(extra_labels, 'tags')

        frontmatter = (
            "---\n"
            "type: correu\n"
            f"thread_id: {thread['thread_id']}\n"
            f"data: {iso_date}\n"
            f'assumpte: "{safe_subject}"\n'
            f"{labels_block}\n"
            f"{tags_block}\n"
            "---\n"
        )

        body_blocks: list[str] = []
        for i, m in enumerate(messages):
            dt_str = m['date'].strftime('%Y-%m-%d %H:%M')
            name, addr = _email_utils.parseaddr(m.get('from') or '')
            sender = name or addr or '(desconegut)'
            addr_part = f" <{addr}>" if addr else ''
            suffix = " (resposta)" if i > 0 else ""
            header = f"## {dt_str} — {sender}{addr_part}{suffix}"

            block_lines = [header, "", (m.get('body_text') or '').strip()]
            atts = msg_attachment_paths.get(m['message_id'], [])
            if atts:
                block_lines.append("")
                block_lines.append("**Adjunts:**")
                for ap in atts:
                    rel = ap.relative_to(dest_dir).as_posix()
                    block_lines.append(f"- [[{rel}]]")
            body_blocks.append("\n".join(block_lines))

        content = frontmatter + "\n" + "\n\n".join(body_blocks).rstrip() + "\n"
        note_path.write_text(content, encoding='utf-8')
        return note_path, all_attachment_paths

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
