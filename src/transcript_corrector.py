import os
import re
import time
from pathlib import Path
from crewai import Agent, Task, Crew, LLM
from json_repair import repair_json


class TranscriptCorrector:
    def __init__(self, vocab: dict, semantic_memory_path: Path = None, model: str = None,
                 threshold_auto: float = 0.85):
        self.vocab = vocab
        self.semantic_memory_path = Path(semantic_memory_path) if semantic_memory_path else None
        self.llm = LLM(model=model or os.getenv('LLM_MODELH'), drop_params=True)
        self.threshold_auto = threshold_auto

    def detect(self, transcript: str, reference_transcript: str = None, semantic_context=None) -> tuple[str, list[dict]]:
        """Aplica correccions memoritzades i detecta nous errors amb LLM.

        Returns:
            (transcripció amb memoritzades aplicades, llista de correccions noves)
            Cada correcció: {"original", "correccio", "motiu", "frase"}
        """
        # 1. Aplicar correccions memoritzades automàticament
        # Globals (Canvis-Memoritzats.md) → s'apliquen a totes les transcripcions
        global_memorized = self._load_global_memorized()
        if global_memorized:
            for original, correccio in global_memorized.items():
                if original in transcript:
                    transcript = transcript.replace(original, correccio)

        # Locals (semantic_memory.json) → s'apliquen només a aquesta sèrie
        local_memorized = self._load_local_memorized()
        if local_memorized:
            for original, correccio in local_memorized.items():
                if original in transcript:
                    transcript = transcript.replace(original, correccio)

        # 2. LLM detecta nous errors
        vocab_text = self._format_vocab()

        semantic_section = ''
        if semantic_context and (semantic_context.relevant_projects or semantic_context.topic_context or semantic_context.likely_terms):
            terms_line = f"\nTermes tècnics confirmats per a aquesta sèrie: {', '.join(semantic_context.likely_terms)}" if semantic_context.likely_terms else ''
            semantic_section = f"""
MEMÒRIA SEMÀNTICA D'AQUESTA SÈRIE DE REUNIONS:
Projectes habituals: {', '.join(semantic_context.relevant_projects) or 'cap'}
Temes recurrents: {', '.join(semantic_context.topic_context) or 'cap'}{terms_line}
"""

        ref_section = ''
        if reference_transcript:
            ref_section = f"""
EXEMPLE DE TRANSCRIPCIÓ JA CORREGIDA (reunió anterior de la mateixa sèrie, usa-la com a referència de noms, termes i estil):
{reference_transcript}
"""

        agent = Agent(
            role="Corrector de transcripcions",
            goal="Detectar paraules mal transcrites usant el vocabulari de l'empresa",
            backstory="Expert en correcció de transcripcions automàtiques en català per JCM Technologies.",
            llm=self.llm,
            verbose=False
        )

        task = Task(
            description=f"""
Ets un corrector especialitzat en transcripcions automàtiques per veu (ASR) de reunions tècniques en català.

El sistema ASR comet errors fonètics: transcriu paraules comunes del català o castellà quan el parlant deia un terme tècnic, nom de producte o nom de persona del vocabulari de l'empresa. Pot passar que "HONOADOOR" es transcrigui com "congeladors", "HONOA" com "onea", "KAIMAI" com "queimei", o noms de persona com paraules comunes.

TASCA: Revisa la transcripció i detecta TOTES les paraules o frases que probablement siguin errors fonètics d'algun terme del vocabulari. No et limitis a errors ortogràfics: busca paraules que no tinguin sentit en el context tècnic i que sonin semblant a algun terme del vocabulari.

VOCABULARI DE L'EMPRESA:
{vocab_text}
{semantic_section}
{ref_section}TRANSCRIPCIÓ:
{transcript}

Per cada possible error, indica:
- "original": el text erroni tal com apareix a la transcripció
- "correccio": el terme correcte del vocabulari
- "motiu": breu explicació de la similitud fonètica o per què no té sentit en context
- "frase": la frase sencera de la transcripció on apareix l'error (per donar context)
- "confiança": valor entre 0.0 i 1.0 que reflecteix la certesa que és un error. Guia:
    * 0.9–1.0: terme exactament al vocabulari, similitud fonètica clara i inequívoca, sense ambigüitat semàntica possible
    * 0.7–0.89: probable error fonètic però podria ser una paraula legítima en algun context
    * 0.5–0.69: possible error però ambigu; el mot té sentit per si sol en català/castellà
    * < 0.5: especulatiu; no usar

IMPORTANT: No proposis cap correcció si el terme correcte del vocabulari ja apareix literalment a la transcripció. Per exemple, si "OTC" ja és al text, no cal proposar canviar "TC" per "OTC".
IMPORTANT: L'"original" ha de ser sempre una paraula o frase sencera, mai una part d'una paraula. Per exemple, si veus "acabo", no proposis corregir "cabo" perquè és una subcadena d'una paraula més llarga.

Retorna ÚNICAMENT un array JSON (sense cap text addicional):
[{{"original": "...", "correccio": "...", "motiu": "...", "frase": "...", "confiança": 0.95}}]
Si no hi ha errors, retorna [].
            """,
            expected_output="Array JSON de correccions amb camp 'confiança'",
            agent=agent
        )

        if os.getenv('GENERA_LOG', '').upper() == 'TRUE':
            from datetime import datetime
            separator = '-' * 90
            log_entry = (
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"{separator}\n"
                f"Vocabulari:\n{vocab_text}\n\n"
                f"Semàntic:\n{semantic_section}\n\n"
                f"Referència:\n{ref_section}\n"
                f"{separator}\n"
            )
            log_path = Path(__file__).resolve().parent.parent / 'data' / 'log-correccio-transcripcio.txt'
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(log_entry)

        crew = Crew(agents=[agent], tasks=[task], verbose=False)
        result = self._kickoff_with_retry(crew)

        raw = result.raw if hasattr(result, 'raw') else str(result)
        corrections = repair_json(raw, return_objects=True) or []
        if not isinstance(corrections, list):
            corrections = []

        # Filtrar correccions on l'original és sempre subcadena d'una paraula més llarga
        def is_whole_word(word, text):
            return bool(re.search(r'(?<!\w)' + re.escape(word) + r'(?!\w)', text))

        corrections = [
            c for c in corrections
            if isinstance(c, dict) and 'original' in c and is_whole_word(c['original'], transcript)
        ]

        return transcript, corrections

    def _kickoff_with_retry(self, crew: Crew, max_retries: int = 4):
        """Executa crew.kickoff() amb reintents exponencials en cas de 429."""
        delay = 30
        for attempt in range(max_retries):
            try:
                return crew.kickoff()
            except Exception as e:
                is_rate_limit = '429' in str(e) or 'Too Many Requests' in str(e) or 'rate_limit' in str(e).lower()
                if is_rate_limit and attempt < max_retries - 1:
                    print(f"[TranscriptCorrector] 429 rate limit, reintent {attempt + 1}/{max_retries - 1} en {delay}s...")
                    time.sleep(delay)
                    delay = min(delay * 2, 120)
                else:
                    raise

    def apply(self, transcript: str, corrections: list[dict]) -> str:
        """Aplica les correccions aprovades a la transcripció."""
        for c in corrections:
            transcript = re.sub(
                r'(?<!\w)' + re.escape(c['original']) + r'(?!\w)',
                c['correccio'],
                transcript
            )
        return transcript

    def _load_global_memorized(self) -> dict:
        if not self.semantic_memory_path:
            return {}
        current = self.semantic_memory_path.parent
        for _ in range(6):
            candidate = current / 'zConfig' / 'Canvis-Memoritzats.md'
            if candidate.exists():
                break
            current = current.parent
        else:
            return {}
        result = {}
        for line in candidate.read_text(encoding='utf-8').splitlines():
            m = re.match(r'^-\s+(.+?)\s+→\s+(.+)$', line)
            if m:
                result[m.group(1)] = m.group(2)
        return result

    def _load_local_memorized(self) -> dict:
        if not self.semantic_memory_path or not self.semantic_memory_path.exists():
            return {}
        try:
            import json
            data = json.loads(self.semantic_memory_path.read_text(encoding='utf-8'))
            return data.get('aliases', {})
        except Exception:
            return {}

    def _format_vocab(self) -> str:
        lines = []
        for seccio, paraules in self.vocab.items():
            if seccio == 'Configuració':
                continue
            lines.append(f"{seccio}: {', '.join(paraules)}")
        return '\n'.join(lines)
