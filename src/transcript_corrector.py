import os
import re
import time
from pathlib import Path
from crewai import Agent, Task, Crew, LLM
from json_repair import repair_json

from phonetic_filter import is_likely_phonetic


class TranscriptCorrector:
    def __init__(self, vocab: dict, semantic_memory_path: Path = None, model: str = None,
                 threshold_auto: float = 0.85):
        self.vocab = vocab
        self.semantic_memory_path = Path(semantic_memory_path) if semantic_memory_path else None
        self.llm = LLM(model=model or os.getenv('LLM_MODELH'), drop_params=True)
        self.threshold_auto = threshold_auto

    def detect(self, transcript: str, reference_summary: str = None, semantic_context=None) -> tuple[str, list[dict]]:
        """Aplica correccions memoritzades i detecta nous errors amb LLM.

        Returns:
            (transcripció amb memoritzades aplicades, llista de correccions noves)
            Cada correcció: {"original", "correccio", "motiu", "frase"}
        """
        # 1. Aplicar correccions memoritzades automàticament
        # Globals (Canvis-Memoritzats.md) → s'apliquen a totes les transcripcions
        for original, correccio in self._load_global_memorized().items():
            transcript = self._replace_whole_word(transcript, original, correccio)

        # Locals (semantic_memory.json) → s'apliquen només a aquesta sèrie
        for original, correccio in self._load_local_memorized().items():
            transcript = self._replace_whole_word(transcript, original, correccio)

        # (El pre-pass fuzzy es va eliminar: afegia massa falsos positius —
        # paraules catalanes comunes amb similitud >0.7 amb cognoms/termes,
        # tipus `cosa→Coma`, `pots→Cots`. El LLM ja veu el vocabulari sencer.
        # `phonetic_filter.find_fuzzy_candidates` es conserva per experiments.)

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
        if reference_summary:
            ref_section = f"""
RESUMS VALIDATS DE REUNIONS ANTERIORS DE LA MATEIXA SÈRIE (redactats i revisats per l'usuari; són una referència FIABLE de com s'escriuen correctament els noms propis, productes i termes tècnics d'aquesta sèrie):
{reference_summary}
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

IMPORTANT: No proposis cap correcció si l'original ja és una entrada del vocabulari. Per exemple, si veus "Riera" al text i "Riera" és al vocabulari, NO proposis canviar-lo per "Griera" encara que també hi sigui. Cada paraula del text que ja coincideix exactament amb un terme del vocabulari és correcta i no s'ha de tocar.
IMPORTANT: No proposis cap correcció si el terme correcte del vocabulari ja apareix literalment a la transcripció. Per exemple, si "OTC" ja és al text, no cal proposar canviar "TC" per "OTC".
IMPORTANT: L'"original" ha de ser sempre una paraula o frase sencera, mai una part d'una paraula. Per exemple, si veus "acabo", no proposis corregir "cabo" perquè és una subcadena d'una paraula més llarga.

REGLA CRÍTICA: NO proposis substituir una paraula catalana o castellana legítima per un terme del vocabulari només perquè sonen similar. Si l'original és una paraula que existeix al diccionari català/castellà i té sentit a la frase, NO la canviïs encara que un terme del vocabulari hi sigui fonèticament proper.

EXEMPLES DEL QUE NO HAS DE PROPOSAR (errors típics a evitar):
- "És molt a la meva zona" → NO proposis "meva → Medva". 'meva' és pronom possessiu català.
- "Deu haver passat alguna cosa" → NO proposis "cosa → Coma". 'cosa' és substantiu català.
- "abans he parlat amb ell" → NO proposis "parlat → Panelat". 'parlat' és participi de parlar.
- "Al final del sistema" → NO proposis "final → Fina". 'final' és substantiu/adjectiu català.
- "m'he equivocat en la vida" → NO proposis "vida → Vila". 'vida' és substantiu català.
- "no seria a través de comunicacions" → NO proposis "seria → Serra". 'seria' és condicional de ser.
- "ho miraré igualment" → NO proposis "miraré → Mifare". 'miraré' és futur de mirar.
- "a millor podem accedir" → NO proposis "millor → Miller". 'millor' és adjectiu català.
- "tu pots accedir" → NO proposis "pots → Cots". 'pots' és present de poder.
- "oscil·lador intern" → NO proposis "intern → Integra". 'intern' és adjectiu català.
- "tinc sola pebre" → NO proposis "sola → Sala". 'sola' és adjectiu femení.

EXEMPLES DEL QUE SÍ HAS DE PROPOSAR (errors fonètics clars):
- "el producte queimei" → SÍ: "queimei → KAIMAI". 'queimei' no és català ni castellà.
- "mirem l'onea" → SÍ: "onea → HONOA". 'onea' no té sentit en cap llengua.
- "el sistema bidpfox" → SÍ: "bidpfox → BIPROX". 'bidpfox' no és una paraula real.

Regla pràctica: ABANS de proposar una correcció, pregunta't "l'original és una paraula que un diccionari de català o castellà acceptaria?". Si la resposta és sí, NO la proposis.

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
            if isinstance(c, dict) and 'original' in c
            and 'correccio' in c
            and is_whole_word(c['original'], transcript)
        ]

        # Filtre de confiança: només propostes amb confiança molt alta (≥0.85).
        # Diversos rounds amb llindar 0.5 i 0.7 han mostrat que el LLM segueix
        # al·lucinant substitucions falses (meva→Medva, cosa→Coma, Riera→Griera)
        # amb confiança 0.7-0.85. Trade-off: perdem errors borderline, però
        # evitem que el text corregit tingui pitjor qualitat que l'original.
        corrections = [c for c in corrections if c.get('confiança', 1.0) >= 0.85]

        # Filtre fonètic: descarta correccions massa diferents (probablement
        # substitucions semàntiques que el LLM ha proposat per compte propi).
        corrections = [c for c in corrections if is_likely_phonetic(c['original'], c['correccio'])]

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
            transcript = self._replace_whole_word(transcript, c['original'], c['correccio'])
        return transcript

    @staticmethod
    def _replace_whole_word(text: str, original: str, correccio: str) -> str:
        """Reemplaça `original` a `text` només quan és paraula sencera.
        Evita coincidències dins de paraules més llargues (e.g. 'cabo' dins 'acabo')."""
        if not original:
            return text
        # lambda: re.sub interpreta el 2n argument com a template (\1, \g<...>);
        # una correcció amb '\' corrompria el text o llançaria error.
        return re.sub(
            r'(?<!\w)' + re.escape(original) + r'(?!\w)',
            lambda _m: correccio,
            text
        )

    def _load_global_memorized(self) -> dict:
        """Aliases globals des del Vocabulari.md unificat (sublistes indentades).

        Cerca `zConfig/Vocabulari.md` pujant fins a 6 nivells de directori i
        delega el parsing a `VocabularyLoader.load_aliases()`.
        """
        if not self.semantic_memory_path:
            return {}
        from vocabulary_loader import VocabularyLoader
        current = self.semantic_memory_path.parent
        for _ in range(6):
            candidate = current / 'zConfig' / 'Vocabulari.md'
            if candidate.exists():
                return VocabularyLoader(candidate).load_aliases()
            current = current.parent
        return {}

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
