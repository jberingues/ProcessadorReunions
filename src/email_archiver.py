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

# Marcador que identifica una carpeta com a sèrie a efectes d'etiquetes Gmail
# i dispatch de correus. L'usuari ha de crear `Correus/` (pot quedar buida)
# a cada sèrie que vulgui sincronitzar amb Gmail. Es trien `Correus/` com a
# marcador en lloc de `Reunions/` perquè algunes sèries reben només correus
# (sense reunions) i altres reunions sense voler arxivar correus.
SERIES_SUBFOLDER_MARKER = 'Correus'

# Subcarpetes estructurals d'una sèrie que mai són sèries pròpies. Es salten
# en recórrer el vault buscant sèries niu (e.g. dins de Proveïdors/ARROW/ no
# volem que Reunions/ o Fitxers/ comptin com a sub-sèries).
NON_SERIES_SUBFOLDERS = {'zConfig', 'Reunions', SERIES_SUBFOLDER_MARKER, 'Fitxers'}


def _is_series_folder(path: Path) -> bool:
    return (path / SERIES_SUBFOLDER_MARKER).is_dir()


@dataclass
class VaultDiscovery:
    """Resultat d'escanejar el vault.

    Les etiquetes Gmail són el **nom de fulla** de la sèrie (e.g. `CRA`,
    `Microchip`), no el camí complet. Així l'etiqueta és invariant quan la
    sèrie es trasllada entre top-levels (Seguiment → Projectes → Reunions
    vàries → tancades). Conseqüència: els noms de fulla han de ser únics al
    vault; les col·lisions s'avisen a `warnings` i només es conserva la
    primera ocurrència.

    - `active`: { etiqueta_fulla → directori destí } per a sèries actives.
      Aquestes són les etiquetes que han d'existir a Gmail.
    - `closed_by_active_label`: { etiqueta_fulla → directori tancat } per
      capturar correus tardans d'etiquetes encara presents a Gmail però
      la sèrie ja és a `Temes seguiment tancats/`.
    - `top_level`: { etiqueta_fulla → top-level } per resoldre la prioritat
      de dispatch (l'etiqueta ja no conté el top-level). Les tancades es
      mapegen a 'Seguiment'.
    """
    active: dict[str, Path] = field(default_factory=dict)
    closed_by_active_label: dict[str, Path] = field(default_factory=dict)
    top_level: dict[str, str] = field(default_factory=dict)
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


def _walk_series(directory: Path) -> list[tuple[str, Path]]:
    """Recorre `directory` recursivament i retorna (nom_fulla, path) per a cada
    directori que contingui el marcador `SERIES_SUBFOLDER_MARKER` (`Correus/`).

    Suporta **niu real**: una carpeta sèrie pot contenir sub-sèries (e.g.
    `Proveïdors/ARROW/` amb correus propis i `Proveïdors/ARROW/Microchip/`
    també amb correus). Per això NO s'atura en trobar una sèrie — continua
    descendint. Salta x*, i les subcarpetes estructurals (`Reunions/`,
    `Correus/`, `Fitxers/`, `zConfig`) que mai són sèries pròpies.

    L'etiqueta és el **nom de la carpeta fulla**, no el camí.
    """
    found: list[tuple[str, Path]] = []
    if not directory.exists():
        return found
    for child in sorted(directory.iterdir()):
        if (not child.is_dir() or _is_template(child.name)
                or child.name in NON_SERIES_SUBFOLDERS):
            continue
        if _is_series_folder(child):
            found.append((child.name, child))
        # Descendim sempre: una sèrie pot contenir sub-sèries.
        found.extend(_walk_series(child))
    return found


def discover_vault_series(vault_path: Path | str, include_sincro: bool = False) -> VaultDiscovery:
    """Descobreix totes les sèries del vault a `Reunions/`.

    L'etiqueta de cada sèrie és el seu nom de fulla (vegeu `VaultDiscovery`).
    Detecta col·lisions de nom entre top-levels diferents i les avisa.

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
        for leaf, path in _walk_series(top):
            if leaf in discovery.active:
                discovery.warnings.append(
                    f"Col·lisió d'etiqueta '{leaf}': ja existeix a "
                    f"{discovery.active[leaf]}, s'ignora {path}"
                )
                continue
            discovery.active[leaf] = path
            discovery.top_level[leaf] = top.name

    # Tancades: les indexem per l'etiqueta de fulla esperada. Com que
    # l'etiqueta és invariant al trasllat, el correu tardà arriba amb el
    # mateix nom de fulla que tindria activa. Es mapegen a 'Seguiment' per a
    # la prioritat de dispatch (origen conceptual de les tancades).
    closed_root = reunions_root / SERIES_TOP_LEVEL_CLOSED
    for leaf, path in _walk_series(closed_root):
        discovery.closed_by_active_label[leaf] = path
        discovery.top_level.setdefault(leaf, 'Seguiment')

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
        # L'etiqueta ja no conté el top-level: el resolem via discovery.
        top = discovery.top_level.get(label, '')
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


# --- Retall de cites en respostes ---

# Línia d'atribució de resposta: "El dia 9 de jul. 2026, X va escriure:",
# "On Mon, Jul 9, 2026 ... wrote:", "El 9/7/26, X escribió:".
_QUOTE_ATTRIBUTION_RE = re.compile(
    r'^(El|On|Am|Le)\s.{0,200}(va escriure|escrigué|escribió|wrote|schrieb)\s*:\s*$',
    re.IGNORECASE,
)
# Separador clàssic "-----Missatge original-----" (Outlook i derivats).
_ORIGINAL_MSG_RE = re.compile(
    r'^\s*-{2,}\s*(Missatge original|Original Message|Mensaje original)',
    re.IGNORECASE,
)
# Bloc de capçaleres inline (Outlook): línia "De:/From:" seguida a prop
# d'una "Enviat:/Sent:/Data:...". html2text pot envoltar les claus amb '*'.
_HEADER_FIRST_RE = re.compile(r'^\s*\**(De|From|Von)\**\s*:\s*\S', re.IGNORECASE)
_HEADER_FOLLOW_RE = re.compile(
    r'^\s*\**(Enviat|Enviado|Sent|Data|Date|Per a|Para|To|A)\**\s*:', re.IGNORECASE,
)


def trim_quoted_reply(body: str) -> str:
    """Retalla la cua citada d'una resposta (l'històric del fil que el client
    de correu repeteix sota de cada missatge).

    En un fil de N missatges, cada resposta duplica tot l'anterior: la nota
    arxivada creix quadràticament i, com a font per a un LLM, és soroll. El
    fil sencer ja queda recollit per les seccions per-missatge de la nota (i
    l'original sempre és a Gmail).

    Heurística de tall (la posició MÉS AMUNT que coincideixi):
      - línia d'atribució "El dia ... va escriure:" / "On ... wrote:"
      - separador "-----Missatge original-----"
      - bloc de capçaleres inline "De:/From:" + "Enviat:/Sent:" a ≤3 línies
      - tirada de ≥2 línies consecutives començant per '>'

    Prudència: si el tall cau a la primera línia o deixa el cos buit, es
    retorna el text sencer (millor soroll que perdre contingut). Pensat per a
    RESPOSTES (2n missatge en endavant), no per a reenviats: en un reenviat
    el contingut d'interès és justament sota les capçaleres inline.
    """
    lines = body.splitlines()
    cut = None
    for i, line in enumerate(lines):
        if _QUOTE_ATTRIBUTION_RE.match(line) or _ORIGINAL_MSG_RE.match(line):
            cut = i
            break
        if (_HEADER_FIRST_RE.match(line)
                and any(_HEADER_FOLLOW_RE.match(l) for l in lines[i + 1:i + 4])):
            cut = i
            break
        if (line.lstrip().startswith('>') and i + 1 < len(lines)
                and lines[i + 1].lstrip().startswith('>')):
            cut = i
            break
    if cut is None or cut == 0:
        return body
    trimmed = '\n'.join(lines[:cut]).rstrip()
    return trimmed if trimmed.strip() else body


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


def mark_archived(store: dict, thread_id: str, message_count: int, dest_rel_path: str,
                  subject: str = '') -> None:
    """El `subject` és purament informatiu: fa el JSON autoexplicatiu quan
    s'inspecciona (per depurar o per forçar un re-arxivat, cal poder saber
    quin fil és cada thread_id sense anar a Gmail)."""
    store[thread_id] = {
        'message_count': message_count,
        'archived_at': datetime.now(timezone.utc).isoformat(),
        'dest_path': dest_rel_path,
    }
    if subject:
        store[thread_id]['subject'] = subject


@dataclass
class LabelSyncResult:
    """Resum d'una sincronització d'etiquetes vault → Gmail."""
    created: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (etiqueta, error)
    orphan: list[str] = field(default_factory=list)              # a Gmail, no al vault
    closed: list[str] = field(default_factory=list)              # sèrie tancada


@dataclass
class LabelMigrationPlan:
    """Pla de migració d'etiquetes Gmail del format antic (camí complet, e.g.
    `Seguiment/CRA`) al nou (nom de fulla, e.g. `CRA`).

    - `renames`: (label_id, nom_antic, nom_nou) a renombrar (conserva fils).
    - `skipped_target_exists`: noms antics que NO es renombren perquè ja
      existeix una etiqueta plana amb el nom de fulla (cal fusionar a mà).
    - `skipped_collision`: noms antics que comparteixen nom de fulla entre
      ells (no es pot decidir quin guanya; resolució manual).
    - `not_in_vault`: etiquetes amb '/' la fulla de les quals no correspon a
      cap sèrie actual del vault (es deixen tal qual; informatiu).
    """
    renames: list[tuple[str, str, str]] = field(default_factory=list)
    skipped_target_exists: list[str] = field(default_factory=list)
    skipped_collision: list[str] = field(default_factory=list)
    not_in_vault: list[str] = field(default_factory=list)


def plan_label_migration(existing_labels: list[dict], discovery: VaultDiscovery) -> LabelMigrationPlan:
    """Calcula el pla per migrar etiquetes Gmail antigues (amb '/') a nom de fulla.

    Args:
        existing_labels: [{'id', 'name'}, ...] tal com retorna
            `GmailFetcher.list_user_labels()`.
        discovery: sèries del vault (les etiquetes esperades són els noms de
            fulla d'`active` i `closed_by_active_label`).

    Una etiqueta antiga `A/B/C` es renombra a `C` només si `C` és una sèrie
    esperada del vault, no hi ha ja una etiqueta plana `C`, i cap altra
    etiqueta antiga mapeja també a `C`.
    """
    expected = set(discovery.active) | set(discovery.closed_by_active_label)
    existing_names = {l['name'] for l in existing_labels}
    plan = LabelMigrationPlan()

    by_leaf: dict[str, list[tuple[str, str]]] = {}
    for l in existing_labels:
        name = l['name']
        if '/' not in name:
            continue  # ja és forma de fulla
        leaf = name.rsplit('/', 1)[-1]
        if leaf not in expected:
            plan.not_in_vault.append(name)
            continue
        by_leaf.setdefault(leaf, []).append((l['id'], name))

    for leaf, items in sorted(by_leaf.items()):
        if len(items) > 1:
            plan.skipped_collision.extend(sorted(n for _, n in items))
            continue
        label_id, old_name = items[0]
        if leaf in existing_names:
            plan.skipped_target_exists.append(old_name)
            continue
        plan.renames.append((label_id, old_name, leaf))

    return plan


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
