"""Migració one-shot: afegeix frontmatter als fitxers anuals existents.

`ObsidianWriter.append_to_year_note` escriu frontmatter (`type: resum_anual`,
`serie`, `any`) als anuals nous i el prepèn als antics quan hi afegeix un bloc
— però només quan la sèrie torna a tenir una reunió processada. Aquest script
posa el frontmatter a TOTS els anuals existents d'un sol cop, perquè les
cerques estructurades (Dataview / consultes LLM) cobreixin tot el vault des
d'ara.

Un fitxer anual és `<Any> <Sèrie>.md` dins la carpeta de la sèrie, on `<Sèrie>`
és el nom de la carpeta via `series_name_for_file` (mateixa derivació que
`append_to_year_note`). Els fitxers que ja comencen amb `---` no es toquen
(idempotent). Se salten `zConfig` i les plantilles `x*`.

Per defecte fa un **dry-run**; cal `--apply` per escriure.

Executar amb:
    uv run python scripts/migrate_year_frontmatter.py            # dry-run
    uv run python scripts/migrate_year_frontmatter.py --apply    # escriu
"""
import argparse
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent  # arrel del repo
sys.path.insert(0, str(ROOT / "src"))

load_dotenv(ROOT / ".env")

from obsidian_writer import series_name_for_file  # noqa: E402

_YEAR_NOTE_RE = re.compile(r'^(\d{4}) (.+)\.md$')


def find_year_notes(vault: Path) -> list[tuple[Path, str, int]]:
    """Retorna (path, sèrie, any) per a cada fitxer anual del vault.

    Reconeix `<Any> <Sèrie>.md` només si `<Sèrie>` coincideix amb el nom de la
    carpeta contenidora (via series_name_for_file) — així no es confon amb
    altres .md que comencin amb 4 dígits.
    """
    found = []
    reunions = Path(vault) / 'Reunions'
    for p in sorted(reunions.rglob('*.md')):
        if any(part == 'zConfig' or part.startswith('x') for part in p.relative_to(reunions).parts):
            continue
        m = _YEAR_NOTE_RE.match(p.name)
        if not m:
            continue
        year, name_series = int(m.group(1)), m.group(2)
        if not (2000 <= year <= 2100):
            continue
        if name_series != series_name_for_file(p.parent.name):
            continue
        found.append((p, name_series, year))
    return found


def build_frontmatter(series: str, year: int) -> str:
    """Mateix format que ObsidianWriter.append_to_year_note."""
    return (
        "---\n"
        "type: resum_anual\n"
        f'serie: "{series}"\n'
        f"any: {year}\n"
        "---\n"
    )


def migrate(vault: Path, apply: bool, log=print) -> tuple[int, int]:
    """Retorna (migrats, ja_ok)."""
    migrated = skipped = 0
    for path, series, year in find_year_notes(vault):
        content = path.read_text(encoding='utf-8')
        if content.startswith('---'):
            skipped += 1
            continue
        migrated += 1
        rel = path.relative_to(vault)
        log(f"  + {rel}  (serie={series!r}, any={year})")
        if apply:
            path.write_text(
                build_frontmatter(series, year) + "\n" + content.lstrip('\n'),
                encoding='utf-8',
            )
    return migrated, skipped


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
    print(f"Vault: {vault}\nMode: {mode}\n\nAnuals sense frontmatter:")
    migrated, skipped = migrate(Path(vault), args.apply)
    verb = "migrats" if args.apply else "per migrar"
    print(f"\n{migrated} {verb}, {skipped} ja amb frontmatter.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
