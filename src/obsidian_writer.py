import re
import yaml
from pathlib import Path

# Sufixos que codifiquen l'estat d'una nota al nom de fitxer (vegeu Note
# Lifecycle al CLAUDE.md): ~ corregida, + pendent de consolidar, * processada.
STATE_SUFFIXES = ('~', '+', '*')


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

    def read_recent_year_blocks(self, meeting_note_path: Path, n: int = 2) -> "str | None":
        """Retorna els últims `n` blocs (`## <data> - <títol>`) dels fitxers
        anuals de la sèrie, en ordre cronològic, com a text de referència.

        Usat per la correcció de transcripcions: el resum anual l'ha validat
        l'usuari (fase 2), per tant és una referència fiable de com s'escriuen
        noms propis i termes tècnics, a diferència de la transcripció corregida
        (que pot tenir errors residuals si es va auto-aplicar sense revisar).
        Es prenen els últims `n` perquè a la darrera reunió potser no s'han
        tractat tots els temes; dos blocs cobreixen més vocabulari que un.

        El subfolder i el nom dels anuals es deriven com a `append_to_year_note`.
        Pot haver-hi més d'un fitxer anual (canvi d'any): es concatenen per any
        ascendent. Retorna None si no hi ha cap anual amb blocs.
        """
        subfolder = meeting_note_path.parent.parent
        series = series_name_for_file(subfolder.name)
        name_re = re.compile(rf'^\d{{4}} {re.escape(series)}\.md$')
        year_files = sorted(
            (p for p in subfolder.glob(f'*{series}.md') if name_re.match(p.name)),
            key=lambda p: p.name[:4]
        )
        blocks = []
        for yf in year_files:
            text = yf.read_text(encoding='utf-8')
            for part in re.split(r'(?m)^(?=## )', text):
                if part.lstrip().startswith('## '):
                    blocks.append(part.strip())
        if not blocks:
            return None
        return '\n\n'.join(blocks[-n:])

    def _note_stem(self, meeting: dict) -> str:
        """Stem del fitxer d'una nota de reunió: 'YYMMDD_<títol net>'.

        Compartit entre `create_simple_note` (on escriu) i `find_existing_note`
        (on comprova si ja existeix) perquè el nom es calculi en un sol lloc.

        Si el títol net acaba en un dels sufixos d'estat (~ + *), s'hi afegeix un
        '_' final per evitar que es confongui amb el marcador d'estat (e.g. un
        títol "Vigik+" col·lisionaria amb l'estat '+' pendent de consolidar i
        trencaria el cicle de vida de la nota).
        """
        data = meeting['start'].strftime('%y%m%d')
        stem = f"{data}_{self._clean(meeting['title'])}"
        if stem.endswith(STATE_SUFFIXES):
            stem += '_'
        return stem

    def find_existing_note(self, meeting: dict, target_dir) -> "Path | None":
        """Retorna la nota ja existent per a aquesta reunió a `target_dir`, o None.

        Considera els quatre sufixos d'estat (sense sufix / '~' corregida /
        '+' pendent de consolidar / '*' processada) perquè un re-import no creï
        un duplicat: sense aquesta comprovació, re-desar una reunió ja corregida
        (`YYMMDD_Títol~.md`) escriuria un `YYMMDD_Títol.md` nou al costat.
        """
        if not meeting.get('start'):
            return None
        target_dir = Path(target_dir)
        stem = self._note_stem(meeting)
        for suffix in ('',) + STATE_SUFFIXES:
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
        """Notes sense cap sufix d'estat (originals, no corregides).

        Exclou ~ (corregida), + (pendent de consolidar) i * (processada) perquè
        una nota ja avançada al cicle no reaparegui al Wizard Correcció."""
        notes = []
        for p in (self.vault / 'Reunions').rglob('*.md'):
            if 'zConfig' in p.parts:
                continue
            if p.parent.name != 'Reunions':
                continue
            if not p.stem.endswith(STATE_SUFFIXES):
                parts = p.stem.split('_', 1)
                # Només notes de reunió (prefix YYMMDD numèric). Exclou fitxers
                # solts dins Reunions/ sense data (e.g. CLAUDE.md, README.md).
                if len(parts[0]) != 6 or not parts[0].isdigit():
                    continue
                title = parts[1].replace('_', ' ') if len(parts) > 1 else p.stem
                notes.append({'path': p, 'title': title, 'date': parts[0]})
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

    def find_pending_consolidation_notes(self) -> list:
        """Notes amb + al stem (ordre del dia generat a la fase 1, pendents de
        consolidar a Temes oberts + fitxer anual)."""
        notes = []
        for p in (self.vault / 'Reunions').rglob('*.md'):
            if 'zConfig' in p.parts:
                continue
            if p.parent.name != 'Reunions':
                continue
            if p.stem.endswith('+'):
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

    def ordre_del_dia_path(self, series_dir) -> Path:
        """Path de l'Ordre del dia d'una sèrie: 'Ordre del dia - <sèrie>.md'.

        El nom inclou la sèrie (folder) perquè sigui identificable a la cerca
        d'Obsidian (abans tots es deien igual). Un per sèrie. La sèrie es
        normalitza amb series_name_for_file (com el fitxer anual)."""
        series_dir = Path(series_dir)
        return series_dir / f"Ordre del dia - {series_name_for_file(series_dir.name)}.md"

    def ensure_temes_oberts(self, series_dir) -> Path:
        """Garanteix que existeix <series_dir>/Temes oberts.md. Si falta, el crea
        buit amb la secció '### Altres temes' (convenció del vault) perquè els
        temes nous de la consolidació hi tinguin lloc. Idempotent: si ja existeix
        no el toca. Retorna el path."""
        path = Path(series_dir) / 'Temes oberts.md'
        if not path.exists():
            path.write_text("### Altres temes\n", encoding='utf-8')
        return path

    def read_attendees_string(self, note_path: Path) -> str:
        """Llegeix els assistents del frontmatter d'una nota i els retorna com a
        'Nom1, Nom2'. Resol wikilinks [[Nom]] i cometes. Buit si no n'hi ha."""
        content = Path(note_path).read_text(encoding='utf-8')
        if not content.startswith('---'):
            return ''
        end = content.find('---', 3)
        if end == -1:
            return ''
        try:
            frontmatter = yaml.safe_load(content[3:end])
        except Exception:
            return ''
        if not frontmatter or 'attendees' not in frontmatter:
            return ''
        names = []
        for entry in frontmatter['attendees'] or []:
            name = str(entry).strip().strip('"').strip()
            if name.startswith('[[') and name.endswith(']]'):
                name = name[2:-2]
            names.append(name)
        return ', '.join(names)

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

    def mark_as_ordre_generated(self, path: Path) -> Path:
        """Fase 1 feta: l'ordre del dia s'ha generat i la nota queda pendent de
        consolidar. Canvia el sufix ~ (corregida) per + (pendent de consolidar);
        si no té ~, l'afegeix."""
        stem = path.stem
        if stem.endswith('~'):
            new_stem = stem[:-1] + '+'
        else:
            new_stem = stem + '+'
        new_path = path.with_stem(new_stem)
        path.rename(new_path)
        return new_path

    def mark_as_processed(self, path: Path) -> Path:
        stem = path.stem
        if stem.endswith(('~', '+')):
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
