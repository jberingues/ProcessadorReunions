"""Migració one-shot: treu els links de persona de les reunions del vault.

Decisió 2026-10: els links ([[ ]]) es reserven per a projectes. Els de
persona (assistents) no aportaven valor i feien soroll (graf, backlinks,
cerques de `[[`). El codi ja escriu els noms en text pla; aquest script
neteja els fitxers existents. Toca NOMÉS:

  - frontmatter `attendees:`      `  - "[[Nom]]"`        → `  - "Nom"`
  - línia del cos `**Assistents:** [[A]], [[B|b]]`        → `**Assistents:** A, b`
  - encapçalament que és només un link `##### [[Nom]]`   → `##### Nom`
    (persones als anuals de Sincronització)

La resta de links (projectes, fitxers, text) no es toquen. `[[X|àlies]]` es
substitueix pel text visible. Idempotent. Salta `zConfig` i plantilles `x*`.

Per defecte fa un **dry-run**; cal `--apply` per escriure.

Executar amb:
    uv run python scripts/migrate_unlink_people.py            # dry-run
    uv run python scripts/migrate_unlink_people.py --apply    # escriu
"""
import argparse
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent  # arrel del repo
load_dotenv(ROOT / ".env")

_LINK_RE = re.compile(r'\[\[([^\]|]*)(?:\|([^\]]*))?\]\]')
_HEADING_LINK_RE = re.compile(r'^(#{1,6}) \[\[([^\]|]*)(?:\|([^\]]*))?\]\]\s*$')
_ATTENDEE_ITEM_RE = re.compile(r'^(\s+- )"?\[\[([^\]|]*)(?:\|([^\]]*))?\]\]"?\s*$')


def _visible(target: str, alias: str | None) -> str:
    return (alias if alias else target).strip()


def unlink_people(text: str) -> tuple[str, int]:
    """Retorna (text nou, nombre de links trets)."""
    lines = text.split('\n')
    count = 0

    # Frontmatter: només els ítems de la llista `attendees:`.
    if lines and lines[0] == '---':
        in_attendees = False
        for i in range(1, len(lines)):
            line = lines[i]
            if line == '---':
                break
            if re.match(r'^\S', line):
                in_attendees = line.startswith('attendees:')
                continue
            if in_attendees:
                m = _ATTENDEE_ITEM_RE.match(line)
                if m:
                    lines[i] = f'{m.group(1)}"{_visible(m.group(2), m.group(3))}"'
                    count += 1
                elif line.lstrip().startswith('- '):
                    # Ítem amb diversos noms: `- "[[A]], [[B]]"`.
                    lines[i], n = _LINK_RE.subn(lambda m: _visible(m.group(1), m.group(2)), line)
                    count += n

    for i, line in enumerate(lines):
        if line.startswith('**Assistents:**'):
            new, n = _LINK_RE.subn(lambda m: _visible(m.group(1), m.group(2)), line)
            lines[i], count = new, count + n
            continue
        m = _HEADING_LINK_RE.match(line)
        if m:
            lines[i] = f'{m.group(1)} {_visible(m.group(2), m.group(3))}'
            count += 1

    return '\n'.join(lines), count


def migrate(vault: Path, apply: bool, log=print) -> tuple[int, int]:
    """Retorna (fitxers amb canvis, links trets)."""
    files = links = 0
    reunions = Path(vault) / 'Reunions'
    for path in sorted(reunions.rglob('*.md')):
        rel = path.relative_to(reunions)
        if any(part == 'zConfig' or part.startswith('x') for part in rel.parts):
            continue
        content = path.read_text(encoding='utf-8')
        new, n = unlink_people(content)
        if not n:
            continue
        files += 1
        links += n
        log(f"  {n:4d}  {rel}")
        if apply:
            path.write_text(new, encoding='utf-8')
    return files, links


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true',
                        help="Escriu els canvis (per defecte només dry-run).")
    args = parser.parse_args()

    vault = os.getenv('OBSIDIAN_VAULT_PATH')
    if not vault:
        print("Error: OBSIDIAN_VAULT_PATH no configurat al .env", file=sys.stderr)
        return 1

    mode = "APLICANT" if args.apply else "DRY-RUN (res s'escriu; --apply per aplicar)"
    print(f"Vault: {vault}\nMode: {mode}\n\nLinks de persona per fitxer:")
    files, links = migrate(Path(vault), args.apply)
    verb = "trets" if args.apply else "per treure"
    print(f"\n{links} links {verb} en {files} fitxers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
