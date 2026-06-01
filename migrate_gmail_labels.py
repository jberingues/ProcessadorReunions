"""Migra les etiquetes Gmail del format antic (camí complet, e.g.
`Seguiment/CRA`) al nou (nom de fulla, e.g. `CRA`).

El renombrat conserva l'ID de l'etiqueta i, per tant, totes les assignacions
de fils/missatges. Per defecte fa un **dry-run** (només mostra el pla); cal
`--apply` per executar els canvis a Gmail.

Executar amb:
    uv run python migrate_gmail_labels.py             # dry-run
    uv run python migrate_gmail_labels.py --apply     # aplica els renombrats
    uv run python migrate_gmail_labels.py --include-sincro [--apply]
"""
import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))

load_dotenv(ROOT / ".env")

from calendar_matcher import CalendarMatcher  # noqa: E402
from gmail_fetcher import GmailFetcher  # noqa: E402
from email_archiver import discover_vault_series, plan_label_migration  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true',
                        help="Aplica els renombrats (per defecte només dry-run).")
    parser.add_argument('--include-sincro', action='store_true',
                        help="Inclou les sèries de Sincronització/.")
    args = parser.parse_args()

    vault = os.getenv('OBSIDIAN_VAULT_PATH')
    if not vault:
        print("Error: OBSIDIAN_VAULT_PATH no configurat al .env", file=sys.stderr)
        return 1

    discovery = discover_vault_series(vault, include_sincro=args.include_sincro)
    for w in discovery.warnings:
        print(f"[avís vault] {w}")

    print("Autenticant amb Google...")
    fetcher = GmailFetcher(CalendarMatcher().gmail)
    existing = fetcher.list_user_labels()
    plan = plan_label_migration(existing, discovery)

    print(f"\nEtiquetes Gmail existents: {len(existing)}")
    print(f"Sèries actives al vault: {len(discovery.active)} "
          f"(+ {len(discovery.closed_by_active_label)} tancades)\n")

    if plan.renames:
        print(f"== Renombrats proposats ({len(plan.renames)}) ==")
        for _id, old, new in plan.renames:
            print(f"  {old}  ->  {new}")
    else:
        print("== Cap renombrat proposat ==")

    if plan.skipped_target_exists:
        print(f"\n== Saltats: ja existeix etiqueta plana ({len(plan.skipped_target_exists)}) ==")
        print("   (fusiona manualment a Gmail; el rename crearia un duplicat)")
        for n in plan.skipped_target_exists:
            print(f"  {n}")

    if plan.skipped_collision:
        print(f"\n== Saltats: col·lisió de nom de fulla ({len(plan.skipped_collision)}) ==")
        print("   (dues etiquetes mapegen al mateix nom; resol manualment)")
        for n in plan.skipped_collision:
            print(f"  {n}")

    if plan.not_in_vault:
        print(f"\n== Sense sèrie al vault, es deixen tal qual ({len(plan.not_in_vault)}) ==")
        for n in plan.not_in_vault:
            print(f"  {n}")

    if not args.apply:
        print("\n(dry-run — torna a executar amb --apply per aplicar els renombrats)")
        return 0

    if not plan.renames:
        print("\nRes a aplicar.")
        return 0

    print(f"\nAplicant {len(plan.renames)} renombrats...")
    errors = 0
    for label_id, old, new in plan.renames:
        try:
            fetcher.rename_label(label_id, new)
            print(f"  OK  {old}  ->  {new}")
        except Exception as e:  # noqa: BLE001
            errors += 1
            print(f"  ERROR  {old}  ->  {new}: {e}", file=sys.stderr)
    print(f"\nFet. {len(plan.renames) - errors} renombrats, {errors} errors.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
