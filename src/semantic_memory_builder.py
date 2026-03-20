import re
import json
from pathlib import Path
from semantic_models import SemanticMemory


class SemanticMemoryBuilder:
    def build_if_stale(self, meeting_dir: Path) -> Path | None:
        """Construeix o actualitza semantic_memory.json si cal. Retorna el path o None."""
        json_path = meeting_dir / 'semantic_memory.json'
        processed_files = self._find_processed_files(meeting_dir)

        if not processed_files:
            return None

        if not self._is_stale(json_path, processed_files):
            return json_path

        memory = self._build(meeting_dir, processed_files)
        json_path.write_text(memory.model_dump_json(indent=2), encoding='utf-8')
        return json_path

    def _is_stale(self, json_path: Path, processed_files: list[Path]) -> bool:
        if not json_path.exists():
            return True
        json_mtime = json_path.stat().st_mtime
        newest_md = max(p.stat().st_mtime for p in processed_files)
        return newest_md > json_mtime

    def _find_processed_files(self, meeting_dir: Path) -> list[Path]:
        reunions_dir = meeting_dir / 'Reunions'
        if not reunions_dir.exists():
            return []
        return [p for p in reunions_dir.glob('*.md')
                if '*' in p.stem or p.stem.endswith('~')]

    def _build(self, meeting_dir: Path, processed_files: list[Path]) -> SemanticMemory:
        existing = self._load_existing(meeting_dir / 'semantic_memory.json')
        person = meeting_dir.name
        extractions = [self._extract_from_note(p) for p in processed_files]
        return self._merge(existing, person, extractions, meeting_dir)

    def _load_existing(self, json_path: Path) -> SemanticMemory | None:
        if not json_path.exists():
            return None
        try:
            return SemanticMemory.model_validate_json(json_path.read_text(encoding='utf-8'))
        except Exception:
            return None

    def _extract_from_note(self, path: Path) -> dict:
        text = path.read_text(encoding='utf-8')
        topics = []

        in_frontmatter = False
        frontmatter_done = False

        for line in text.splitlines():
            # Frontmatter handling
            if not frontmatter_done:
                if line.strip() == '---':
                    if not in_frontmatter:
                        in_frontmatter = True
                        continue
                    else:
                        frontmatter_done = True
                        continue
                if in_frontmatter:
                    continue

            # Headers → recurring_topics
            if line.startswith('## ') or line.startswith('### '):
                header = re.sub(r'^#+\s*', '', line).strip()
                if header and header.lower() not in ('transcripció', 'transcript', 'resum'):
                    topics.append(header)

        return {
            'topics': list(dict.fromkeys(topics)),
        }

    def _load_vocab_projects(self, meeting_dir: Path) -> list[str]:
        """Carrega projectes des de zConfig/Vocabulari.md (seccions Persones/Projectes)."""
        current = meeting_dir
        for _ in range(5):
            candidate = current / 'zConfig' / 'Vocabulari.md'
            if candidate.exists():
                break
            current = current.parent
        else:
            return []

        projects = []
        current_section = None
        target_sections = {'projectes', 'clients', 'productes'}

        for line in candidate.read_text(encoding='utf-8').splitlines():
            if line.startswith('## '):
                current_section = line[3:].strip().lower()
            elif line.startswith('- ') and current_section in target_sections:
                word = line[2:].strip()
                if word:
                    projects.append(word)

        return projects

    def _merge(self, existing: SemanticMemory | None, person: str,
               extractions: list[dict], meeting_dir: Path) -> SemanticMemory:
        # Recollir tots els temes
        all_topics = []
        for e in extractions:
            all_topics.extend(e.get('topics', []))

        # Deduplicar
        topics = list(dict.fromkeys(all_topics))

        # Projectes des de Vocabulari.md
        projects = self._load_vocab_projects(meeting_dir)

        # Aliases: preservar els existents al JSON (s'hi afegeixen via "Memoritza")
        aliases = existing.aliases.copy() if existing else {}

        # technical_terms = valors dels aliases (termes confirmats de la sèrie)
        terms = list(dict.fromkeys(aliases.values()))

        # Fusionar temes i projectes amb existent si n'hi ha
        if existing:
            for t in existing.recurring_topics:
                if t not in topics:
                    topics.append(t)
            for p in existing.projects:
                if p not in projects:
                    projects.append(p)

        return SemanticMemory(
            person=person,
            projects=projects,
            technical_terms=terms[:50],   # limitar mida
            aliases=aliases,
            recurring_topics=topics[:30],
        )
