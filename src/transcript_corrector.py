import os
import re
from pathlib import Path
from crewai import Agent, Task, Crew, LLM
from json_repair import repair_json


class TranscriptCorrector:
    def __init__(self, vocab: dict, memorized_path: Path = None, model: str = None,
                 threshold_auto: float = 0.85):
        self.vocab = vocab
        self.memorized_path = Path(memorized_path) if memorized_path else None
        self.llm = LLM(model=model or os.getenv('LLM_MODELH'), drop_params=True)
        self.threshold_auto = threshold_auto

    def detect(self, transcript: str, reference_transcript: str = None, semantic_context=None) -> tuple[str, list[dict]]:
        """Aplica correccions memoritzades i detecta nous errors amb LLM.

        Returns:
            (transcripció amb memoritzades aplicades, llista de correccions noves)
            Cada correcció: {"original", "correccio", "motiu", "frase"}
        """
        # 1. Aplicar correccions memoritzades automàticament
        memorized = self._load_memorized()
        if memorized:
            for original, correccio in memorized.items():
                if original in transcript:
                    transcript = transcript.replace(original, correccio)

        # 2. LLM detecta nous errors
        vocab_text = self._format_vocab()

        semantic_section = ''
        if semantic_context and (semantic_context.aliases or semantic_context.topic_context):
            alias_lines = '\n'.join(
                f'- "{w}" s\'ha de corregir a "{c}"'
                for w, c in semantic_context.aliases.items()
            )
            semantic_section = f"""
MEMÒRIA SEMÀNTICA D'AQUESTA SÈRIE DE REUNIONS:
Projectes habituals: {', '.join(semantic_context.relevant_projects) or 'cap'}
Temes recurrents: {', '.join(semantic_context.topic_context) or 'cap'}

CORRECCIONS APRESES (errors fonètics ja confirmats per a aquesta sèrie):
{alias_lines}
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

        crew = Crew(agents=[agent], tasks=[task], verbose=False)
        result = crew.kickoff()

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

    def apply(self, transcript: str, corrections: list[dict]) -> str:
        """Aplica les correccions aprovades a la transcripció."""
        for c in corrections:
            transcript = re.sub(
                r'(?<!\w)' + re.escape(c['original']) + r'(?!\w)',
                c['correccio'],
                transcript
            )
        return transcript

    def save_memorized(self, original: str, correccio: str):
        """Desa una correcció al fitxer de correccions memoritzades."""
        self._save_memorized(original, correccio)

    def _load_memorized(self) -> dict:
        if not self.memorized_path or not self.memorized_path.exists():
            return {}
        corrections = {}
        for line in self.memorized_path.read_text(encoding='utf-8').splitlines():
            if line.startswith('- ') and ' → ' in line:
                parts = line[2:].split(' → ', 1)
                if len(parts) == 2:
                    corrections[parts[0].strip()] = parts[1].strip()
        return corrections

    def _save_memorized(self, original: str, correccio: str):
        if not self.memorized_path:
            return
        if not self.memorized_path.exists():
            self.memorized_path.parent.mkdir(parents=True, exist_ok=True)
            self.memorized_path.write_text(
                "---\ntype: configuracio\n---\n\n# Canvis Memoritzats\n\n",
                encoding='utf-8'
            )
        content = self.memorized_path.read_text(encoding='utf-8')
        entry = f"- {original} → {correccio}\n"
        if entry.strip() not in content:
            self.memorized_path.write_text(content + entry, encoding='utf-8')

    def _format_vocab(self) -> str:
        lines = []
        for seccio, paraules in self.vocab.items():
            lines.append(f"{seccio}: {', '.join(paraules)}")
        return '\n'.join(lines)
