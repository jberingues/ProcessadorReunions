#!/usr/bin/env python3
"""Migració del vault Reunions/ a l'estructura homogènia.

Renombra fitxers d'estat/històric/resum a la nova convenció i actualitza
enllaços [[...]] dins de les notes afectades. Per defecte fa dry-run; usa
--apply per executar de veritat.

Mapeig de renomenats:
- Reunions/Seguiment/<X>/<estat>.md           → Temes oberts.md
- Reunions/Seguiment/<X>/Històric.md           → 2026 <X>.md
- Reunions/Sincronització/<X>/Resum reunions 2026.md → 2026 <X>.md
- Reunions/Proveïdors/<X>/<X>.md               → 2026 <X>.md
- Reunions/Reunions vàries/<X>/<X>.md          → 2026 <X>.md
- Reunions/Projectes/<X>/<X>.md                → Resum projecte <X>.md

Subfolders amb prefix 'x' (plantilles) es salten.

Usage:
    uv run python scripts/migrate_vault.py            # dry-run
    uv run python scripts/migrate_vault.py --apply    # executar
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


CURRENT_YEAR = "2026"

TYPE_HANDLERS: dict[str, str] = {
    "Seguiment": "seguiment",
    "Sincronització": "sincronitzacio",
    "Proveïdors": "accumulador_2026",
    "Reunions vàries": "accumulador_2026",
    "Projectes": "projectes",
}

SEGUIMENT_PROTECTED = {
    "Històric.md",
    "Ordre del dia propera reunió.md",
    "Temes oberts.md",
}


@dataclass
class Rename:
    src: Path
    dst: Path
    reason: str
    ambiguous: bool = False
    notes: list[str] = field(default_factory=list)


def folder_label(folder: Path) -> str:
    return folder.name.replace("_", " ").replace("[", "").replace("]", "")


def plan_seguiment(subfolder: Path) -> list[Rename]:
    out: list[Rename] = []
    label = folder_label(subfolder)

    historic = subfolder / "Històric.md"
    if historic.exists():
        out.append(Rename(historic, subfolder / f"{CURRENT_YEAR} {label}.md",
                          "Històric → 2026 <X>"))

    candidates = [
        p for p in sorted(subfolder.glob("*.md"))
        if p.name not in SEGUIMENT_PROTECTED
        and not p.name.startswith(f"{CURRENT_YEAR} ")
    ]
    if len(candidates) == 1:
        out.append(Rename(candidates[0], subfolder / "Temes oberts.md",
                          "Estat → Temes oberts"))
    elif len(candidates) > 1:
        out.append(Rename(candidates[0], candidates[0],
                          f"AMBIGÜITAT estat: {[c.name for c in candidates]}",
                          ambiguous=True))
    # 0 candidats: la sèrie no té estat — OK, no rename.
    return out


def plan_sincronitzacio(subfolder: Path) -> list[Rename]:
    label = folder_label(subfolder)
    resum = subfolder / f"Resum reunions {CURRENT_YEAR}.md"
    if not resum.exists():
        return []
    return [Rename(resum, subfolder / f"{CURRENT_YEAR} {label}.md",
                   "Resum reunions → 2026 <X>")]


def plan_accumulador_2026(subfolder: Path) -> list[Rename]:
    """Per Proveïdors i Reunions vàries: un sol fitxer accumulador → 2026 <X>.md."""
    label = folder_label(subfolder)
    new_name = f"{CURRENT_YEAR} {label}.md"
    candidates = [
        p for p in sorted(subfolder.glob("*.md"))
        if p.name != new_name
    ]
    if len(candidates) == 1:
        return [Rename(candidates[0], subfolder / new_name,
                       "<X> → 2026 <X>")]
    if len(candidates) > 1:
        return [Rename(candidates[0], candidates[0],
                       f"AMBIGÜITAT: {[c.name for c in candidates]}",
                       ambiguous=True)]
    return []


def plan_projectes(subfolder: Path) -> list[Rename]:
    """Per Projectes només renombrem el fitxer que coincideix exactament amb el nom del folder
    (e.g. ARIN.md a Projectes/ARIN/). Altres .md root es deixen com estan."""
    label = folder_label(subfolder)
    new_name = f"Resum projecte {label}.md"
    for candidate_name in (f"{subfolder.name}.md", f"{label}.md"):
        candidate = subfolder / candidate_name
        if candidate.exists() and candidate.name != new_name:
            return [Rename(candidate, subfolder / new_name,
                           "<X> → Resum projecte <X>")]
    return []


PLAN_FUNCS = {
    "seguiment": plan_seguiment,
    "sincronitzacio": plan_sincronitzacio,
    "accumulador_2026": plan_accumulador_2026,
    "projectes": plan_projectes,
}


def collect_renames(reunions: Path) -> list[Rename]:
    all_renames: list[Rename] = []
    for type_folder, handler_key in TYPE_HANDLERS.items():
        type_path = reunions / type_folder
        if not type_path.is_dir():
            print(f"  (info) no existeix {type_path}")
            continue
        plan_fn = PLAN_FUNCS[handler_key]
        for subfolder in sorted(type_path.iterdir()):
            if not subfolder.is_dir():
                continue
            if subfolder.name.startswith("x"):
                continue
            all_renames.extend(plan_fn(subfolder))
    return all_renames


def substitute_links(text: str, src_stem: str, dst_stem: str) -> tuple[str, int]:
    """Substitueix [[src_stem]], [[src_stem|alias]], [[src_stem#section]] per la versió nova.
    No toca enllaços amb path complet (e.g. [[Reunions/.../src_stem]])."""
    pattern = re.compile(
        r"\[\[" + re.escape(src_stem) + r"(?=[\]#|])([^\]]*)\]\]"
    )
    count = 0

    def repl(m):
        nonlocal count
        count += 1
        return f"[[{dst_stem}{m.group(1)}]]"

    new_text = pattern.sub(repl, text)
    return new_text, count


def find_path_qualified_refs(vault: Path, src_stem: str, subfolder: Path) -> list[tuple[Path, str]]:
    """Cerca enllaços amb path (e.g. [[Reunions/Seguiment/A10Pro/Històric]]) que apuntin a aquest fitxer.
    Retorna llista (nota, snippet) per revisió manual."""
    out = []
    # Pattern: [[<qualsevol path>/src_stem ( opcional #|alias ) ]]
    pattern = re.compile(
        r"\[\[[^\]\[]*/" + re.escape(src_stem) + r"(?=[\]#|])([^\]]*)\]\]"
    )
    for note in vault.rglob("*.md"):
        try:
            text = note.read_text(encoding="utf-8")
        except Exception:
            continue
        for m in pattern.finditer(text):
            out.append((note, m.group(0)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="Executar de veritat (sense això és dry-run)")
    args = ap.parse_args()

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    vault_root = os.getenv("OBSIDIAN_VAULT_PATH")
    if not vault_root:
        sys.exit("OBSIDIAN_VAULT_PATH no trobat a .env")
    reunions = Path(vault_root) / "Reunions"
    if not reunions.is_dir():
        sys.exit(f"No existeix {reunions}")

    print(f"Vault:  {reunions}")
    print(f"Mode:   {'APPLY' if args.apply else 'DRY-RUN'}")
    print()

    renames = collect_renames(reunions)
    valid = [r for r in renames if not r.ambiguous and r.src != r.dst]
    ambiguous = [r for r in renames if r.ambiguous]

    print("=" * 80)
    print(f"RENOMENATS ({len(valid)} vàlids, {len(ambiguous)} ambigus)")
    print("=" * 80)
    for r in renames:
        rel_src = r.src.relative_to(reunions)
        if r.ambiguous:
            print(f"  AMBIGU  {rel_src.parent}: {r.reason}")
        else:
            print(f"  {rel_src}  →  {r.dst.name}    [{r.reason}]")

    print()
    print("=" * 80)
    print("SUBSTITUCIONS D'ENLLAÇOS [[...]] (curts, dins del subfolder afectat)")
    print("=" * 80)

    total_subs = 0
    total_notes = 0
    for r in valid:
        subfolder = r.src.parent
        for note in sorted(subfolder.rglob("*.md")):
            try:
                text = note.read_text(encoding="utf-8")
            except Exception:
                continue
            _, count = substitute_links(text, r.src.stem, r.dst.stem)
            if count > 0:
                rel = note.relative_to(reunions)
                print(f"  {rel}  ({count}x)  [[{r.src.stem}]] → [[{r.dst.stem}]]")
                total_subs += count
                total_notes += 1

    print()
    print(f"  Total: {total_subs} substitucions a {total_notes} notes")
    print()

    print("=" * 80)
    print("ENLLAÇOS AMB PATH (NO substituïts automàticament — revisió manual)")
    print("=" * 80)
    path_refs_total = 0
    for r in valid:
        refs = find_path_qualified_refs(reunions, r.src.stem, r.src.parent)
        for note, snippet in refs:
            rel = note.relative_to(reunions)
            print(f"  {rel}   {snippet}")
            path_refs_total += 1
    if path_refs_total == 0:
        print("  (cap detectat)")
    else:
        print(f"\n  Total: {path_refs_total} referències amb path. Reviseu manualment.")
    print()

    if args.apply:
        if ambiguous:
            sys.exit("Hi ha ambigüitats sense resoldre. Cancel·lant. "
                     "Reviseu el log i resoleu manualment abans de --apply.")
        print("Aplicant renomenats i substitucions...")
        for r in valid:
            r.src.rename(r.dst)
        for r in valid:
            subfolder = r.dst.parent
            for note in subfolder.rglob("*.md"):
                try:
                    text = note.read_text(encoding="utf-8")
                except Exception:
                    continue
                new_text, count = substitute_links(text, r.src.stem, r.dst.stem)
                if count > 0:
                    note.write_text(new_text, encoding="utf-8")
        print("Fet.")
    else:
        print("(dry-run — res tocat. Per executar: --apply)")


if __name__ == "__main__":
    main()
