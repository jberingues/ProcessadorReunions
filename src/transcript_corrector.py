import os
import re
from pathlib import Path
from colorama import Fore, Style
from crewai import Agent, Task, Crew, LLM
from json_repair import repair_json


class TranscriptCorrector:
    def __init__(self, vocab: dict, memorized_path: Path = None, model: str = None):
        self.vocab = vocab
        self.memorized_path = Path(memorized_path) if memorized_path else None
        self.llm = LLM(model=model or os.getenv('LLM_MODELH'), drop_params=True)

    def correct(self, transcript: str, reference_transcript: str = None) -> str:
        # 1. Aplicar correccions memoritzades automàticament
        memorized = self._load_memorized()
        if memorized:
            print(f"  Aplicant {len(memorized)} correccions memoritzades...")
            for original, correccio in memorized.items():
                if original in transcript:
                    transcript = transcript.replace(original, correccio)
                    print(f"  ✓ \"{original}\" → \"{correccio}\"")
            print()

        # 2. LLM detecta nous errors
        vocab_text = self._format_vocab()
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
{ref_section}
TRANSCRIPCIÓ:
{transcript}

Per cada possible error, indica:
- "original": el text erroni tal com apareix a la transcripció
- "correccio": el terme correcte del vocabulari
- "motiu": breu explicació de la similitud fonètica o per què no té sentit en context
- "frase": la frase sencera de la transcripció on apareix l'error (per donar context)

Retorna ÚNICAMENT un array JSON (sense cap text addicional):
[{{"original": "...", "correccio": "...", "motiu": "...", "frase": "..."}}]
Si no hi ha errors, retorna [].
            """,
            expected_output="Array JSON de correccions",
            agent=agent
        )

        crew = Crew(agents=[agent], tasks=[task], verbose=False)
        print("  → Agent corrector iniciat...")
        result = crew.kickoff()
        print("  ✓ Agent corrector finalitzat\n")

        raw = result.raw if hasattr(result, 'raw') else str(result)
        corrections = repair_json(raw, return_objects=True) or []
        if not isinstance(corrections, list):
            corrections = []

        # 3. Revisió interactiva dels nous errors detectats
        return self._apply_interactively(transcript, corrections)

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

    def _extract_context(self, transcript: str, original: str, chars: int = 200) -> str:
        idx = transcript.find(original)
        if idx == -1:
            return ''
        start = max(0, idx - chars)
        end = min(len(transcript), idx + len(original) + chars)
        snippet = transcript[start:end]
        highlighted = snippet.replace(original, f"{Fore.BLUE}[{original}]{Style.RESET_ALL}", 1)
        return highlighted

    def _apply_interactively(self, transcript: str, corrections: list) -> str:
        if not corrections:
            print("  Cap error detectat.\n")
            return transcript

        approved = []
        for c in corrections:
            context = self._extract_context(transcript, c['original'], chars=200)
            if context:
                print(f"  ...{context}...")
            print(f"  \"{c['original']}\" → \"{c['correccio']}\"  ({c['motiu']})")
            resp = input("  Aplicar? (s/n/m=siMemoritza/text propi): ").strip()
            print()

            if resp.lower() == 'm':
                approved.append(c)
                self._save_memorized(c['original'], c['correccio'])
                print(f"  ✓ Memoritzat: \"{c['original']}\" → \"{c['correccio']}\"\n")
            elif resp.lower() == 's':
                approved.append(c)
            elif resp.lower() not in ('n', ''):
                approved.append({**c, 'correccio': resp})
                mem = input(f"  Memoritzar \"{c['original']}\" → \"{resp}\"? (s/n): ").strip().lower()
                print()
                if mem == 's':
                    self._save_memorized(c['original'], resp)
                    print(f"  ✓ Memoritzat: \"{c['original']}\" → \"{resp}\"\n")

        for c in approved:
            transcript = transcript.replace(c['original'], c['correccio'])
        return transcript
