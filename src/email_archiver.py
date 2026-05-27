"""Lògica pura per a l'arxivat de correus al vault d'Obsidian.

Descobreix sèries del vault (carpetes amb subfolder `Reunions/`),
calcula les etiquetes Gmail corresponents, decideix el destí d'un fil
segons les seves etiquetes, i gestiona el JSON d'idempotència.

Cap dependència de PySide6 ni de l'API de Gmail — pot ser testejat amb
fitxers/dades en memòria.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


# Top-levels dins de Reunions/ amb tractament especial. La resta s'inclouen
# automàticament si contenen alguna sèrie (carpeta amb subfolder `Reunions/`).
SERIES_TOP_LEVEL_CLOSED = 'Temes seguiment tancats'
SERIES_TOP_LEVEL_SINCRO = 'Sincronització'

# Top-levels que MAI s'escanegen com a sèries actives.
# - zConfig: configuració del vault, no és contingut.
# - SERIES_TOP_LEVEL_CLOSED: tractament dedicat (closed_by_active_label).
# Sincronització s'afegeix dinàmicament a aquesta llista quan `include_sincro=False`.
SERIES_TOP_LEVEL_EXCLUDED = {'zConfig', SERIES_TOP_LEVEL_CLOSED}

# Prioritat per decidir destí quan un fil té múltiples etiquetes de vault.
# Els top-levels no listats reben prioritat residual (la més baixa).
DISPATCH_PRIORITY = ['Projectes', 'Proveïdors', 'Seguiment', 'Reunions vàries']

# Path relatiu del JSON d'idempotència dins del vault.
PROCESSED_STORE_REL = 'zConfig/.processed_threads.json'


@dataclass
class VaultDiscovery:
    """Resultat d'escanejar el vault.

    - `active`: { etiqueta → directori destí } per a sèries actives.
      Aquestes són les etiquetes que han d'existir a Gmail.
    - `closed_by_active_label`: { 'Seguiment/<X>' → directori tancat } per
      capturar correus tardans d'etiquetes encara presents a Gmail però
      la sèrie ja és a `Temes seguiment tancats/`.
    """
    active: dict[str, Path] = field(default_factory=dict)
    closed_by_active_label: dict[str, Path] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class DispatchResult:
    """Resultat de decidir on arxivar un fil."""
    dest: Path | None
    primary_label: str | None
    extra_labels: list[str]
    is_closed: bool = False
    warning: str | None = None


def _is_template(name: str) -> bool:
    """Carpetes que comencen per 'x' són plantilles."""
    return name.startswith('x')


def _walk_series(top_level_dir: Path, label_prefix: str) -> list[tuple[str, Path]]:
    """Recorre `top_level_dir` recursivament i retorna (etiqueta, path) per
    a cada directori que contingui un subfolder `Reunions/`.

    Salta x* i zConfig. Si una carpeta té `Reunions/`, la considera sèrie
    final i no baixa més (no s'admet niu de sèries).
    """
    found: list[tuple[str, Path]] = []
    if not top_level_dir.exists():
        return found
    for child in sorted(top_level_dir.iterdir()):
        if not child.is_dir() or _is_template(child.name) or child.name == 'zConfig':
            continue
        rel = child.relative_to(top_level_dir).as_posix()
        label = f"{label_prefix}/{rel}"
        if (child / 'Reunions').is_dir():
            found.append((label, child))
        else:
            found.extend(_walk_series(child, label))
    return found


def discover_vault_series(vault_path: Path | str, include_sincro: bool = False) -> VaultDiscovery:
    """Descobreix totes les sèries del vault a `Reunions/`.

    Args:
        vault_path: arrel del vault d'Obsidian.
        include_sincro: si True, inclou `Sincronització/` com a top-level vàlid.
    """
    discovery = VaultDiscovery()
    reunions_root = Path(vault_path) / 'Reunions'
    if not reunions_root.exists():
        discovery.warnings.append(f"No s'ha trobat {reunions_root}")
        return discovery

    excluded = set(SERIES_TOP_LEVEL_EXCLUDED)
    if not include_sincro:
        excluded.add(SERIES_TOP_LEVEL_SINCRO)

    for top in sorted(reunions_root.iterdir()):
        if not top.is_dir() or _is_template(top.name) or top.name in excluded:
            continue
        for label, path in _walk_series(top, top.name):
            discovery.active[label] = path

    # Tancades: les indexem per l'etiqueta *activa* esperada perquè el cas
    # tardà arriba amb 'Seguiment/<X>' (mai amb 'Temes seguiment tancats/<X>').
    closed_root = reunions_root / SERIES_TOP_LEVEL_CLOSED
    if closed_root.exists():
        for child in sorted(closed_root.iterdir()):
            if not child.is_dir() or _is_template(child.name):
                continue
            if (child / 'Reunions').is_dir():
                active_label = f"Seguiment/{child.name}"
                discovery.closed_by_active_label[active_label] = child

    return discovery


def pick_destination(thread_label_names: list[str], discovery: VaultDiscovery) -> DispatchResult:
    """Decideix on arxivar un fil segons les seves etiquetes Gmail.

    Aplica DISPATCH_PRIORITY entre les etiquetes que matchegen sèries del
    vault. Si la primary és una sèrie tancada, marca el resultat amb
    `is_closed=True` i deixa un warning.
    """
    vault_labels = [
        l for l in thread_label_names
        if l in discovery.active or l in discovery.closed_by_active_label
    ]
    if not vault_labels:
        return DispatchResult(
            dest=None, primary_label=None, extra_labels=[],
            warning=f"Sense etiqueta de vault entre {thread_label_names!r}"
        )

    def priority_of(label: str) -> int:
        top = label.split('/', 1)[0]
        try:
            return DISPATCH_PRIORITY.index(top)
        except ValueError:
            return len(DISPATCH_PRIORITY)

    vault_labels.sort(key=priority_of)
    primary = vault_labels[0]
    extras = list(vault_labels[1:])

    if primary in discovery.active:
        return DispatchResult(
            dest=discovery.active[primary],
            primary_label=primary,
            extra_labels=extras,
            is_closed=False,
        )
    return DispatchResult(
        dest=discovery.closed_by_active_label[primary],
        primary_label=primary,
        extra_labels=extras,
        is_closed=True,
        warning=f"Correu tardà: etiqueta {primary} però sèrie tancada",
    )


# --- Normalització de noms ---

_REPLY_PREFIX_RE = re.compile(r'^(re|fwd|fw|rv|rep)\s*:\s*', re.IGNORECASE)


def normalize_subject(subject: str, max_len: int = 60) -> str:
    """Neteja un assumpte per fer-lo apte com a stem de fitxer.

    - Treu prefixos Re:/Fwd:/Fw:/Rv:/Rep: (repetidament).
    - Elimina chars problemàtics de path.
    - Col·lapsa whitespace.
    - Retalla a `max_len`.
    - Espais → underscores (coherent amb `ObsidianWriter._clean`).
    """
    s = (subject or '(sense assumpte)').strip()
    while True:
        new = _REPLY_PREFIX_RE.sub('', s, count=1)
        if new == s:
            break
        s = new.strip()
    for c in '<>:"/\\|?*':
        s = s.replace(c, '')
    s = ' '.join(s.split())
    if len(s) > max_len:
        s = s[:max_len].rstrip()
    if not s:
        s = 'sense_assumpte'
    return s.replace(' ', '_')


def _safe_filename(original: str) -> str:
    safe = original or 'adjunt'
    for c in '<>:"/\\|?*':
        safe = safe.replace(c, '_')
    return safe


def _split_stem_ext(safe: str) -> tuple[str, str]:
    stem, dot, ext = safe.rpartition('.')
    if not dot:
        return safe, ''
    return stem, '.' + ext


def unique_attachment_path(files_dir: Path, date_prefix: str, original_name: str) -> Path:
    """Calcula un path no-col·lisionant per a un adjunt.

    Format: `<files_dir>/<date_prefix>_<original_name>`. Si existeix,
    afegeix sufix `_2`, `_3`, … abans de l'extensió.
    """
    stem, ext = _split_stem_ext(_safe_filename(original_name))
    base = f"{date_prefix}_{stem}"
    candidate = files_dir / f"{base}{ext}"
    if not candidate.exists():
        return candidate
    i = 2
    while True:
        candidate = files_dir / f"{base}_{i}{ext}"
        if not candidate.exists():
            return candidate
        i += 1


def place_attachment(files_dir: Path, date_prefix: str, original_name: str, data: bytes) -> Path:
    """Desa un adjunt amb nom <date_prefix>_<original> de manera idempotent.

    - Si el path candidate no existeix: l'escriu i el retorna.
    - Si existeix amb bytes idèntics: reusa el path (no escriu res). Permet
      regenerar un fil sense duplicar adjunts.
    - Si existeix amb bytes diferents: afegeix sufix `_2`, `_3`, ... amb
      `unique_attachment_path`.
    """
    files_dir.mkdir(parents=True, exist_ok=True)
    stem, ext = _split_stem_ext(_safe_filename(original_name))
    candidate = files_dir / f"{date_prefix}_{stem}{ext}"
    if candidate.exists():
        try:
            if candidate.read_bytes() == data:
                return candidate
        except OSError:
            pass
        candidate = unique_attachment_path(files_dir, date_prefix, original_name)
    candidate.write_bytes(data)
    return candidate


# --- Idempotència ---

def load_processed_store(vault_path: Path | str) -> dict:
    path = Path(vault_path) / PROCESSED_STORE_REL
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return {}


def save_processed_store(vault_path: Path | str, store: dict) -> None:
    path = Path(vault_path) / PROCESSED_STORE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding='utf-8')


def needs_archive(store: dict, thread_id: str, current_message_count: int) -> bool:
    """True si el fil és nou o ha crescut des de la darrera arxivada."""
    entry = store.get(thread_id)
    if entry is None:
        return True
    return current_message_count > entry.get('message_count', 0)


def mark_archived(store: dict, thread_id: str, message_count: int, dest_rel_path: str) -> None:
    store[thread_id] = {
        'message_count': message_count,
        'archived_at': datetime.now(timezone.utc).isoformat(),
        'dest_path': dest_rel_path,
    }


@dataclass
class LabelSyncResult:
    """Resum d'una sincronització d'etiquetes vault → Gmail."""
    created: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (etiqueta, error)
    orphan: list[str] = field(default_factory=list)              # a Gmail, no al vault
    closed: list[str] = field(default_factory=list)              # sèrie tancada


def sync_gmail_labels(fetcher, discovery: VaultDiscovery, log=None) -> LabelSyncResult:
    """Crea a Gmail les etiquetes que falten respecte el vault.

    No esborra cap etiqueta de Gmail (decisió de disseny: orphans s'avisen,
    mai s'eliminen automàticament). El `log` és un callable opcional que
    rep missatges de progrés (per a UI live)."""
    existing_names = {l['name'] for l in fetcher.list_user_labels()}
    expected = set(discovery.active.keys())
    result = LabelSyncResult()

    for name in sorted(expected - existing_names):
        try:
            fetcher.create_label(name)
            result.created.append(name)
            if log:
                log(f"+ Creada etiqueta: {name}")
        except Exception as e:
            result.failed.append((name, str(e)))
            if log:
                log(f"! Error creant {name}: {e}")

    for orphan in sorted(existing_names - expected):
        if orphan in discovery.closed_by_active_label:
            result.closed.append(orphan)
            if log:
                log(f"~ Sèrie tancada: {orphan} (esborra l'etiqueta a Gmail manualment quan vulguis)")
        else:
            result.orphan.append(orphan)
            if log:
                log(f"? Etiqueta Gmail sense sèrie corresponent al vault: {orphan}")

    return result
