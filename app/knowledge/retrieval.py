"""Bounded lexical retrieval; retrieved prose is guidance, never an instruction source."""

from app.knowledge.loader import KnowledgeChunk, KnowledgeLoader


class KnowledgeRetriever:
    def __init__(self, loader: KnowledgeLoader | None = None) -> None:
        self.loader = loader or KnowledgeLoader()
        self._chunks: list[KnowledgeChunk] | None = None

    def search(self, task: str, *, limit: int = 4) -> list[KnowledgeChunk]:
        if self._chunks is None:
            self._chunks = self.loader.load()
        query = self._tokens(task)
        ranked: list[tuple[float, KnowledgeChunk]] = []
        for chunk in self._chunks:
            haystack = self._tokens(f"{chunk.document} {' '.join(chunk.tags)} {chunk.text}")
            score = len(query & haystack) / max(1, len(query))
            if score:
                ranked.append((score, chunk))
        ranked.sort(key=lambda item: (-item[0], item[1].document))
        return [chunk for _, chunk in ranked[: max(0, min(limit, 8))]]

    def compact_context(self, task: str, *, limit: int = 4) -> list[dict[str, str]]:
        return [
            {"ref": item.document, "guidance": item.text} for item in self.search(task, limit=limit)
        ]

    @staticmethod
    def _tokens(value: str) -> set[str]:
        return {token.casefold() for token in value.replace("_", " ").split() if len(token) > 2}
