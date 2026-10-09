import re
from pathlib import Path
from pydantic import BaseModel
from crewai import Agent, Task, Crew, LLM

from llm_config import log_crew_usage, model_hard, reasoning_effort


class ActiveTopicUpdate(BaseModel):
    topic_name: str
    summary: str
    conclusion: str = ""  # resum d'una línia del tema; "" per compat enrere
    # Projectes (nom de carpeta de Projectes/) on el tema decideix o informa
    # alguna cosa. Es renderitzen com a links [[X]]; [] per compat enrere.
    projects: list[str] = []


class MeetingAnalysisResult(BaseModel):
    updated_topics: list[ActiveTopicUpdate]
    new_other_topics: list[str]


def _flatten_paragraph(text: str) -> str:
    """Col·lapsa un resum multi-línia/multi-paràgraf del LLM en una sola línia.

    Sense això, un summary amb salts de línia interns (el LLM sovint en fa un
    per paràgraf) trencava el bullet Markdown: la primera línia quedava com a
    "- ...", la resta com a paràgrafs solts sense guió just a sota."""
    return ' '.join(text.split())


def _projects_line(projects: list[str]) -> str:
    """Text de la línia de projectes d'un tema (sense el prefix de bullet)."""
    return "**Projectes:** " + ", ".join(f"[[{p}]]" for p in projects)


# [[X]], [[X|àlies]], [[X#secció]] → X
_WIKILINK_RE = re.compile(r'\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]')


def _parse_project_links(text: str) -> list[str]:
    """Noms dels fitxers enllaçats a `text`, en ordre i sense duplicats."""
    seen: list[str] = []
    for name in _WIKILINK_RE.findall(text):
        name = name.strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def projects_prompt_section(projects: list[tuple[str, list[str]]]) -> str:
    """Bloc del prompt amb la llista de projectes per etiquetar els temes.
    Buit si no n'hi ha (el prompt queda com abans: sense links)."""
    if not projects:
        return ""
    lines = []
    for name, aliases in projects:
        lines.append(f"- {name} (també: {', '.join(aliases)})" if aliases else f"- {name}")
    return f"""
PROJECTES DE L'EMPRESA (nom canònic, i entre parèntesis altres noms amb què s'hi fa referència):
{chr(10).join(lines)}

ETIQUETATGE DE PROJECTES:
- Per cada tema, omple el camp `projects` amb el NOM CANÒNIC dels projectes de la llista sobre els quals en aquest tema es DECIDEIX o s'INFORMA alguna cosa rellevant (estat, problemes, decisions, terminis, responsables, propers passos).
- Inclou-hi el projecte encara que no s'anomeni explícitament, si pel context és inequívoc que el tema en tracta.
- NO hi posis un projecte només perquè s'esmenta de passada o com a comparació.
- Si el tema no tracta cap projecte de la llista, deixa `projects` buit. No inventis projectes que no siguin a la llista.
"""


def normalize_projects(result: MeetingAnalysisResult,
                       projects: list[tuple[str, list[str]]]) -> MeetingAnalysisResult:
    """Valida els projectes que retorna el LLM: àlies → nom canònic (sense
    distingir majúscules), treu `[[ ]]`, elimina duplicats i descarta noms
    que no existeixen (un link inventat crearia una nota buida a Obsidian).
    Als `new_other_topics` valida igualment els links inline `[[X]]`."""
    lookup: dict[str, str] = {}
    for name, aliases in projects:
        for key in (name, *aliases):
            lookup.setdefault(key.strip().lower(), name)

    def canon(raw: str) -> str | None:
        return lookup.get(raw.strip().strip('[]').split('|')[0].split('#')[0].strip().lower())

    for topic in result.updated_topics:
        clean: list[str] = []
        for raw in topic.projects:
            name = canon(raw)
            if name and name not in clean:
                clean.append(name)
        topic.projects = clean

    def fix_inline(text: str) -> str:
        def sub(m):
            name = canon(m.group(1))
            return f"[[{name}]]" if name else ""
        return ' '.join(_WIKILINK_RE.sub(sub, text).split())

    result.new_other_topics = [fix_inline(t) for t in result.new_other_topics]
    return result


def _iso_date(date_label: str) -> str:
    """'261005' → '2026-10-05'; si no és YYMMDD, '?'."""
    if len(date_label) == 6 and date_label.isdigit():
        return f"20{date_label[:2]}-{date_label[2:4]}-{date_label[4:]}"
    return "?"


def _link_safe(text: str) -> str:
    """Treu els caràcters que trenquen un link d'Obsidian a un encapçalament."""
    return ' '.join(re.sub(r'[\[\]#|^]', ' ', text).split())


def build_project_mentions(result: MeetingAnalysisResult, date_label: str,
                           series_label: str, year_note_stem: str, heading: str,
                           exclude=()) -> dict[str, list[str]]:
    """Línies de menció per a la nota principal de cada projecte etiquetat.

    Una línia per (tema, projecte): data · link al bloc de l'anual · tema:
    conclusió (o resum si no n'hi ha). Els 'Altres temes' compten si porten
    links inline [[X]] (el text de la menció va sense els links).
    `exclude`: projectes a ometre (la sèrie mateixa de la reunió)."""
    link = f"[[{year_note_stem}#{_link_safe(heading)}|{series_label}]]"
    prefix = f"- **{_iso_date(date_label)}** · {link} · "
    out: dict[str, list[str]] = {}

    def add(project: str, line: str):
        if project in exclude:
            return
        lines = out.setdefault(project, [])
        if line not in lines:
            lines.append(line)

    for t in result.updated_topics:
        text = _flatten_paragraph(t.conclusion or t.summary)
        for project in t.projects:
            add(project, f"{prefix}*{t.topic_name}*: {text}")
    for other in result.new_other_topics:
        projects = _parse_project_links(other)
        text = ' '.join(_WIKILINK_RE.sub('', other).split())
        for project in projects:
            add(project, f"{prefix}*Altres temes*: {text}")
    return out


def parse_active_topics(temes_oberts_path: Path) -> list[str]:
    """Llegeix Temes oberts.md i retorna els noms de les seccions ### (exclou ## Altres temes)."""
    content = Path(temes_oberts_path).read_text(encoding='utf-8')
    topics = []
    for line in content.splitlines():
        if re.match(r'^#{1,6} Altres temes', line):
            break
        match = re.match(r'^#{2,6} (.+)$', line)
        if match:
            topics.append(match.group(1).strip())
    return topics


# Els "Altres temes" són text lliure (no tenen camp `projects`): el link va inline.
OTHER_TOPICS_LINKS_INSTRUCTION = (
    "- Als new_other_topics, si un tema tracta un projecte de la llista amb el mateix criteri, "
    "afegeix al final del text el link amb el nom canònic, per exemple: \"... [[A10Pro]]\".\n"
)


class MeetingAnalyzer:
    def __init__(self, model: str = None):
        # Tier hard: la qualitat dels resums acaba a la memòria permanent
        # (Ordre del dia → Temes oberts + anual).
        self.llm = LLM(model=model or model_hard(), drop_params=True,
                       reasoning_effort=reasoning_effort())

    def analyze(self, topics: list[str], transcript: str, brief: bool = False,
                projects: list[tuple[str, list[str]]] | None = None) -> MeetingAnalysisResult:
        topics_list = '\n'.join(f'- {t}' for t in topics)
        summary_instruction = (
            "escriu un resum de màxim 2 línies del que s'ha dit."
            if brief else
            "escriu un resum de 3-4 línies del que s'ha dit, incloent decisions preses, estat actual i propers passos si s'han mencionat."
        )

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
- Per cada tema obert que s'hagi tractat a la reunió, {summary_instruction}
- Per cada tema tractat, omple també el camp `conclusion` amb una conclusió molt breu d'una sola línia (el resultat o punt clau del tema).
- Només resumeix el que s'ha dit, no inventis.
- Si un tema no s'ha tractat, NO l'incloguis a updated_topics.
- Si s'han tractat temes nous que no estan a la llista de temes oberts, afegeix-los a new_other_topics amb una descripció breu.
- El camp topic_name ha de coincidir EXACTAMENT amb el nom del tema tal com apareix a la llista.
{projects_prompt_section(projects or [])}{OTHER_TOPICS_LINKS_INSTRUCTION if projects else ""}""",
            expected_output="MeetingAnalysisResult amb els temes tractats i nous temes",
            agent=agent,
            output_pydantic=MeetingAnalysisResult
        )

        crew = Crew(agents=[agent], tasks=[task], verbose=False)
        print("  → Agent analista iniciat...")
        result = crew.kickoff()
        print("  ✓ Agent analista finalitzat\n")
        log_crew_usage('analisi seguiment', crew)
        return normalize_projects(result.pydantic, projects or [])

    def summarize(self, transcript: str, brief: bool = False,
                  projects: list[tuple[str, list[str]]] | None = None) -> MeetingAnalysisResult:
        """Resum lliure d'una reunió: NO parteix d'una llista de temes oberts.

        El LLM detecta pel seu compte els temes principals tractats i en fa un
        resum cada un. A diferència d'analyze(), no compara amb Temes oberts ni
        genera agenda — és purament un resum de la reunió. Retorna els temes
        detectats a updated_topics (new_other_topics queda buit) per reusar el
        mateix format/parse de l'Ordre del dia.
        """
        summary_instruction = (
            "escriu un resum de màxim 2 línies del que s'ha dit."
            if brief else
            "escriu un resum de 3-4 línies del que s'ha dit, incloent decisions preses, estat actual i propers passos si s'han mencionat."
        )

        agent = Agent(
            role="Analista de reunions",
            goal="Resumir una transcripció de reunió tema per tema",
            backstory="Expert en síntesi de reunions tecnològiques en català.",
            llm=self.llm,
            verbose=False
        )

        task = Task(
            description=f"""
Analitza la transcripció d'una reunió i identifica els temes principals que s'hi han tractat.

TRANSCRIPCIÓ:
{transcript}

INSTRUCCIONS:
- Identifica els temes principals tractats a la reunió (tu decideixes quins són; no parteixes de cap llista prèvia).
- Per cada tema, {summary_instruction}
- Per cada tema, omple també el camp `conclusion` amb una conclusió molt breu d'una sola línia (el resultat o punt clau del tema).
- Només resumeix el que s'ha dit, no inventis.
- Posa TOTS els temes a updated_topics: topic_name = nom curt del tema, summary = el resum, conclusion = la conclusió d'una línia.
- Deixa new_other_topics buit.
{projects_prompt_section(projects or [])}""",
            expected_output="MeetingAnalysisResult amb un tema i resum per cada assumpte tractat",
            agent=agent,
            output_pydantic=MeetingAnalysisResult
        )

        crew = Crew(agents=[agent], tasks=[task], verbose=False)
        print("  → Agent de resum iniciat...")
        result = crew.kickoff()
        print("  ✓ Agent de resum finalitzat\n")
        log_crew_usage('resum lliure', crew)
        return normalize_projects(result.pydantic, projects or [])


class StateFileUpdater:
    def update(self, temes_oberts_path: Path, result: MeetingAnalysisResult, date_label: str) -> str:
        """Aplica updates al fitxer Temes oberts.md i retorna el bloc del resum
        d'aquesta reunió (tots els temes tractats + temes nous) en format markdown
        perquè el caller l'escrigui al fitxer anual via append_to_year_note.

        Els temes que el LLM marqui com a "(Tancat)" queden al fitxer Temes oberts.md
        amb la marca; l'usuari els eliminarà manualment quan ho decideixi.

        Retorna cadena buida si no hi ha temes tractats ni temes nous.
        """
        if not result.updated_topics and not result.new_other_topics:
            return ""

        content = Path(temes_oberts_path).read_text(encoding='utf-8')
        lines = content.splitlines()

        if result.updated_topics:
            lines = self._insert_topic_updates(lines, result.updated_topics, date_label)

        lines = self._update_other_topics(lines, result.new_other_topics)

        Path(temes_oberts_path).write_text('\n'.join(lines) + '\n', encoding='utf-8')
        return self.build_year_block(result)

    def build_year_block(self, result: MeetingAnalysisResult) -> str:
        """Construeix el bloc del resum d'aquesta reunió (temes tractats + altres
        temes nous) per ser afegit al fitxer anual."""
        block_lines: list[str] = []
        for topic in result.updated_topics:
            block_lines.append(f"### {topic.topic_name}")
            block_lines.append(f"- {_flatten_paragraph(topic.summary)}")
            if topic.conclusion:
                block_lines.append(f"- **Conclusió:** {_flatten_paragraph(topic.conclusion)}")
            if topic.projects:
                block_lines.append(f"- {_projects_line(topic.projects)}")
            block_lines.append("")
        if result.new_other_topics:
            block_lines.append("#### Altres temes")
            for new_topic in result.new_other_topics:
                block_lines.append(f"- {new_topic}")
        while block_lines and not block_lines[-1].strip():
            block_lines.pop()
        return '\n'.join(block_lines)

    def _insert_topic_updates(self, lines: list[str], updates: list[ActiveTopicUpdate], date_label: str) -> list[str]:
        updates_by_name = {u.topic_name: u.summary for u in updates}
        new_lines = []
        i = 0
        while i < len(lines):
            new_lines.append(lines[i])
            match = re.match(r'^#{2,6} (.+)$', lines[i])
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

    def _update_other_topics(self, lines: list[str], new_topics: list[str]) -> list[str]:
        """Buida la secció '## Altres temes' del fitxer i hi posa els temes nous
        d'aquesta reunió. Els antics no es preserven — ja s'han escrit al fitxer
        anual en el processat previ on van aparèixer.

        Si la secció '## Altres temes' no existeix, els nous temes no es desen
        (cap creació automàtica per evitar fitxers mal estructurats sense criteri editorial)."""
        new_lines = []
        in_altres = False
        for line in lines:
            if re.match(r'^#{1,6} Altres temes', line):
                in_altres = True
                new_lines.append(line)
                for topic in new_topics:
                    new_lines.append(f'- {topic}')
                continue
            if in_altres and re.match(r'^#{1,6} ', line):
                in_altres = False
                new_lines.append(line)
                continue
            if in_altres:
                # Dins la secció Altres temes — descartem el contingut antic
                continue
            new_lines.append(line)
        return new_lines


def format_ordre_del_dia(result: MeetingAnalysisResult, all_topics: list[str], date_str: str) -> str:
    lines = [f"### Resum de la reunió anterior {date_str}", ""]

    for i, t in enumerate(result.updated_topics, 1):
        lines.append(f"#### *{i}) {t.topic_name}*")
        lines.append(f"* {_flatten_paragraph(t.summary)}")
        if t.conclusion:
            lines.append(f"* **Conclusió:** {_flatten_paragraph(t.conclusion)}")
        if t.projects:
            lines.append(f"* {_projects_line(t.projects)}")
        lines.append("")

    if result.new_other_topics:
        lines.append("#### *Altres temes*")
        for topic in result.new_other_topics:
            lines.append(f"* {topic}")
        lines.append("")

    lines.append("Ordre del dia propera reunió:")
    for i, t in enumerate(all_topics, 1):
        lines.append(f"{i}) {t}")

    return '\n'.join(lines) + '\n'


def format_resum(result: MeetingAnalysisResult, date_str: str) -> str:
    """Format de l'Ordre del dia per a l'opció 'Resum' (resum lliure):
    mateixa secció 'Resum de la reunió' que els seguiments (perquè
    parse_ordre_del_dia la reconegui) però SENSE l'agenda 'Ordre del dia
    propera reunió:' — un resum pur no porta seguiment de temes."""
    lines = [f"### Resum de la reunió {date_str}", ""]

    for i, t in enumerate(result.updated_topics, 1):
        lines.append(f"#### *{i}) {t.topic_name}*")
        lines.append(f"* {_flatten_paragraph(t.summary)}")
        if t.conclusion:
            lines.append(f"* **Conclusió:** {_flatten_paragraph(t.conclusion)}")
        if t.projects:
            lines.append(f"* {_projects_line(t.projects)}")
        lines.append("")

    if result.new_other_topics:
        lines.append("#### *Altres temes*")
        for topic in result.new_other_topics:
            lines.append(f"* {topic}")
        lines.append("")

    return '\n'.join(lines).rstrip('\n') + '\n'


def parse_ordre_del_dia(text: str) -> MeetingAnalysisResult:
    """Invers de format_ordre_del_dia: reconstrueix el MeetingAnalysisResult a
    partir del fitxer Ordre del dia de la sèrie (possiblement editat a
    mà per l'usuari durant la validació).

    Llegeix només la secció 'Resum de la reunió anterior' (els temes tractats i
    els 'Altres temes'); ignora la llista 'Ordre del dia propera reunió:' final,
    que és l'agenda de temes oberts i ja viu a Temes oberts.md.

    Tolera edicions lleugeres (text dels resums modificat, espais). Si l'usuari
    canvia el NOM d'un tema, deixarà de coincidir amb la capçalera de Temes
    oberts i el bullet no s'hi inserirà (però sí anirà al fitxer anual). Si parteix
    un resum en diverses línies/bullets, es concatenen amb un espai.
    """
    updated_topics: list[ActiveTopicUpdate] = []
    new_other_topics: list[str] = []
    mode = None  # None | 'topic' | 'altres'
    current_name: str | None = None
    current_summary_lines: list[str] = []
    current_conclusion: str = ""
    current_projects: list[str] = []

    def flush_topic():
        nonlocal current_name, current_summary_lines, current_conclusion, current_projects
        if current_name is not None:
            summary = ' '.join(s for s in current_summary_lines if s)
            updated_topics.append(
                ActiveTopicUpdate(
                    topic_name=current_name,
                    summary=summary,
                    conclusion=current_conclusion,
                    projects=current_projects,
                )
            )
        current_name = None
        current_summary_lines = []
        current_conclusion = ""
        current_projects = []

    started = False
    for line in text.splitlines():
        if re.match(r'^#{2,6}\s+Resum de la reunió', line):
            started = True
            continue
        if not started:
            continue
        if re.match(r'^\s*Ordre del dia propera reunió\s*:', line):
            break
        if re.match(r'^#{2,6}\s+\*?\s*Altres temes\s*\*?\s*$', line):
            flush_topic()
            mode = 'altres'
            continue
        m = re.match(r'^#{2,6}\s+\*?\s*\d+\)\s*(.+?)\s*\*?\s*$', line)
        if m:
            flush_topic()
            mode = 'topic'
            current_name = m.group(1).strip().rstrip('*').strip()
            continue
        stripped = line.strip()
        if not stripped:
            continue
        content = re.sub(r'^[\*\-]\s+', '', stripped)
        if mode == 'topic':
            cm = re.match(r'^\**\s*Conclusió\s*:\s*\**\s*(.*)$', content, re.IGNORECASE)
            pm = re.match(r'^\**\s*Projectes\s*:\s*\**\s*(.*)$', content, re.IGNORECASE)
            if cm:
                current_conclusion = cm.group(1).strip().rstrip('*').strip()
            elif pm:
                current_projects = _parse_project_links(pm.group(1))
            else:
                current_summary_lines.append(content)
        elif mode == 'altres':
            new_other_topics.append(content)

    flush_topic()
    return MeetingAnalysisResult(
        updated_topics=updated_topics, new_other_topics=new_other_topics
    )


ORDRE_PENDING_KEY = 'pendent_revisio'
ORDRE_KIND_KEY = 'tipus_consolidacio'  # 'seguiment' (default) | 'resum'
ORDRE_INTERNAL_KEYS = (ORDRE_PENDING_KEY, ORDRE_KIND_KEY)


def with_pending_marker(ordre_content: str, kind: str = 'seguiment') -> str:
    """Afegeix el frontmatter '<ORDRE_PENDING_KEY>: true' a dalt de l'Ordre del
    dia (fase 1) perquè sigui cercable a Obsidian com a pendent de revisar
    (`[pendent_revisio]` al cercador). `parse_ordre_del_dia` ignora el
    frontmatter (va abans de la capçalera 'Resum').

    `kind` indica a la fase 2 (Consolidar) com propagar el contingut: 'seguiment'
    (default) → Temes oberts + anual; 'resum' → només anual. Per a 'seguiment'
    NO s'escriu la clau de tipus (compatibilitat amb Ordres del dia existents:
    l'absència de la clau es llegeix com a 'seguiment')."""
    if kind == 'seguiment':
        return f"---\n{ORDRE_PENDING_KEY}: true\n---\n{ordre_content}"
    return f"---\n{ORDRE_PENDING_KEY}: true\n{ORDRE_KIND_KEY}: {kind}\n---\n{ordre_content}"


def read_ordre_kind(text: str) -> str:
    """Llegeix el tipus de consolidació del frontmatter de l'Ordre del dia.
    Retorna 'seguiment' si la clau no hi és (compatibilitat enrere)."""
    m = re.match(r'^---\n(.*?)\n---\n?', text, re.DOTALL)
    if not m:
        return 'seguiment'
    for line in m.group(1).splitlines():
        km = re.match(rf'^\s*{ORDRE_KIND_KEY}\s*:\s*(.+?)\s*$', line)
        if km:
            return km.group(1).strip()
    return 'seguiment'


def strip_pending_marker(text: str) -> str:
    """Treu les claus internes de processat del frontmatter (fase 2), conservant
    la resta del fitxer (incloses edicions de l'usuari i altres claus). Si el
    frontmatter queda buit, l'elimina del tot. Idempotent: si no hi ha cap marca,
    retorna el text sense canvis."""
    m = re.match(r'^---\n(.*?)\n---\n?', text, re.DOTALL)
    if not m:
        return text
    fm_lines = [
        line for line in m.group(1).splitlines()
        if not any(re.match(rf'^\s*{key}\s*:', line) for key in ORDRE_INTERNAL_KEYS)
    ]
    rest = text[m.end():]
    fm_body = '\n'.join(fm_lines).strip('\n')
    if not fm_body:
        return rest
    return f"---\n{fm_body}\n---\n{rest}"
