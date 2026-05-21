from pathlib import Path


class VocabularyLoader:
    """Llegeix el Vocabulari.md unificat (termes principals + aliases sublista).

    Format esperat:
        ## Secció
        - Terme principal          (línia de primer nivell, sense indentació)
          - Alias 1                (sublista indentada amb 2 espais)
          - Alias 2
        - Altre terme

    `load()` retorna només els termes principals per secció (compatibilitat amb
    el codi anterior). `load_aliases()` retorna el mapping alias → terme correcte.
    """

    def __init__(self, vocab_path: Path):
        self.path = Path(vocab_path)

    def load_config(self) -> dict:
        """Retorna claus de la secció '## Configuració' com a dict str→str."""
        vocab = self.load()
        config = {}
        for item in vocab.get('Configuració', []):
            if ':' in item:
                k, _, v = item.partition(':')
                config[k.strip()] = v.strip()
        return config

    def load(self) -> dict:
        """Retorna {secció: [termes principals]}. Ignora aliases (sublistes)."""
        parsed = self._parse()
        return {section: [term for term, _ in entries]
                for section, entries in parsed.items()}

    def load_aliases(self) -> dict:
        """Retorna {alias: terme_correcte} per a tots els aliases del vocabulari.

        Els aliases són sublistes indentades sota un terme principal. S'usen
        com a correccions globals (substitució whole-word del corrector).

        Defensiu: si el terme principal és del format antic "X → Y" o "X (Y)",
        el target s'extreu de la part canònica (X), no de la línia sencera.
        Així no es corrompen transcripcions si algú deixa una entrada antiga.
        """
        parsed = self._parse()
        aliases = {}
        for section, entries in parsed.items():
            for term, alias_list in entries:
                canonical = self._canonical_form(term)
                for alias in alias_list:
                    aliases[alias] = canonical
        return aliases

    ORPHAN_SECTION = "Altres (per revisar)"

    def add_term(self, term: str) -> tuple[bool, str]:
        """Afegeix un terme principal al Vocabulari sense aliases.

        Útil quan l'usuari valida una paraula com a correcta (no és error de
        transcripció, sinó terminologia legítima que el sistema no coneixia).
        S'afegeix a la secció `## Altres (per revisar)` perquè l'usuari el
        reubiqui a la secció correcta més endavant.

        Retorna (canviat, missatge). Si el terme ja existeix, retorna False.
        """
        if not self.path.exists():
            return False, f"Fitxer no existeix: {self.path}"
        if not term:
            return False, "term és obligatori"

        lines = self.path.read_text(encoding='utf-8').splitlines()
        if self._find_term_line(lines, term) is not None:
            return False, f"El terme '{term}' ja existeix al Vocabulari"

        orphan_header = f"## {self.ORPHAN_SECTION}"
        orphan_idx = next(
            (i for i, l in enumerate(lines) if l.strip() == orphan_header),
            None
        )
        if orphan_idx is None:
            if lines and lines[-1].strip():
                lines.append('')
            lines.append(orphan_header)
            lines.append('')
            lines.append(f"- {term}")
        else:
            end_idx = len(lines)
            for k in range(orphan_idx + 1, len(lines)):
                if lines[k].startswith('## '):
                    end_idx = k
                    break
            while end_idx > orphan_idx + 1 and not lines[end_idx - 1].strip():
                end_idx -= 1
            lines.insert(end_idx, f"- {term}")
        self.path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        return True, f"Terme '{term}' afegit a '{self.ORPHAN_SECTION}'"

    def add_alias(self, alias: str, target_term: str) -> tuple[bool, str]:
        """Afegeix un alias al Vocabulari.md preservant format del fitxer.

        Comportament:
        - Si `target_term` ja existeix com a terme principal, afegeix l'alias
          com a sublista al final de les sublistes existents del terme.
        - Si no existeix, crea l'entrada a la secció 'Altres (per revisar)'.
        - Si l'alias ja és present al terme, no fa res (no duplica).

        Retorna (canviat, missatge) on canviat=True si s'ha modificat el fitxer.
        """
        if not self.path.exists():
            return False, f"Fitxer no existeix: {self.path}"
        if not alias or not target_term:
            return False, "alias i target_term són obligatoris"

        lines = self.path.read_text(encoding='utf-8').splitlines()
        target_canonical = self._canonical_form(target_term)

        term_line_idx = self._find_term_line(lines, target_canonical)
        if term_line_idx is not None:
            return self._insert_alias_under_term(lines, term_line_idx, alias)
        return self._add_to_orphan_section(lines, target_term, alias)

    def _find_term_line(self, lines: list[str], target: str) -> int | None:
        """Troba l'índex de la línia que defineix `target` com a terme principal.

        Cerca línies que comencen amb `- ` (sense indentació) i la forma canònica
        del seu contingut coincideix amb `target` (case/accent-insensitive).
        Ignora línies dins del frontmatter.
        """
        from phonetic_filter import _normalize  # comparació case/accent-insensitive
        in_frontmatter = False
        frontmatter_done = False
        for i, raw in enumerate(lines):
            if not frontmatter_done:
                if raw.strip() == '---':
                    in_frontmatter = not in_frontmatter
                    if not in_frontmatter:
                        frontmatter_done = True
                    continue
                if in_frontmatter:
                    continue
            if raw.startswith('- '):
                term = raw[2:].strip()
                if _normalize(self._canonical_form(term)) == _normalize(target):
                    return i
        return None

    def _insert_alias_under_term(self, lines: list[str], term_idx: int,
                                  alias: str) -> tuple[bool, str]:
        """Insereix l'alias com a sublista després de les sublistes existents."""
        # Recorre les línies següents per trobar el final del bloc d'aliases
        i = term_idx + 1
        existing_aliases = []
        while i < len(lines) and lines[i].startswith('  - '):
            existing_aliases.append(lines[i].lstrip()[2:].strip())
            i += 1
        if alias in existing_aliases:
            return False, f"L'alias '{alias}' ja existeix per a aquest terme"
        lines.insert(i, f"  - {alias}")
        self.path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        return True, f"Alias '{alias}' afegit al terme existent"

    def _add_to_orphan_section(self, lines: list[str], target_term: str,
                                alias: str) -> tuple[bool, str]:
        """Afegeix terme + alias a la secció ORPHAN_SECTION (creant-la si cal)."""
        orphan_header = f"## {self.ORPHAN_SECTION}"
        orphan_idx = next(
            (i for i, l in enumerate(lines) if l.strip() == orphan_header),
            None
        )
        if orphan_idx is None:
            # Afegeix la secció al final
            if lines and lines[-1].strip():
                lines.append('')
            lines.append(orphan_header)
            lines.append('')
            lines.append(f"- {target_term}")
            lines.append(f"  - {alias}")
        else:
            # Cerca si el terme ja és a la secció orphan
            j = orphan_idx + 1
            # Avança fins després del header i línia en blanc
            while j < len(lines) and not lines[j].startswith('- '):
                j += 1
            term_in_orphan = self._find_term_line(lines[orphan_idx:], target_term)
            if term_in_orphan is not None:
                # Ja hi és: insereix com a sublista
                return self._insert_alias_under_term(
                    lines, orphan_idx + term_in_orphan, alias
                )
            # Afegeix al final de la secció orphan
            end_idx = len(lines)
            for k in range(orphan_idx + 1, len(lines)):
                if lines[k].startswith('## '):
                    end_idx = k
                    break
            # Treu línies en blanc al final de la secció
            while end_idx > orphan_idx + 1 and not lines[end_idx - 1].strip():
                end_idx -= 1
            lines.insert(end_idx, f"  - {alias}")
            lines.insert(end_idx, f"- {target_term}")
        self.path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        return True, f"Terme '{target_term}' afegit a '{self.ORPHAN_SECTION}'"

    @staticmethod
    def _canonical_form(term: str) -> str:
        """Extreu la forma canònica d'un terme.

        Casos:
        - "IA → Intel·ligència Artificial" → "IA"
        - "RiD / R+D / RmesD → ..." → "RiD" (primera alternativa)
        - "RmesD (R+D)" → "RmesD"
        - "HONOA" → "HONOA"
        """
        if '→' in term:
            left, _, _ = term.partition('→')
            term = left.strip()
        if '(' in term:
            term = term.split('(')[0].strip()
        if '/' in term:
            term = term.split('/')[0].strip()
        return term

    def _parse(self) -> dict:
        """Parser intern: retorna {secció: [(terme, [aliases])]}."""
        if not self.path.exists():
            return {}

        sections = {}
        current_section = None
        current_entries = None
        last_term_aliases = None
        in_frontmatter = False
        frontmatter_done = False

        for raw_line in self.path.read_text(encoding='utf-8').splitlines():
            # Frontmatter handling
            if not frontmatter_done:
                if raw_line.strip() == '---':
                    if not in_frontmatter:
                        in_frontmatter = True
                        continue
                    else:
                        frontmatter_done = True
                        continue
                if in_frontmatter:
                    continue

            # Section headers
            if raw_line.startswith('## '):
                current_section = raw_line[3:].strip()
                current_entries = sections.setdefault(current_section, [])
                last_term_aliases = None
            elif raw_line.startswith('### '):
                continue  # subsection: ignorem, els termes pengen de la secció pare
            elif raw_line.startswith('- ') and current_section is not None:
                # Terme principal (sense indentació)
                term = raw_line[2:].strip()
                if term:
                    last_term_aliases = []
                    current_entries.append((term, last_term_aliases))
            elif raw_line.startswith('  - ') and current_section is not None:
                entry = raw_line.lstrip()[2:].strip()
                if not entry:
                    continue
                if last_term_aliases is not None:
                    # Sublista d'un terme principal → alias
                    last_term_aliases.append(entry)
                else:
                    # Indentat sense terme pare → entry directa de la secció
                    # (cas de '## Configuració' amb '  - clau: valor')
                    current_entries.append((entry, []))
            # Línies no-list les ignorem (text descriptiu, blank lines, etc.)

        return sections
