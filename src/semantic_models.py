from pydantic import BaseModel


class SemanticMemory(BaseModel):
    person: str
    projects: list[str]
    technical_terms: list[str]
    aliases: dict[str, str]        # transcripció_errònia → terme_correcte
    recurring_topics: list[str]


class SemanticContext(BaseModel):
    relevant_projects: list[str]
    likely_terms: list[str]
    topic_context: list[str]
    aliases: dict[str, str]
