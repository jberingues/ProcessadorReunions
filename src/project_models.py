"""
Data models for the initial definition of a project.

These models represent structured information extracted from a kick-off meeting,
related emails and documents. They serve as the foundation for an LLM extractor
and for subsequent project tracking.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ── Type aliases ──────────────────────────────────────────────────────────────

SourceType = Literal["meeting", "email", "document"]
"""Where a piece of information was found."""

ExtractionStatus = Literal["explicit", "inferred", "missing"]
"""How confident we are that the information was actually stated."""

MilestoneStatus = Literal["planned", "in_progress", "completed", "at_risk", "cancelled"]
"""Lifecycle state of a project milestone."""


# ── Building blocks ───────────────────────────────────────────────────────────

class EvidenceItem(BaseModel):
    """A traceable reference to the source of an extracted datum."""

    source_type: SourceType
    source_name: str
    """Human-readable name of the file or source (e.g. filename, email subject)."""
    excerpt: str = ""
    """Short verbatim fragment that supports the extraction (optional)."""


class ExtractedField(BaseModel):
    """A single extracted value with its confidence and provenance."""

    value: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    status: ExtractionStatus = "explicit"
    evidence: list[EvidenceItem] = Field(default_factory=list)


class Milestone(BaseModel):
    """A project milestone with its expected date and current status."""

    name: str
    target_date: str | None = None
    """ISO date or free-text description (e.g. 'end of Q2')."""
    status: MilestoneStatus = "planned"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[EvidenceItem] = Field(default_factory=list)


class EffortEstimate(BaseModel):
    """An estimate of the total effort required for the project.

    Points measure effort (1 point = 1 person-day). Cost is in EUR.
    """

    points: float | None = None
    """Effort in points (1 point = 1 person-day)."""
    cost_eur: float | None = None
    """Estimated cost in EUR."""
    detail: str | None = None
    """Free-text breakdown or notes about the estimate."""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    status: ExtractionStatus = "missing"
    evidence: list[EvidenceItem] = Field(default_factory=list)


# ── Main model ────────────────────────────────────────────────────────────────

class ProjectDefinition(BaseModel):
    """Complete initial definition of a project as extracted from source materials."""

    project_name: str
    date_defined: str | None = None
    """ISO date when the project was formally defined."""

    # Core definition
    objective: ExtractedField | None = None
    scope_in: list[ExtractedField] = Field(default_factory=list)
    scope_out: list[ExtractedField] = Field(default_factory=list)
    deliverables: list[ExtractedField] = Field(default_factory=list)

    # Planning
    milestones: list[Milestone] = Field(default_factory=list)
    planning_summary: ExtractedField | None = None
    effort_estimate: EffortEstimate | None = None

    # People and dependencies
    stakeholders: list[ExtractedField] = Field(default_factory=list)
    dependencies: list[ExtractedField] = Field(default_factory=list)

    # Risks and open items
    risks: list[ExtractedField] = Field(default_factory=list)
    open_questions: list[ExtractedField] = Field(default_factory=list)

    # Free-text executive summary (LLM-generated, not extracted)
    executive_summary: str | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def missing_field(evidence: list[EvidenceItem] | None = None) -> ExtractedField:
    """Create an ExtractedField placeholder marked as 'missing'."""
    return ExtractedField(value="", confidence=0.0, status="missing",
                          evidence=evidence or [])


def coverage(definition: ProjectDefinition) -> float:
    """Return the fraction of main fields that are not 'missing' (0.0–1.0).

    Considers: objective, scope_in, scope_out, deliverables, milestones,
    planning_summary, effort_estimate, stakeholders, dependencies, risks,
    open_questions.
    """
    _OPTIONAL_FIELDS = [
        definition.objective,
        definition.planning_summary,
        definition.effort_estimate,
    ]
    _LIST_FIELDS = [
        definition.scope_in,
        definition.scope_out,
        definition.deliverables,
        definition.milestones,
        definition.stakeholders,
        definition.dependencies,
        definition.risks,
        definition.open_questions,
    ]

    total = len(_OPTIONAL_FIELDS) + len(_LIST_FIELDS)
    filled = 0

    for field in _OPTIONAL_FIELDS:
        if field is not None and getattr(field, "status", None) != "missing":
            filled += 1

    for lst in _LIST_FIELDS:
        if lst:
            filled += 1

    return filled / total


# ── Markdown formatter ───────────────────────────────────────────────────────

def format_markdown(definition: ProjectDefinition) -> str:
    """Render a ProjectDefinition as an Obsidian-compatible markdown note."""
    lines: list[str] = []

    # Fitxa
    lines.append("## Fitxa")
    lines.append(f"- **Nom:** {definition.project_name}")
    lines.append(f"- **Data definició:** {definition.date_defined or ''}")
    lines.append("")

    # 1. Objectiu
    lines.append("## 1. Objectiu")
    lines.append(_field_value(definition.objective))
    lines.append("")

    # 2. Abast
    lines.append("## 2. Abast")
    lines.append("### Inclou")
    lines.extend(_field_list(definition.scope_in))
    lines.append("### Fora d'abast")
    lines.extend(_field_list(definition.scope_out))
    lines.append("")

    # 3. Entregables
    lines.append("## 3. Entregables")
    lines.extend(_field_list(definition.deliverables))
    lines.append("")

    # 4. Planificació
    lines.append("## 4. Planificació inicial")
    lines.append("### Resum")
    lines.append(_field_value(definition.planning_summary))
    lines.append("### Fites")
    if definition.milestones:
        for m in definition.milestones:
            date_part = f" — {m.target_date}" if m.target_date else ""
            lines.append(f"- {m.name}{date_part}")
    else:
        lines.append("- ")
    lines.append("")

    # 5. Esforç
    lines.append("## 5. Esforç inicial")
    eff = definition.effort_estimate
    if eff and eff.status != "missing":
        points_str = f"{eff.points:.0f} punts" if eff.points is not None else ""
        cost_str = f"{eff.cost_eur:,.0f} €" if eff.cost_eur is not None else ""
        lines.append(f"- **Punts:** {points_str}")
        lines.append(f"- **Cost:** {cost_str}")
        if eff.detail:
            lines.append(f"- **Detall:** {eff.detail}")
    else:
        lines.append("- **Punts:**")
        lines.append("- **Cost:**")
    lines.append("")

    # 6. Stakeholders
    lines.append("## 6. Stakeholders")
    lines.extend(_field_list(definition.stakeholders))
    lines.append("")

    # 7. Dependències
    lines.append("## 7. Dependències")
    lines.extend(_field_list(definition.dependencies))
    lines.append("")

    # 8. Riscos
    lines.append("## 8. Riscos inicials")
    lines.extend(_field_list(definition.risks))
    lines.append("")

    # 9. Punts oberts
    lines.append("## 9. Punts oberts")
    lines.extend(_field_list(definition.open_questions))
    lines.append("")

    # 10. Resum executiu
    lines.append("## 10. Resum executiu")
    lines.append(definition.executive_summary or "")
    lines.append("")

    # 11. Fonts
    lines.append("## 11. Fonts utilitzades")
    sources = _collect_sources(definition)
    if sources:
        for s in sorted(sources):
            lines.append(f"- {s}")
    else:
        lines.append("- ")
    lines.append("")

    return "\n".join(lines)


def _field_value(field: ExtractedField | None) -> str:
    """Return the value of an ExtractedField, or empty string."""
    if field is None or field.status == "missing" or not field.value:
        return ""
    return field.value


def _field_list(fields: list[ExtractedField]) -> list[str]:
    """Format a list of ExtractedField as bullet points."""
    if not fields:
        return ["- "]
    return [f"- {f.value}" for f in fields if f.value]


def _collect_sources(definition: ProjectDefinition) -> set[str]:
    """Gather all unique source_name values from evidence across all fields."""
    sources: set[str] = set()

    def _scan_evidence(evidence: list[EvidenceItem]) -> None:
        for ev in evidence:
            if ev.source_name:
                sources.add(ev.source_name)

    if definition.objective:
        _scan_evidence(definition.objective.evidence)
    if definition.planning_summary:
        _scan_evidence(definition.planning_summary.evidence)
    if definition.effort_estimate:
        _scan_evidence(definition.effort_estimate.evidence)

    for field_list in (definition.scope_in, definition.scope_out,
                       definition.deliverables, definition.stakeholders,
                       definition.dependencies, definition.risks,
                       definition.open_questions):
        for f in field_list:
            _scan_evidence(f.evidence)

    for m in definition.milestones:
        _scan_evidence(m.evidence)

    return sources
