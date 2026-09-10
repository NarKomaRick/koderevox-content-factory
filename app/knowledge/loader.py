"""Load only the checked-in Director knowledge documents."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class KnowledgeChunk:
    document: str
    text: str
    tags: tuple[str, ...]


class KnowledgeLoader:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(__file__).resolve().parents[2] / "director_knowledge"

    def load(self) -> list[KnowledgeChunk]:
        chunks: list[KnowledgeChunk] = []
        for path in sorted(self.root.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
            tags = tuple(path.stem.replace("_", " ").split())
            for index, paragraph in enumerate(paragraphs):
                chunks.append(KnowledgeChunk(f"{path.name}#{index}", paragraph[:1600], tags))
        return chunks
