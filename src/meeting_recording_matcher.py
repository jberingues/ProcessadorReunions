"""Aparellador entre reunions de Google Calendar i gravacions de Plaud.

Funció pura: donades dues llistes (events del calendari + gravacions Plaud
amb `start_at` ja resolt), retorna parells amb un score de confiança i
les llistes d'elements no aparellats.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from plaud_client import PlaudRecording


# Pesos del score combinat (han de sumar 1.0).
# La durada d'una reunió és molt variable (s'allarguen, s'aturen abans, etc.),
# però l'hora d'inici és bastant fiable. El score dóna prioritat al temps.
_W_TIME = 0.85
_W_DURATION = 0.15

# Trams del score temporal:
#   [0, _PERFECT_TIME_OFFSET_MIN]    → 1.0
#   (perfect, _NEAR_TIME_OFFSET_MIN] → 1.0 → 0.5 lineal
#   (near, _MAX_TIME_OFFSET_MIN]     → 0.5 → 0.0 lineal
#   > max                             → 0.0
_PERFECT_TIME_OFFSET_MIN = 5.0
_NEAR_TIME_OFFSET_MIN = 30.0
_MAX_TIME_OFFSET_MIN = 60.0


class PairStatus(str, Enum):
    AUTO = "auto"            # score alt, confirmat automàticament
    SUGGESTED = "suggested"  # score mig, suggerit (l'usuari ha de confirmar)
    MANUAL = "manual"        # creat manualment per l'usuari a la UI


@dataclass
class Pair:
    event: dict[str, Any]
    recording: PlaudRecording
    score: float
    status: PairStatus


@dataclass
class MatchResult:
    pairs: list[Pair] = field(default_factory=list)
    unmatched_events: list[dict[str, Any]] = field(default_factory=list)
    unmatched_recordings: list[PlaudRecording] = field(default_factory=list)


def _time_score(event_start: datetime, rec_start: datetime) -> float:
    """Score temporal per trams (veure constants _*_TIME_OFFSET_MIN)."""
    delta_min = abs((event_start - rec_start).total_seconds()) / 60.0
    if delta_min <= _PERFECT_TIME_OFFSET_MIN:
        return 1.0
    if delta_min >= _MAX_TIME_OFFSET_MIN:
        return 0.0
    if delta_min <= _NEAR_TIME_OFFSET_MIN:
        # Tram 1.0 → 0.5 entre PERFECT i NEAR
        span = _NEAR_TIME_OFFSET_MIN - _PERFECT_TIME_OFFSET_MIN
        return 1.0 - (delta_min - _PERFECT_TIME_OFFSET_MIN) / span * 0.5
    # Tram 0.5 → 0.0 entre NEAR i MAX
    span = _MAX_TIME_OFFSET_MIN - _NEAR_TIME_OFFSET_MIN
    return 0.5 - (delta_min - _NEAR_TIME_OFFSET_MIN) / span * 0.5


def _duration_score(event_dur_s: float, rec_dur_s: float) -> float:
    """Compara durada de la reunió amb la de la gravació.

    Gravacions més curtes que la reunió (típic — l'usuari atura abans) tenen
    penalització lineal. Gravacions més llargues que la reunió (potser
    encavalca amb la següent) tenen penalització més forta.
    """
    if event_dur_s <= 0 or rec_dur_s <= 0:
        return 0.0
    ratio = rec_dur_s / event_dur_s
    if ratio <= 1.0:
        return ratio
    return max(0.0, 2.0 - ratio)


def _score(event: dict[str, Any], rec: PlaudRecording) -> float:
    if rec.start_at is None:
        return 0.0
    event_start: datetime = event["start"]
    event_end: datetime = event["end"]
    t = _time_score(event_start, rec.start_at)
    if t == 0.0:
        # Sense proximitat temporal, no és un parell vàlid encara que la durada
        # coincideixi: una durada similar entre reunions distants és casualitat.
        return 0.0
    d = _duration_score((event_end - event_start).total_seconds(), rec.duration_seconds)
    return _W_TIME * t + _W_DURATION * d


def match(
    events: list[dict[str, Any]],
    recordings: list[PlaudRecording],
    auto_threshold: float = 0.9,
    min_threshold: float = 0.3,
) -> MatchResult:
    """Aparella events i gravacions 1:1 amb un algorisme greedy.

    - Calcula el score de tots els parells (event, recording).
    - Ordena per score descendent.
    - Va assignant; cada event i cada recording només pot aparèixer un cop.
    - Parells amb score ≥ auto_threshold → PairStatus.AUTO.
    - Parells amb score ≥ min_threshold però < auto_threshold → SUGGESTED.
    - Per sota de min_threshold no s'aparella.
    """
    candidates: list[tuple[float, int, int]] = []
    for ei, ev in enumerate(events):
        for ri, rec in enumerate(recordings):
            s = _score(ev, rec)
            if s >= min_threshold:
                candidates.append((s, ei, ri))
    candidates.sort(key=lambda x: x[0], reverse=True)

    used_events: set[int] = set()
    used_recs: set[int] = set()
    pairs: list[Pair] = []
    for score, ei, ri in candidates:
        if ei in used_events or ri in used_recs:
            continue
        used_events.add(ei)
        used_recs.add(ri)
        status = PairStatus.AUTO if score >= auto_threshold else PairStatus.SUGGESTED
        pairs.append(Pair(event=events[ei], recording=recordings[ri], score=score, status=status))

    unmatched_events = [ev for i, ev in enumerate(events) if i not in used_events]
    unmatched_recs = [r for i, r in enumerate(recordings) if i not in used_recs]
    return MatchResult(pairs=pairs, unmatched_events=unmatched_events, unmatched_recordings=unmatched_recs)
