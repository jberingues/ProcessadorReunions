"""Fase 2 del processat de reunions de seguiment: consolidació.

La fase 1 (Wizard Processar) genera només l'Ordre del dia ('Ordre del dia -
<sèrie>.md') i deixa la nota en estat '+' (pendent de consolidar). L'usuari valida/corregeix
l'Ordre del dia a Obsidian. La consolidació pren aquest Ordre del dia ja
validat, en treu els resums (via parse_ordre_del_dia) i els propaga a:

  - Temes oberts.md  (bullets datats sota cada tema tractat)
  - <Any> <Sèrie>.md (bloc del resum al fitxer anual)
  - <Projecte>.md    (línia de menció a la nota principal de cada projecte
                      enllaçat a un tema; decisió 2026-10)

i marca la nota com a processada ('*').

Lògica pura (sense Qt): rep un ObsidianWriter ja construït.
"""
import logging
from pathlib import Path

from meeting_analyzer import (
    parse_ordre_del_dia, strip_pending_marker, read_ordre_kind, StateFileUpdater,
    build_project_mentions,
)
from obsidian_writer import series_name_for_file

logger = logging.getLogger(__name__)

TEMES_FILENAME = 'Temes oberts.md'


def consolidate_pending_note(obsidian, note: dict) -> dict:
    """Consolida una nota pendent ('+').

    `note` és un dict {'path', 'date', 'title'} tal com el retorna
    ObsidianWriter.find_pending_consolidation_notes().

    Ordre d'operacions (igual que la fase 1 original): primer Temes oberts +
    fitxer anual, després marcar processada — així si una escriptura falla, la
    nota queda '+' i es pot reintentar. Reintentar després d'una fallada a mig
    camí pot duplicar bullets datats; en aquest cas cal revisar manualment.

    Les mencions als projectes s'escriuen després de l'anual i NO aturen la
    consolidació si fallen (l'anual ja és escrit: reintentar el duplicaria);
    es reporten a 'mention_warnings'.

    Retorna {'note_path', 'year_written', 'block', 'mentions', 'mention_warnings'}.
    Llança FileNotFoundError si falta l'Ordre del dia o el Temes oberts.
    """
    note_path = Path(note['path'])
    series_dir = note_path.parent.parent
    ordre_path = obsidian.ordre_del_dia_path(series_dir)
    temes_path = series_dir / TEMES_FILENAME

    if not ordre_path.exists():
        raise FileNotFoundError(f"Falta {ordre_path.name} a {series_dir.name}")

    ordre_text = ordre_path.read_text(encoding='utf-8')
    kind = read_ordre_kind(ordre_text)
    result = parse_ordre_del_dia(ordre_text)

    if kind == 'resum':
        # Resum lliure (opció 'Resum'): NO toca Temes oberts; només propaga el
        # resum al fitxer anual. Per això tampoc s'exigeix que existeixi Temes
        # oberts a la sèrie.
        meeting_block = StateFileUpdater().build_year_block(result)
    else:
        if not temes_path.exists():
            raise FileNotFoundError(f"Falta {TEMES_FILENAME} a {series_dir.name}")
        meeting_block = StateFileUpdater().update(temes_path, result, note['date'])
    year_written = False
    mentions: list[str] = []
    mention_warnings: list[str] = []
    if meeting_block:
        attendees = obsidian.read_attendees_string(note_path)
        year_note = obsidian.append_to_year_note(
            note_path, note['date'], note['title'], attendees, meeting_block
        )
        year_written = True
        mentions, mention_warnings = _write_project_mentions(
            obsidian, result, note, series_dir, Path(year_note).stem
        )

    # Treu la marca de pendent de revisar de l'Ordre del dia (ja consolidat),
    # conservant el contingut (incloses les edicions de l'usuari).
    cleaned = strip_pending_marker(ordre_text)
    if cleaned != ordre_text:
        ordre_path.write_text(cleaned, encoding='utf-8')

    new_path = obsidian.mark_as_processed(note_path)
    return {'note_path': new_path, 'year_written': year_written, 'block': meeting_block,
            'mentions': mentions, 'mention_warnings': mention_warnings}


def _write_project_mentions(obsidian, result, note: dict, series_dir: Path,
                            year_note_stem: str) -> tuple[list[str], list[str]]:
    """Escriu les mencions de cada projecte enllaçat. Retorna (projectes
    escrits, avisos). La sèrie de la reunió s'exclou (ja és al seu anual)."""
    by_project = build_project_mentions(
        result, note['date'], series_name_for_file(series_dir.name), year_note_stem,
        f"{note['date']} - {note['title']}", exclude={series_dir.name},
    )
    written, warnings = [], []
    for project, lines in by_project.items():
        try:
            if obsidian.append_project_mentions(project, lines) is None:
                warnings.append(f"Projecte inexistent: {project}")
            else:
                written.append(project)
        except Exception as e:
            logger.exception("Error escrivint mencions a %s", project)
            warnings.append(f"{project}: {e}")
    return written, warnings
