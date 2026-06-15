"""Fase 2 del processat de reunions de seguiment: consolidació.

La fase 1 (Wizard Processar) genera només 'Ordre del dia propera reunió.md' i
deixa la nota en estat '+' (pendent de consolidar). L'usuari valida/corregeix
l'Ordre del dia a Obsidian. La consolidació pren aquest Ordre del dia ja
validat, en treu els resums (via parse_ordre_del_dia) i els propaga a:

  - Temes oberts.md  (bullets datats sota cada tema tractat)
  - <Any> <Sèrie>.md (bloc del resum al fitxer anual)

i marca la nota com a processada ('*').

Lògica pura (sense Qt): rep un ObsidianWriter ja construït.
"""
from pathlib import Path

from meeting_analyzer import parse_ordre_del_dia, StateFileUpdater

ORDRE_FILENAME = 'Ordre del dia propera reunió.md'
TEMES_FILENAME = 'Temes oberts.md'


def consolidate_pending_note(obsidian, note: dict) -> dict:
    """Consolida una nota pendent ('+').

    `note` és un dict {'path', 'date', 'title'} tal com el retorna
    ObsidianWriter.find_pending_consolidation_notes().

    Ordre d'operacions (igual que la fase 1 original): primer Temes oberts +
    fitxer anual, després marcar processada — així si una escriptura falla, la
    nota queda '+' i es pot reintentar. Reintentar després d'una fallada a mig
    camí pot duplicar bullets datats; en aquest cas cal revisar manualment.

    Retorna {'note_path', 'year_written', 'block'}.
    Llança FileNotFoundError si falta l'Ordre del dia o el Temes oberts.
    """
    note_path = Path(note['path'])
    series_dir = note_path.parent.parent
    ordre_path = series_dir / ORDRE_FILENAME
    temes_path = series_dir / TEMES_FILENAME

    if not ordre_path.exists():
        raise FileNotFoundError(f"Falta {ORDRE_FILENAME} a {series_dir.name}")
    if not temes_path.exists():
        raise FileNotFoundError(f"Falta {TEMES_FILENAME} a {series_dir.name}")

    result = parse_ordre_del_dia(ordre_path.read_text(encoding='utf-8'))

    meeting_block = StateFileUpdater().update(temes_path, result, note['date'])
    year_written = False
    if meeting_block:
        attendees = obsidian.read_attendees_string(note_path)
        obsidian.append_to_year_note(
            note_path, note['date'], note['title'], attendees, meeting_block
        )
        year_written = True

    new_path = obsidian.mark_as_processed(note_path)
    return {'note_path': new_path, 'year_written': year_written, 'block': meeting_block}
