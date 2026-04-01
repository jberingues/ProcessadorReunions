"""
Extract a structured ProjectDefinition from source materials using an LLM.

Given a set of input sources (kick-off meeting transcript, emails, documents),
builds a unified context and invokes an LLM to produce a ProjectDefinition.
"""

from __future__ import annotations

import os
import re
import logging

import litellm
from json_repair import repair_json
from pydantic import BaseModel

from project_models import (
    ExtractedField,
    Milestone,
    EffortEstimate,
    ProjectDefinition,
    SourceType,
)

logger = logging.getLogger(__name__)

# ── Max tokens per source to avoid exceeding context limits ──────────────────
_MAX_SOURCE_CHARS = 30_000


# ── Input model ──────────────────────────────────────────────────────────────

class ProjectSource(BaseModel):
    """A single input source for project definition extraction."""

    source_type: SourceType
    source_name: str
    content: str


# ── Prompt ───────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a project analyst. Given source materials about a project, extract a \
structured JSON definition.

IMPORTANT: All extracted text values MUST be written in Catalan (català).

RULES:
- Only extract information that is present in the sources.
- NEVER invent or hallucinate data.
- For each extracted field, set "status" to:
  - "explicit" if clearly stated in the sources
  - "inferred" if you had to deduce it from context
  - "missing" if the information is not available (set value to "")
- Set "confidence" between 0.0 and 1.0.
- For "evidence", reference the source by its exact "source_name" and include a \
short excerpt when possible.
- For effort estimates: the organization measures effort in "points" \
(1 point = 1 person-day of work) and cost in EUR. Extract both if mentioned.
- For "date_defined": use the date of the earliest meeting source, NOT dates \
from document filenames or PDF metadata.
- Return ONLY valid JSON, no markdown fences, no extra text.
"""

_USER_PROMPT_TEMPLATE = """\
Project name: {project_name}

=== SOURCES ===
{sources_block}
=== END SOURCES ===

Extract the project definition as a JSON object with this structure:
{{
  "project_name": "{project_name}",
  "date_defined": null or ISO date string,
  "objective": {{"value": "...", "confidence": 0.0-1.0, "status": "explicit|inferred|missing", "evidence": [{{"source_type": "...", "source_name": "...", "excerpt": "..."}}]}},
  "scope_in": [same field format],
  "scope_out": [same field format],
  "deliverables": [same field format],
  "milestones": [{{"name": "...", "target_date": null or string, "status": "planned", "confidence": 0.0-1.0, "evidence": [...]}}],
  "planning_summary": same field format or null,
  "effort_estimate": {{"points": number or null, "cost_eur": number or null, "detail": "free-text breakdown", "confidence": 0.0-1.0, "status": "...", "evidence": [...]}} or null,
  "stakeholders": [same field format],
  "dependencies": [same field format],
  "risks": [same field format],
  "open_questions": [same field format],
  "executive_summary": "Brief 3-5 sentence summary of the project"
}}

If information for a section is not available, use an empty list [] for list \
fields or null for optional fields. Do NOT invent information.
"""


# ── Extractor ────────────────────────────────────────────────────────────────

class ProjectDefinitionExtractor:
    """Extracts a ProjectDefinition from source materials via LLM."""

    def __init__(self, model: str | None = None):
        self.model = model or os.getenv("LLM_MODELH")

    def extract(self, project_name: str, sources: list[ProjectSource]) -> ProjectDefinition:
        """Extract a ProjectDefinition from the given sources.

        Returns a minimal definition with project_name if the LLM call
        or parsing fails.
        """
        context = self._build_sources_block(sources)
        messages = self._build_messages(project_name, context)

        try:
            raw = self._call_llm(messages)
            return self._parse_response(raw, project_name)
        except Exception:
            logger.exception("Failed to extract project definition")
            return self._empty_definition(project_name)

    # ── Internal steps ───────────────────────────────────────────────────

    def _build_sources_block(self, sources: list[ProjectSource]) -> str:
        """Format all sources into a single text block."""
        parts = []
        for src in sources:
            content = _truncate(src.content, _MAX_SOURCE_CHARS)
            label = f"[{src.source_type.upper()}] {src.source_name}"
            parts.append(f"--- {label} ---\n{content}")
        return "\n\n".join(parts)

    def _build_messages(self, project_name: str, sources_block: str) -> list[dict]:
        """Build the chat messages for the LLM call."""
        user_content = _USER_PROMPT_TEMPLATE.format(
            project_name=project_name,
            sources_block=sources_block,
        )
        return [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

    def _call_llm(self, messages: list[dict]) -> str:
        """Invoke the LLM and return the raw response text."""
        response = litellm.completion(model=self.model, messages=messages)
        return response.choices[0].message.content.strip()

    def _parse_response(self, raw: str, project_name: str) -> ProjectDefinition:
        """Parse the LLM response into a ProjectDefinition."""
        cleaned = _strip_json_fences(raw)
        data = repair_json(cleaned, return_objects=True)

        if not isinstance(data, dict):
            logger.warning("LLM returned non-dict JSON, using empty definition")
            return self._empty_definition(project_name)

        # Normalize common LLM quirks before validation
        _normalize_evidence_types(data)
        _normalize_simple_strings(data)

        # Ensure project_name is set
        data["project_name"] = project_name

        try:
            return ProjectDefinition.model_validate(data)
        except Exception as e:
            logger.warning("Pydantic validation failed, attempting partial parse: %s", e)
            return self._partial_parse(data, project_name)

    def _partial_parse(self, data: dict, project_name: str) -> ProjectDefinition:
        """Best-effort parse: extract what we can, skip the rest."""
        definition = self._empty_definition(project_name)

        definition.date_defined = data.get("date_defined")
        definition.executive_summary = data.get("executive_summary")

        # Try individual fields, skip on error
        definition.objective = _try_parse_field(data.get("objective"))
        definition.planning_summary = _try_parse_field(data.get("planning_summary"))

        for list_name in ("scope_in", "scope_out", "deliverables",
                          "stakeholders", "dependencies", "risks", "open_questions"):
            items = _try_parse_field_list(data.get(list_name))
            if items:
                setattr(definition, list_name, items)

        milestones = _try_parse_milestone_list(data.get("milestones"))
        if milestones:
            definition.milestones = milestones

        effort = _try_parse_effort(data.get("effort_estimate"))
        if effort:
            definition.effort_estimate = effort

        return definition

    @staticmethod
    def _empty_definition(project_name: str) -> ProjectDefinition:
        """Return a minimal valid ProjectDefinition."""
        return ProjectDefinition(project_name=project_name)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _normalize_evidence_types(data: dict) -> None:
    """Lowercase source_type in evidence items (LLMs often return MEETING)."""
    for value in data.values():
        items = value if isinstance(value, list) else ([value] if isinstance(value, dict) else [])
        for item in items:
            if not isinstance(item, dict):
                continue
            for ev in item.get("evidence", []):
                if isinstance(ev, dict) and isinstance(ev.get("source_type"), str):
                    ev["source_type"] = ev["source_type"].lower()


def _normalize_simple_strings(data: dict) -> None:
    """Flatten fields that should be plain strings but LLM returned as dicts."""
    for key in ("date_defined", "executive_summary"):
        val = data.get(key)
        if isinstance(val, dict):
            data[key] = val.get("value", str(val))


def _truncate(text: str, max_chars: int) -> str:
    """Truncate text to max_chars, adding a marker if truncated."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n[... truncated ...]"


def _strip_json_fences(text: str) -> str:
    """Remove markdown ```json fences from LLM output."""
    text = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def _try_parse_field(raw: object) -> ExtractedField | None:
    """Try to parse a single ExtractedField from a dict."""
    if not isinstance(raw, dict):
        return None
    try:
        return ExtractedField.model_validate(raw)
    except Exception:
        return None


def _try_parse_field_list(raw: object) -> list[ExtractedField]:
    """Try to parse a list of ExtractedField from a list of dicts."""
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw:
        field = _try_parse_field(item)
        if field:
            result.append(field)
    return result


def _try_parse_milestone_list(raw: object) -> list[Milestone]:
    """Try to parse a list of Milestone from a list of dicts."""
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            result.append(Milestone.model_validate(item))
        except Exception:
            continue
    return result


def _try_parse_effort(raw: object) -> EffortEstimate | None:
    """Try to parse an EffortEstimate from a dict."""
    if not isinstance(raw, dict):
        return None
    try:
        return EffortEstimate.model_validate(raw)
    except Exception:
        return None
