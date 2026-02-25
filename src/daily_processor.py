import os
from pydantic import BaseModel
from crewai import Agent, Task, Crew, LLM


class PersonDaily(BaseModel):
    name: str
    ahir: list[str]
    avui: list[str]


class DailyScrumResult(BaseModel):
    participants: list[PersonDaily]
    altres_temes: list[str]


class DailyProcessor:
    def __init__(self, vocab: dict, model: str = None):
        self.vocab = vocab
        self.llm = LLM(model=model or os.getenv('LLM_MODELH'), drop_params=True)

    def process(self, transcript: str, attendees: list[dict]) -> DailyScrumResult:
        vocab_text = self._format_vocab()
        attendees_filtered = [a for a in attendees if a.get('name') != 'Jordi Beringues']
        attendees_list = '\n'.join(f'- {a["name"]}' for a in attendees_filtered)

        agent = Agent(
            role="Analista de Daily Scrum",
            goal="Extreure el resum per persona d'una reunió de Daily Scrum",
            backstory="Expert en anàlisi de reunions Daily Scrum en català per equips tecnològics.",
            llm=self.llm,
            verbose=False
        )

        task = Task(
            description=f"""
Analitza la transcripció d'una reunió de Daily Scrum (sincronització diària).

ASSISTENTS (noms exactes que has d'usar):
{attendees_list}

VOCABULARI DE L'EMPRESA (per escriure correctament noms de productes, projectes i persones):
{vocab_text}

TRANSCRIPCIÓ:
{transcript}

INSTRUCCIONS:
- Per cada assistent, extreu el que va fer AHIR (passat) i el que farà AVUI (futur/pla).
- Usa temps PASSAT per "ahir" i temps FUTUR o present per "avui".
- Si una persona no menciona què va fer ahir, deixa la llista "ahir" buida.
- Si una persona no menciona què farà avui, deixa la llista "avui" buida.
- Cada bullet ha de ser una frase curta i clara (1-2 línies màxim).
- El camp "name" ha de coincidir EXACTAMENT amb un dels noms de la llista d'assistents.
- Usa el vocabulari per escriure correctament noms de productes, projectes i persones.
- No inventis informació que no aparegui a la transcripció.
- Si es discuteixen temes addicionals (decisions, blockers, discussions generals), afegeix-los a "altres_temes" com a frases curtes.
- Si no hi ha temes addicionals, deixa "altres_temes" buit.
""",
            expected_output="DailyScrumResult amb participants i altres_temes",
            agent=agent,
            output_pydantic=DailyScrumResult
        )

        crew = Crew(agents=[agent], tasks=[task], verbose=False)
        print("  → Agent Daily Scrum iniciat...")
        result = crew.kickoff()
        print("  ✓ Agent Daily Scrum finalitzat\n")
        return result.pydantic

    def format_markdown(self, result: DailyScrumResult, meeting_title: str, date_str: str) -> str:
        lines = [f"# {meeting_title} - {date_str}", ""]

        for p in result.participants:
            lines.append(f"##### [[{p.name}]]")
            if p.ahir:
                lines.append("**Ahir:**")
                for item in p.ahir:
                    lines.append(f"- {item}")
            if p.avui:
                lines.append("**Avui:**")
                for item in p.avui:
                    lines.append(f"- {item}")
            lines.append("")

        if result.altres_temes:
            lines.append("## Altres temes tractats")
            for topic in result.altres_temes:
                lines.append(f"- {topic}")
            lines.append("")

        return '\n'.join(lines)

    def _format_vocab(self) -> str:
        lines = []
        for seccio, paraules in self.vocab.items():
            lines.append(f"{seccio}: {', '.join(paraules)}")
        return '\n'.join(lines)
