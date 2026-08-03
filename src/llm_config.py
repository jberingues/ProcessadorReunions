"""Configuració compartida de les crides LLM: tiering de models, esforç de
raonament i registre de consum de tokens.

Tiering (.env):
  LLM_MODELH — model "hard": anàlisi de reunions (analyze/summarize) i
      extracció de definició de projecte, on la qualitat del resum importa.
  LLM_MODELL — model "light": extracció mecànica (detecció d'errors de
      transcripció, daily scrum, resum de correus), on un model petit rendeix
      pràcticament igual per una fracció del cost. Si no està definit, cau a
      LLM_MODELH (comportament anterior).
  LLM_REASONING_EFFORT — esforç de raonament per a models que en tenen
      (gpt-5.x, o-sèrie...). Default 'low': per a tasques d'extracció,
      l'esforç per defecte del proveïdor ('medium') crema tokens de raonament
      ocults facturats com a output sense guany apreciable. Valors habituals:
      none/low/medium/high (el que suporti el proveïdor). Valor buit → no
      s'envia el paràmetre (comportament del proveïdor per defecte).

Registre de consum: els helpers log_* escriuen una línia INFO per crida a
data/app.log (prompt/completion/total i, si el proveïdor ho reporta, tokens
de raonament i de cache). Serveix per veure on va el cost i validar canvis.
"""
import logging
import os

logger = logging.getLogger(__name__)


def model_hard() -> "str | None":
    return os.getenv('LLM_MODELH')


def model_light() -> "str | None":
    return os.getenv('LLM_MODELL') or os.getenv('LLM_MODELH')


def reasoning_effort() -> "str | None":
    value = os.getenv('LLM_REASONING_EFFORT', 'low').strip()
    return value or None


def log_crew_usage(label: str, crew) -> None:
    """Registra el consum acumulat d'un crew.kickoff() (CrewAI: usage_metrics)."""
    m = getattr(crew, 'usage_metrics', None)
    if m is None:
        return
    logger.info(
        "LLM ús [%s]: prompt=%d (cache=%d) completion=%d total=%d crides=%d",
        label,
        getattr(m, 'prompt_tokens', 0),
        getattr(m, 'cached_prompt_tokens', 0),
        getattr(m, 'completion_tokens', 0),
        getattr(m, 'total_tokens', 0),
        getattr(m, 'successful_requests', 0),
    )


def log_completion_usage(label: str, response) -> None:
    """Registra el consum d'una crida litellm.completion directa."""
    usage = getattr(response, 'usage', None)
    if usage is None:
        return
    details = getattr(usage, 'completion_tokens_details', None)
    reasoning = getattr(details, 'reasoning_tokens', None) if details else None
    extra = f" (raonament={reasoning})" if reasoning else ""
    logger.info(
        "LLM ús [%s]: prompt=%d completion=%d%s total=%d",
        label,
        getattr(usage, 'prompt_tokens', 0),
        getattr(usage, 'completion_tokens', 0),
        extra,
        getattr(usage, 'total_tokens', 0),
    )
