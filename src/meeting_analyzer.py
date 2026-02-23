import os
import re
from pathlib import Path
from pydantic import BaseModel
from crewai import Agent, Task, Crew, LLM


class ActiveTopicUpdate(BaseModel):
    topic_name: str
    summary: str


class MeetingAnalysisResult(BaseModel):
    updated_topics: list[ActiveTopicUpdate]
    new_other_topics: list[str]


def parse_active_topics(estat_path: Path) -> list[str]:
    """Llegeix Estat actual.md i retorna els noms de les seccions ### (exclou ## Altres temes)."""
    content = Path(estat_path).read_text(encoding='utf-8')
    topics = []
    for line in content.splitlines():
        if re.match(r'^#{1,6} Altres temes', line):
            break
        match = re.match(r'^### (.+)$', line)
        if match:
            topics.append(match.group(1).strip())
    return topics


class MeetingAnalyzer:
    def __init__(self, model: str = None):
        self.llm = LLM(model=model or os.getenv('LLM_MODELH'), drop_params=True)

    def analyze(self, topics: list[str], transcript: str) -> MeetingAnalysisResult:
        topics_list = '\n'.join(f'- {t}' for t in topics)

        agent = Agent(
            role="Analista de reunions de seguiment",
            goal="Analitzar una transcripció de reunió i extreure resums per cada tema tractat",
            backstory="Expert en anàlisi de reunions de seguiment de projectes tecnològics en català.",
            llm=self.llm,
            verbose=False
        )

        task = Task(
            description=f"""
Analitza la transcripció d'una reunió de seguiment i determina quins temes s'han tractat.

TEMES OBERTS ACTUALS:
{topics_list}

TRANSCRIPCIÓ:
{transcript}

INSTRUCCIONS:
- Per cada tema obert que s'hagi tractat a la reunió, escriu un resum de 3-4 línies del que s'ha dit, incloent decisions preses, estat actual i propers passos si s'han mencionat.
- Només resumeix el que s'ha dit, no inventis.
- Si un tema no s'ha tractat, NO l'incloguis a updated_topics.
- Si s'han tractat temes nous que no estan a la llista de temes oberts, afegeix-los a new_other_topics amb una descripció breu.
- El camp topic_name ha de coincidir EXACTAMENT amb el nom del tema tal com apareix a la llista.
""",
            expected_output="MeetingAnalysisResult amb els temes tractats i nous temes",
            agent=agent,
            output_pydantic=MeetingAnalysisResult
        )

        crew = Crew(agents=[agent], tasks=[task], verbose=False)
        print("  → Agent analista iniciat...")
        result = crew.kickoff()
        print("  ✓ Agent analista finalitzat\n")
        return result.pydantic


class StateFileUpdater:
    def update(self, estat_path: Path, result: MeetingAnalysisResult, date_label: str):
        if not result.updated_topics and not result.new_other_topics:
            return

        content = Path(estat_path).read_text(encoding='utf-8')
        lines = content.splitlines()

        if result.updated_topics:
            lines = self._insert_topic_updates(lines, result.updated_topics, date_label)

        lines, old_altres = self._update_other_topics(lines, result.new_other_topics)
        if old_altres:
            self._append_to_historic(estat_path.parent / 'Històric.md', old_altres, date_label)
        if old_altres:
            self._append_to_historic(estat_path.parent / 'Històric.md', old_altres, date_label)

        Path(estat_path).write_text('\n'.join(lines) + '\n', encoding='utf-8')

    def _insert_topic_updates(self, lines: list[str], updates: list[ActiveTopicUpdate], date_label: str) -> list[str]:
        updates_by_name = {u.topic_name: u.summary for u in updates}
        new_lines = []
        i = 0
        while i < len(lines):
            new_lines.append(lines[i])
            match = re.match(r'^### (.+)$', lines[i])
            if match:
                topic = match.group(1).strip()
                if topic in updates_by_name:
                    # Find the insertion point: just before the next header or end
                    j = i + 1
                    while j < len(lines) and not lines[j].startswith('## ') and not lines[j].startswith('### '):
                        new_lines.append(lines[j])
                        j += 1
                    new_lines.append(f"- **{date_label}:** {updates_by_name[topic]}")
                    i = j
                    continue
            i += 1
        return new_lines

    def _update_other_topics(self, lines: list[str], new_topics: list[str]) -> tuple[list[str], list[str]]:
        new_lines = []
        old_altres_content = []
        in_altres = False
        for line in lines:
            if re.match(r'^#{1,6} Altres temes', line):
                in_altres = True
                new_lines.append(line)
                for topic in new_topics:
                    new_lines.append(f'- {topic}')
                continue
            if in_altres:
                if re.match(r'^#{1,6} ', line) and not re.match(r'^#{1,6} Altres temes', line):
                    in_altres = False
                    new_lines.append(line)
                else:
                    if line.strip():
                        old_altres_content.append(line)
                continue
            new_lines.append(line)
        return new_lines, old_altres_content

    def _append_to_historic(self, historic_path: Path, content: list[str], date_label: str):
        existing = historic_path.read_text(encoding='utf-8') if historic_path.exists() else ''
        block = f'\n## Reunió {date_label}\n' + '\n'.join(content) + '\n'
        historic_path.write_text(existing + block, encoding='utf-8')
