"""Filtres fonètics i fuzzy per a la correcció de transcripcions.

Dues funcions principals:
- `find_fuzzy_candidates`: detecta possibles errors fonètics comparant paraules
  del transcript amb el vocabulari de l'empresa (pre-pass abans del LLM).
- `is_likely_phonetic`: indica si una proposta del LLM sembla un error fonètic
  o més aviat una substitució semàntica (post-pass per descartar sinònims).

S'usa Levenshtein normalitzat (case-insensitive i sense accents) com a mesura
de similitud — prou robust per a errors d'ASR en català sense afegir dependències.
"""
import re
import unicodedata


def _normalize(s: str) -> str:
    """Minúscules + sense accents. Permet comparar acrònims i variants accentuades."""
    decomposed = unicodedata.normalize('NFD', s.lower())
    return ''.join(c for c in decomposed if unicodedata.category(c) != 'Mn')


def levenshtein(a: str, b: str) -> int:
    """Distància d'edició entre dues cadenes."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(
                curr[j - 1] + 1,        # inserció
                prev[j] + 1,            # esborrat
                prev[j - 1] + cost      # substitució
            )
        prev = curr
    return prev[-1]


def normalized_distance(a: str, b: str) -> float:
    """Distància normalitzada entre 0 (idèntics) i 1 (totalment diferents).
    Aplica normalització (minúscules + sense accents) per ser robust amb acrònims."""
    na, nb = _normalize(a), _normalize(b)
    if not na and not nb:
        return 0.0
    return levenshtein(na, nb) / max(len(na), len(nb))


def similarity(a: str, b: str) -> float:
    """Similitud entre 0 i 1 (invers de la distància normalitzada)."""
    return 1.0 - normalized_distance(a, b)


def is_likely_phonetic(original: str, correccio: str, max_distance: float = 0.75) -> bool:
    """Retorna True si `original` i `correccio` són prou similars per ser un error
    fonètic creïble. Si retorna False, probablement el LLM està fent una
    substitució semàntica (sinònim) que no volem.

    El llindar 0.75 és permissiu: deixa passar errors d'ASR severs (queimei→KAIMAI
    distància 0.57, congeladors→HONOADOOR ~0.64) i bloca sinònims sense relació
    fonètica clara (cotxe→automòbil, casa→habitatge).

    Cas límit: parelles com gestor→administrador (~0.69) o ordinador→computadora
    passen el filtre perquè comparteixen lletres. El LLM hauria de no proposar-les
    inicialment perquè el seu prompt demana errors fonètics, no semàntics.
    """
    if not original or not correccio:
        return False
    # Correccions multi-paraula: relaxem el filtre, no és el cas típic
    if ' ' in original.strip() or ' ' in correccio.strip():
        return True
    return normalized_distance(original, correccio) <= max_distance


def find_fuzzy_candidates(transcript: str, vocab_terms: list[str],
                          min_similarity: float = 0.6,
                          min_word_length: int = 4) -> list[dict]:
    """Pre-pass: per a cada terme del vocabulari, busca paraules del transcript
    fonèticament similars que NO siguin literalment el terme.

    Args:
        transcript: text complet a analitzar
        vocab_terms: llista de termes del vocabulari (una paraula cadascun)
        min_similarity: llindar mínim de similitud per considerar candidata
        min_word_length: ignora paraules massa curtes (massa coincidències accidentals)

    Returns:
        Llista de candidates amb el mateix format que les correccions del LLM:
        {"original", "correccio", "motiu", "frase", "confiança"}

    No reemplaça el LLM: les candidates s'envien al LLM com a context per
    validació, o es fusionen amb les seves correccions descartant duplicats.
    """
    if not transcript or not vocab_terms:
        return []

    # Extreu paraules del transcript (preserva forma original per al reemplaçament)
    word_positions = {}
    for match in re.finditer(r'\b\w+\b', transcript):
        word = match.group()
        if len(word) < min_word_length:
            continue
        if word not in word_positions:
            word_positions[word] = match.start()

    # Termes del vocabulari ja presents literalment: no calen candidates
    transcript_words_norm = {_normalize(w) for w in word_positions}

    candidates = []
    seen_originals = set()  # evita proposar el mateix `original` dos cops

    for term in vocab_terms:
        term = term.strip()
        if not term or ' ' in term or len(term) < min_word_length:
            continue
        if _normalize(term) in transcript_words_norm:
            continue  # el terme ja és al text, no cal candidata

        # Busca la paraula del transcript més similar a aquest terme
        best_word = None
        best_sim = min_similarity
        for word in word_positions:
            # Evita comparar el terme amb si mateix (variants de cas)
            if _normalize(word) == _normalize(term):
                continue
            sim = similarity(word, term)
            if sim > best_sim:
                best_sim = sim
                best_word = word

        if best_word and best_word not in seen_originals:
            seen_originals.add(best_word)
            frase = _extract_phrase(transcript, word_positions[best_word])
            candidates.append({
                'original': best_word,
                'correccio': term,
                'motiu': f'similitud fonètica amb terme del vocabulari (sim={best_sim:.2f})',
                'frase': frase,
                'confiança': round(best_sim, 2),
                'source': 'fuzzy',  # marca l'origen per al merge
            })

    return candidates


def _extract_phrase(text: str, position: int, context_chars: int = 60) -> str:
    """Extreu una frase de context al voltant d'una posició del text."""
    start = max(0, position - context_chars)
    end = min(len(text), position + context_chars)
    return text[start:end].replace('\n', ' ').strip()
