"""Migra Vocabulari.md + Canvis-Memoritzats.md a un fitxer unificat.

Format de sortida (sublistes):
    ## Projectes i productes JCM
    - HONOADOOR
      - congeladors
      - conelador
    - KAIMAI
      - Keimai

Heurístiques per filtrar aliases sospitosos:
- Massa curts (< 3 chars)
- Paraules comunes / noms propis ambigus (llista negra)
- Només canvi de cas/format (excepte acrònims tot-majúscules)

Ús:
    python scripts/migrate_vocabulary.py <vault_path> [--dry-run] [--out <dir>]

En dry-run: escriu el resultat a /tmp/ i mostra resum.
Sense dry-run: substitueix Vocabulari.md i renombra Canvis-Memoritzats.md a .bak.
"""
import argparse
import re
import shutil
import sys
import unicodedata
from collections import OrderedDict
from datetime import datetime
from pathlib import Path


# Aliases que sabem que són perillosos (paraules comunes o noms propis ambigus).
# `te`, `dep`, `max`, `maxi` ja identificats per l'usuari.
DANGEROUS_ALIASES = {'dep', 'max', 'maxi'}


def normalize(s: str) -> str:
    """Minúscules + sense accents."""
    decomposed = unicodedata.normalize('NFD', s.lower())
    return ''.join(c for c in decomposed if unicodedata.category(c) != 'Mn')


def is_suspicious(alias: str, target: str) -> tuple[bool, str]:
    """Retorna (és_sospitós, motiu). Si no, motiu és None."""
    if len(alias) < 3:
        return True, f"massa curt (<3 chars)"
    if normalize(alias) in DANGEROUS_ALIASES:
        return True, "paraula comuna / nom propi habitual"
    # Només canvi de cas (sense canvi de caràcters)
    if normalize(alias) == normalize(target) and alias != target:
        # Excepció: si el target és un acrònim tot-majúscules (>= 3 chars),
        # el canvi de cas és legítim (ASR transcriu acrònims en minúscules/capitalitzat).
        if target.isupper() and len(target) >= 3:
            return False, ""
        return True, "només canvi de cas/format"
    return False, ""


def parse_vocabulary(path: Path) -> tuple[OrderedDict[str, list[str]], list[str]]:
    """Llegeix Vocabulari.md i retorna (seccions_ordenades, frontmatter_lines).

    `seccions_ordenades`: dict {nom_seccio: [termes_principals]}
    Manté l'ordre original de seccions i termes.
    """
    sections = OrderedDict()
    frontmatter = []

    if not path.exists():
        return sections, frontmatter

    in_frontmatter = False
    frontmatter_done = False
    current_section = None

    for line in path.read_text(encoding='utf-8').splitlines():
        if not frontmatter_done:
            if line.strip() == '---':
                frontmatter.append(line)
                if not in_frontmatter:
                    in_frontmatter = True
                else:
                    frontmatter_done = True
                continue
            if in_frontmatter:
                frontmatter.append(line)
                continue

        if line.startswith('## '):
            current_section = line[3:].strip()
            if current_section not in sections:
                sections[current_section] = []
        elif line.startswith('### '):
            continue  # subsecció: ignorem la capçalera, els termes pengen de la secció pare
        elif line.startswith('- ') and current_section is not None:
            term = line[2:].strip()
            if term:
                sections[current_section].append(term)
        elif line.startswith('  - ') and current_section is not None:
            # Entries indentades sense terme pare (típic de ## Configuració)
            entry = line.lstrip()[2:].strip()
            if entry:
                sections[current_section].append(entry)

    return sections, frontmatter


def parse_canvis_memoritzats(path: Path) -> list[tuple[str, str]]:
    """Retorna llista de (original, correccio) en ordre d'aparició."""
    if not path.exists():
        return []
    result = []
    for line in path.read_text(encoding='utf-8').splitlines():
        m = re.match(r'^-\s+(.+?)\s+→\s+(.+)$', line)
        if m:
            result.append((m.group(1).strip(), m.group(2).strip()))
    return result


ORPHAN_SECTION = "Altres (per revisar)"


def build_term_lookup(sections: OrderedDict[str, list[str]]) -> dict[str, tuple[str, str]]:
    """Construeix un índex per buscar termes case-insensitive.

    Retorna {normalized_term: (section_name, original_term)}.

    Per acrònims format "X → Y" (X / X1 / X2 → Y), indexa cada alternant
    de la part esquerra com a entrada cercable. Així `IEA → IA` empareix
    amb l'entrada `IA → Intel·ligència Artificial`.
    """
    lookup = {}
    for section, terms in sections.items():
        for term in terms:
            if '→' in term:
                left, _, _ = term.partition('→')
                # Suporta alternants separats per '/' (e.g. "RiD / R+D / RmesD")
                for alt in left.split('/'):
                    alt = alt.strip()
                    if alt:
                        lookup[normalize(alt)] = (section, term)
            else:
                lookup[normalize(term)] = (section, term)
    return lookup


def migrate(vocab_path: Path, canvis_path: Path) -> tuple[OrderedDict, list[dict], list[dict]]:
    """Executa la migració en memòria.

    Retorna:
        - new_sections: dict {section: list[(term, [aliases])]} en ordre
        - kept: llista de {alias, target, section} aliases acceptats
        - filtered: llista de {alias, target, reason} aliases descartats
    """
    sections, _ = parse_vocabulary(vocab_path)
    aliases_raw = parse_canvis_memoritzats(canvis_path)

    term_lookup = build_term_lookup(sections)

    # new_sections: {section: OrderedDict {term: [aliases]}}
    new_sections = OrderedDict()
    for section, terms in sections.items():
        new_sections[section] = OrderedDict((term, []) for term in terms)

    kept = []
    filtered = []

    for alias, target in aliases_raw:
        suspicious, reason = is_suspicious(alias, target)
        if suspicious:
            filtered.append({'alias': alias, 'target': target, 'reason': reason})
            continue

        # Busquem el target al Vocabulari
        key = normalize(target)
        if key in term_lookup:
            section, orig_term = term_lookup[key]
            new_sections[section][orig_term].append(alias)
            kept.append({'alias': alias, 'target': orig_term, 'section': section})
        else:
            # Target nou: l'enviem a la secció ORPHAN per a revisió manual.
            # No intentem categoritzar-lo automàticament — la categorització
            # naïf produïa massa errors (terms tècnics com "Weigand" classificats
            # com a persones).
            if ORPHAN_SECTION not in new_sections:
                new_sections[ORPHAN_SECTION] = OrderedDict()
            if target not in new_sections[ORPHAN_SECTION]:
                new_sections[ORPHAN_SECTION][target] = []
                term_lookup[key] = (ORPHAN_SECTION, target)
            new_sections[ORPHAN_SECTION][target].append(alias)
            kept.append({'alias': alias, 'target': target, 'section': ORPHAN_SECTION})

    return new_sections, kept, filtered


def render_vocabulary(new_sections: OrderedDict, frontmatter: list[str]) -> str:
    """Renderitza el nou Vocabulari.md.

    Cada terme és una línia de primer nivell `- <terme>`.
    Cada alias és una sublista `  - <alias>`.
    Es manté l'ordre original de seccions i termes.
    """
    out = []
    if frontmatter:
        # Actualitza el camp `updated` si existeix
        for line in frontmatter:
            if line.startswith('updated:'):
                out.append(f"updated: {datetime.now().strftime('%Y-%m-%d')}")
            else:
                out.append(line)
        out.append('')
    out.append('# Vocabulari JCM Technologies')
    out.append('')
    out.append("Aquest vocabulari s'utilitza per millorar les transcripcions automàtiques de reunions.")
    out.append("Cada terme pot tenir aliases (sublistes indentades) que es corregeixen automàticament a la forma canònica.")
    out.append('')

    for section, terms_dict in new_sections.items():
        if not terms_dict:
            continue
        out.append(f"## {section}")
        out.append('')
        for term, aliases in terms_dict.items():
            out.append(f"- {term}")
            for alias in aliases:
                out.append(f"  - {alias}")
        out.append('')

    return '\n'.join(out)


def render_report(kept: list[dict], filtered: list[dict]) -> str:
    """Renderitza l'informe de migració."""
    lines = []
    lines.append(f"Informe de migració del Vocabulari — {datetime.now().isoformat(timespec='seconds')}")
    lines.append('=' * 70)
    lines.append('')
    lines.append(f"Aliases acceptats: {len(kept)}")
    lines.append(f"Aliases filtrats:  {len(filtered)}")
    lines.append('')

    if filtered:
        lines.append('## Aliases FILTRATS (revisa si vols recuperar-ne algun)')
        lines.append('')
        # Agrupar per motiu
        by_reason: dict[str, list] = {}
        for f in filtered:
            by_reason.setdefault(f['reason'], []).append(f)
        for reason, items in by_reason.items():
            lines.append(f'### {reason} ({len(items)})')
            for it in items:
                lines.append(f"  - {it['alias']} → {it['target']}")
            lines.append('')

    if kept:
        lines.append('## Aliases ACCEPTATS (agrupats per secció destí)')
        lines.append('')
        by_section: dict[str, list] = {}
        for k in kept:
            by_section.setdefault(k['section'], []).append(k)
        for section, items in by_section.items():
            lines.append(f'### {section} ({len(items)})')
            for it in items:
                lines.append(f"  - {it['alias']} → {it['target']}")
            lines.append('')

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('vault', type=Path,
                       help='Path al vault Obsidian (que conté Reunions/zConfig/)')
    parser.add_argument('--dry-run', action='store_true',
                       help="No tocar el vault; escriure sortida a --out")
    parser.add_argument('--out', type=Path, default=Path('/tmp/migracio_vocabulari'),
                       help='Directori on escriure els fitxers en dry-run')
    args = parser.parse_args()

    zconfig = args.vault / 'Reunions' / 'zConfig'
    vocab_path = zconfig / 'Vocabulari.md'
    canvis_path = zconfig / 'Canvis-Memoritzats.md'

    if not vocab_path.exists():
        print(f"Error: no trobo {vocab_path}", file=sys.stderr)
        sys.exit(1)

    new_sections, kept, filtered = migrate(vocab_path, canvis_path)
    _, frontmatter = parse_vocabulary(vocab_path)
    new_content = render_vocabulary(new_sections, frontmatter)
    report = render_report(kept, filtered)

    if args.dry_run:
        args.out.mkdir(parents=True, exist_ok=True)
        new_vocab_out = args.out / 'Vocabulari.md'
        report_out = args.out / 'informe_migracio.txt'
        new_vocab_out.write_text(new_content, encoding='utf-8')
        report_out.write_text(report, encoding='utf-8')
        print(f"[dry-run] Nou Vocabulari → {new_vocab_out}")
        print(f"[dry-run] Informe       → {report_out}")
        print(f"[dry-run] Acceptats: {len(kept)}  Filtrats: {len(filtered)}")
    else:
        # Backup del Canvis-Memoritzats
        if canvis_path.exists():
            backup = canvis_path.with_suffix('.md.bak')
            shutil.move(str(canvis_path), str(backup))
            print(f"Canvis-Memoritzats.md → {backup}")
        # Escriure nou Vocabulari
        vocab_path.write_text(new_content, encoding='utf-8')
        # Escriure informe a zConfig
        report_path = zconfig / 'informe_migracio_vocabulari.txt'
        report_path.write_text(report, encoding='utf-8')
        print(f"Nou Vocabulari escrit a {vocab_path}")
        print(f"Informe a {report_path}")
        print(f"Acceptats: {len(kept)}  Filtrats: {len(filtered)}")


if __name__ == '__main__':
    main()
