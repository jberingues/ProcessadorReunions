"""Quick test for ProjectDefinitionExtractor with real vault data."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, str(Path(__file__).parent / "src"))

from project_definition_extractor import ProjectDefinitionExtractor, ProjectSource
from project_models import coverage, format_markdown

VAULT = Path(os.getenv("OBSIDIAN_VAULT_PATH"))
PROJECT_DIR = VAULT / "Reunions" / "Projectes" / "VDPJCM"


def load_meeting(filename: str) -> ProjectSource:
    path = PROJECT_DIR / "Reunions" / filename
    text = path.read_text(encoding="utf-8")
    return ProjectSource(source_type="meeting", source_name=filename, content=text)


def main():
    sources = [
        load_meeting("260316_Definició_tècnica_VDJCM_MVS1_(Integració_Abrebox)_[VDP2-681]~.md"),
        load_meeting("260323_Proximitat.md"),
    ]

    extractor = ProjectDefinitionExtractor()
    result = extractor.extract(project_name="VDPJCM", sources=sources)

    print("=" * 60)
    print(f"Project: {result.project_name}")
    print(f"Code: {result.project_code}")
    print(f"Date defined: {result.date_defined}")
    print(f"Coverage: {coverage(result):.0%}")
    print("=" * 60)

    if result.objective:
        print(f"\nObjective [{result.objective.status}]: {result.objective.value[:200]}")

    if result.scope_in:
        print(f"\nScope IN ({len(result.scope_in)}):")
        for s in result.scope_in:
            print(f"  - [{s.status}] {s.value[:150]}")

    if result.scope_out:
        print(f"\nScope OUT ({len(result.scope_out)}):")
        for s in result.scope_out:
            print(f"  - [{s.status}] {s.value[:150]}")

    if result.deliverables:
        print(f"\nDeliverables ({len(result.deliverables)}):")
        for d in result.deliverables:
            print(f"  - [{d.status}] {d.value[:150]}")

    if result.milestones:
        print(f"\nMilestones ({len(result.milestones)}):")
        for m in result.milestones:
            print(f"  - {m.name} | target: {m.target_date} | status: {m.status}")

    if result.stakeholders:
        print(f"\nStakeholders ({len(result.stakeholders)}):")
        for s in result.stakeholders:
            print(f"  - [{s.status}] {s.value[:150]}")

    if result.dependencies:
        print(f"\nDependencies ({len(result.dependencies)}):")
        for d in result.dependencies:
            print(f"  - [{d.status}] {d.value[:150]}")

    if result.risks:
        print(f"\nRisks ({len(result.risks)}):")
        for r in result.risks:
            print(f"  - [{r.status}] {r.value[:150]}")

    if result.open_questions:
        print(f"\nOpen questions ({len(result.open_questions)}):")
        for q in result.open_questions:
            print(f"  - [{q.status}] {q.value[:150]}")

    if result.executive_summary:
        print(f"\nExecutive summary:\n{result.executive_summary[:500]}")

    # Markdown output
    md = format_markdown(result)
    out_path = Path("output_VDPJCM.md")
    out_path.write_text(md, encoding="utf-8")
    print(f"\nMarkdown written to {out_path}")
    print("\n" + "=" * 60)
    print(md)


if __name__ == "__main__":
    main()
