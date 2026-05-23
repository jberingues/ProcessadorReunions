#!/usr/bin/env python3
"""Renombra Reunions/Seguiment/Seguiment_*/ → Reunions/Seguiment/<X>/

Estrip el prefix 'Seguiment_' i substitueix els underscores restants per espais.
Excepció: 'Seguiment_x' → 'Seguiment x' (carpeta de proves).

Per cada carpeta:
- Renombra el subfolder
- Renombra el year note '2026 Seguiment X.md' → '2026 X.md' (si existeix)
- Substitueix enllaços [[2026 Seguiment X]] → [[2026 X]] arreu del vault
  (segur perquè els noms de year note són únics per sèrie).

Usage:
    uv run python scripts/migrate_seguiment_rename.py            # dry-run
    uv run python scripts/migrate_seguiment_rename.py --apply    # executar
"""

from __future__ import annotations
import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


SPECIAL_CASES = {
    "Seguiment_x": "Seguiment x",
}


def new_folder_name(old: str) -> str:
    if old in SPECIAL_CASES:
        return SPECIAL_CASES[old]
    if not old.startswith("Seguiment_"):
        return old
    return old[len("Seguiment_"):].replace("_", " ")


@dataclass
class Rename:
    src: Path
    dst: Path
    kind: str  # 'folder' | 'year_note'


def collect_renames(reunions: Path) -> list[Rename]:
    out: list[Rename] = []
    seguiment = reunions / "Seguiment"
    for sub in sorted(seguiment.iterdir()):
        if not sub.is_dir():
            continue
        if not sub.name.startswith("Seguiment_"):
            continue
        new_name = new_folder_name(sub.name)
        if new_name == sub.name:
            continue
        new_sub = sub.parent / new_name
        out.append(Rename(sub, new_sub, "folder"))

        # Year notes: qualsevol fitxer '\d{4} <whatever>.md' es renomena a
        # '\d{4} <target_series>.md'. Lògica permissiva per cobrir casos on l'usuari
        # va canviar el nom del folder manualment sense actualitzar el year note.
        target_series = new_name.replace("_", " ").replace("[", "").replace("]", "")
        for year_note in sub.glob("*.md"):
            m = re.match(r"^(\d{4}) .+\.md$", year_note.name)
            if not m:
                continue
            year = m.group(1)
            target_name = f"{year} {target_series}.md"
            if year_note.name == target_name:
                continue
            dst_in_new_folder = new_sub / target_name
            out.append(Rename(year_note, dst_in_new_folder, "year_note"))
    return out


def substitute_link(text: str, old_stem: str, new_stem: str) -> tuple[str, int]:
    pattern = re.compile(
        r"\[\[" + re.escape(old_stem) + r"(?=[\]#|])([^\]]*)\]\]"
    )
    count = 0

    def repl(m):
        nonlocal count
        count += 1
        return f"[[{new_stem}{m.group(1)}]]"

    return pattern.sub(repl, text), count


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    vault = os.getenv("OBSIDIAN_VAULT_PATH")
    if not vault:
        sys.exit("OBSIDIAN_VAULT_PATH no trobat a .env")
    reunions = Path(vault) / "Reunions"

    print(f"Vault: {reunions}")
    print(f"Mode:  {'APPLY' if args.apply else 'DRY-RUN'}")
    print()

    renames = collect_renames(reunions)
    folder_renames = [r for r in renames if r.kind == "folder"]
    yearnote_renames = [r for r in renames if r.kind == "year_note"]

    print("=" * 80)
    print(f"FOLDERS ({len(folder_renames)})")
    print("=" * 80)
    for r in folder_renames:
        print(f"  {r.src.relative_to(reunions)}  →  {r.dst.name}")
    print()

    print("=" * 80)
    print(f"YEAR NOTES ({len(yearnote_renames)})")
    print("=" * 80)
    for r in yearnote_renames:
        print(f"  {r.src.relative_to(reunions)}  →  {r.dst.parent.name}/{r.dst.name}")
    print()

    # Substitucions d'enllaços a tot el vault
    link_pairs = [(r.src.stem, r.dst.stem) for r in yearnote_renames]

    print("=" * 80)
    print("ENLLAÇOS [[...]] a substituir (arreu del vault)")
    print("=" * 80)
    total_subs = 0
    affected_notes = 0
    note_subs: dict[Path, list[tuple[str, str, int]]] = {}
    for note in reunions.rglob("*.md"):
        try:
            text = note.read_text(encoding="utf-8")
        except Exception:
            continue
        note_changes = []
        for old, new in link_pairs:
            _, count = substitute_link(text, old, new)
            if count > 0:
                note_changes.append((old, new, count))
                total_subs += count
        if note_changes:
            affected_notes += 1
            note_subs[note] = note_changes
            rel = note.relative_to(reunions)
            for old, new, count in note_changes:
                print(f"  {rel}  ({count}x)  [[{old}]] → [[{new}]]")
    if total_subs == 0:
        print("  (cap)")
    print()
    print(f"  Total: {total_subs} substitucions a {affected_notes} notes")
    print()

    if not args.apply:
        print("(dry-run — res tocat. Per executar: --apply)")
        return

    # Ordre d'execució crític: primer renombrar year notes (encara dins de la carpeta vella),
    # després renombrar les carpetes.
    print("Aplicant...")
    # Pas 1: renombrar year notes (dins la carpeta vella, abans del rename de carpeta)
    for r in yearnote_renames:
        # El destí es va calcular amb el path post-rename de carpeta; reconstruïm
        # el destí dins la carpeta vella per fer el rename ABANS del rename de carpeta.
        intermediate_dst = r.src.parent / r.dst.name
        r.src.rename(intermediate_dst)
    # Pas 2: renombrar carpetes
    for r in folder_renames:
        r.src.rename(r.dst)
    # Pas 3: substituir enllaços
    for note, changes in note_subs.items():
        text = note.read_text(encoding="utf-8")
        for old, new, _ in changes:
            text, _ = substitute_link(text, old, new)
        note.write_text(text, encoding="utf-8")
    print("Fet.")


if __name__ == "__main__":
    main()
