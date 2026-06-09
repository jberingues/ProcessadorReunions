"""Embolcall del CLI `plaud` per gestionar gravacions de Plaud.

El CLI s'instal·la amb: npm install -g @plaud-ai/cli
i requereix `plaud login` previ.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional


# Quan el GUI s'inicia des del Finder/Dock/launchd el PATH heretat no inclou
# els bin d'usuari (`~/.npm-global/bin`, Homebrew, etc.), i `subprocess.run`
# falla amb FileNotFoundError. Ampliem la cerca amb les ubicacions habituals.
_EXTRA_BIN_PATHS = [
    os.path.expanduser("~/.npm-global/bin"),
    os.path.expanduser("~/.local/bin"),
    "/opt/homebrew/bin",
    "/usr/local/bin",
]


def _resolve_executable(name: str) -> Optional[str]:
    """Retorna la ruta absoluta del binari, o None si no es troba enlloc."""
    found = shutil.which(name)
    if found:
        return found
    augmented = os.pathsep.join([*_EXTRA_BIN_PATHS, os.environ.get("PATH", "")])
    return shutil.which(name, path=augmented)


def _augmented_path_env() -> dict:
    """Còpia de os.environ amb PATH enriquit. El binari `plaud` és un script
    Node (shebang `#!/usr/bin/env node`) i necessita `node` accessible al
    subprocés. Quan el GUI s'inicia des del Finder/launchd, ni `plaud` ni
    `node` són al PATH heretat."""
    env = os.environ.copy()
    current = env.get("PATH", "")
    extras = [p for p in _EXTRA_BIN_PATHS if p not in current.split(os.pathsep)]
    if extras:
        env["PATH"] = os.pathsep.join([*extras, current]) if current else os.pathsep.join(extras)
    return env


# El CLI de Plaud emet timestamps sense indicador de zona horària, però en UTC.
# Verificat 2026-05-18: gravació 06:19:04 (CEST: 08:19) lligava amb reunió
# convocada a 08:15. Si Plaud canviés algun dia a hora local del dispositiu,
# només cal modificar aquesta constant.
PLAUD_TIMEZONE = timezone.utc


class PlaudCLINotInstalled(Exception):
    """El binari `plaud` no s'ha trobat al PATH."""


class PlaudNotAuthenticated(Exception):
    """Cal executar `plaud login` abans."""


class PlaudError(Exception):
    """Error genèric del CLI."""


@dataclass
class PlaudRecording:
    file_id: str
    name: str
    date: str  # YYYY-MM-DD segons el CLI (data local del dispositiu)
    duration_seconds: int
    start_at: Optional[datetime] = None  # tz-aware UTC, populat sota demanda


# Fila de `plaud today` / `plaud recent`:
#   "  <hex_id>  <name>  YYYY-MM-DD  <duration>"
# El name pot contenir espais simples però els separadors són 2 espais.
_LIST_ROW = re.compile(
    r"^  ([a-f0-9]+)  (.+)  (\d{4}-\d{2}-\d{2})  (\S+)\s*$"
)

# Fila de `plaud file`: "  key:   value"
_KEY_VAL = re.compile(r"^\s+(\w+):\s+(.+?)\s*$")

# Format duració: "22m19s", "1h23m45s", "45s"
_DURATION = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$")


def parse_duration(s: str) -> int:
    """Converteix '22m19s' / '1h23m45s' / '45s' a segons."""
    s = s.strip()
    if not s:
        raise ValueError("Duració buida")
    m = _DURATION.match(s)
    if not m or not any(m.groups()):
        raise ValueError(f"Duració no parsejable: {s!r}")
    h, mn, sec = m.groups()
    return int(h or 0) * 3600 + int(mn or 0) * 60 + int(sec or 0)


def parse_list_output(output: str) -> list[PlaudRecording]:
    """Parseja la sortida de `plaud today` / `plaud recent` / `plaud files`."""
    recordings: list[PlaudRecording] = []
    for line in output.splitlines():
        m = _LIST_ROW.match(line)
        if not m:
            continue
        file_id, name, day, dur = m.groups()
        try:
            duration_s = parse_duration(dur)
        except ValueError:
            continue
        recordings.append(PlaudRecording(
            file_id=file_id,
            name=name,
            date=day,
            duration_seconds=duration_s,
        ))
    return recordings


def parse_file_output(output: str) -> dict[str, str]:
    """Parseja `plaud file <id>` com a dict clau-valor."""
    data: dict[str, str] = {}
    for line in output.splitlines():
        m = _KEY_VAL.match(line)
        if m:
            data[m.group(1)] = m.group(2)
    return data


def strip_transcript_header(output: str) -> str:
    """Elimina les línies "- Fetching..." i "Transcript: <títol>" del CLI."""
    lines = output.splitlines()
    body_start = 0
    for i, line in enumerate(lines):
        if line.startswith("Transcript:"):
            body_start = i + 1
            break
    while body_start < len(lines) and not lines[body_start].strip():
        body_start += 1
    if body_start >= len(lines):
        return ""
    return "\n".join(lines[body_start:]).rstrip() + "\n"


class PlaudClient:
    def __init__(self, executable: str = "plaud", timeout: int = 30):
        # Resol la ruta una sola vegada al constructor. Si no es troba, deixem
        # el nom curt i el _run llançarà PlaudCLINotInstalled a la primera crida.
        self.executable = _resolve_executable(executable) or executable
        self.timeout = timeout

    def _run(self, args: list[str], timeout: Optional[int] = None) -> str:
        try:
            result = subprocess.run(
                [self.executable, *args],
                capture_output=True,
                text=True,
                timeout=timeout or self.timeout,
                env=_augmented_path_env(),
            )
        except FileNotFoundError as e:
            raise PlaudCLINotInstalled(
                f"No s'ha trobat el binari '{self.executable}'. "
                "Instal·la-ho amb: npm install -g @plaud-ai/cli"
            ) from e
        except subprocess.TimeoutExpired as e:
            raise PlaudError(f"Timeout executant 'plaud {' '.join(args)}'") from e

        if result.returncode != 0:
            msg = (result.stderr or "").strip() or (result.stdout or "").strip()
            low = msg.lower()
            if any(k in low for k in ("login", "authenticat", "unauthor", "no token")):
                raise PlaudNotAuthenticated(msg)
            raise PlaudError(msg or f"plaud {args[0]} ha fallat amb codi {result.returncode}")
        return result.stdout

    def is_authenticated(self) -> bool:
        try:
            self._run(["me"], timeout=10)
            return True
        except (PlaudNotAuthenticated, PlaudCLINotInstalled, PlaudError):
            return False

    def list_for_date(self, target_date: date, progress_cb=None) -> list[PlaudRecording]:
        """Llista les gravacions el `start_at` (hora local) de les quals == target_date.

        **Important**: la data que mostra el llistat del CLI (`plaud today` /
        `plaud recent`) és la de **pujada al cloud (`created_at`)**, NO la de
        gravació. Una gravació feta avui però sincronitzada demà apareix sota
        la data de demà. Per això resolem `start_at` de cada candidat i filtrem
        per la seva data **local** (`start_at` és UTC → `.astimezone()`).

        La finestra es consulta amb un dia extra de marge (`days_ago + 2`)
        perquè una gravació feta a `target_date` sempre té `created_at` ≥
        `target_date`, i el marge cobreix el cas de la franja de mitjanit.

        `progress_cb(fets, total)` s'invoca per cada candidat resolt (la part
        lenta), perquè el worker pugui mostrar el progrés sense un doble fetch:
        `start_at` queda poblat als objectes retornats.
        """
        today = datetime.now().date()
        days_ago = (today - target_date).days
        if days_ago < 0 or days_ago > 365:
            return []
        if days_ago == 0:
            out = self._run(["today"])
        else:
            out = self._run(["recent", "-d", str(days_ago + 2)])
        candidates = parse_list_output(out)
        total = len(candidates)
        result: list[PlaudRecording] = []
        for i, rec in enumerate(candidates, start=1):
            if rec.start_at is None:
                rec.start_at = self.get_start_at_utc(rec.file_id)
            if progress_cb is not None:
                progress_cb(i, total)
            if rec.start_at is not None:
                matches = rec.start_at.astimezone().date() == target_date
            else:
                # Sense start_at no podem saber la data real: fem servir la del
                # CLI com a fallback (comportament antic) per no amagar res.
                matches = rec.date == target_date.isoformat()
            if matches:
                result.append(rec)
        return result

    def get_file_metadata(self, file_id: str) -> dict[str, str]:
        return parse_file_output(self._run(["file", file_id]))

    def get_start_at_utc(self, file_id: str) -> Optional[datetime]:
        """Retorna `start_at` com a datetime tz-aware UTC, o None si no hi és."""
        meta = self.get_file_metadata(file_id)
        s = meta.get("start_at")
        if not s:
            return None
        return datetime.fromisoformat(s).replace(tzinfo=PLAUD_TIMEZONE)

    def get_transcript(self, file_id: str) -> str:
        return strip_transcript_header(self._run(["transcript", file_id]))
