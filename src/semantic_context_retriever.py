from pathlib import Path
from semantic_models import SemanticMemory, SemanticContext


class SemanticContextRetriever:
    def load(self, meeting_dir: Path) -> SemanticContext | None:
        json_path = meeting_dir / 'semantic_memory.json'
        if not json_path.exists():
            return None
        memory = SemanticMemory.model_validate_json(json_path.read_text(encoding='utf-8'))
        return SemanticContext(
            relevant_projects=memory.projects,
            likely_terms=memory.technical_terms,
            topic_context=memory.recurring_topics,
            aliases=memory.aliases
        )
