from pathlib import Path


class VocabularyLoader:
    def __init__(self, vocab_path: Path):
        self.path = Path(vocab_path)

    def load(self) -> dict:
        if not self.path.exists():
            return {}

        vocab = {}
        current_section = None
        in_frontmatter = False
        frontmatter_done = False

        for line in self.path.read_text(encoding='utf-8').splitlines():
            # Handle frontmatter
            if not frontmatter_done:
                if line.strip() == '---':
                    if not in_frontmatter:
                        in_frontmatter = True
                        continue
                    else:
                        frontmatter_done = True
                        continue
                if in_frontmatter:
                    continue

            # Section headers
            if line.startswith('## '):
                current_section = line[3:].strip()
                if current_section not in vocab:
                    vocab[current_section] = []
            elif line.startswith('### '):
                # Subsection: keep under current parent section
                pass
            elif line.startswith('- ') and current_section is not None:
                word = line[2:].strip()
                if word:
                    vocab[current_section].append(word)

        return vocab
