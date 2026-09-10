"""Provider-neutral external asset search contract; no network provider is enabled by default."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AssetSearchResult:
    provider: str
    source_url: str
    original_url: str
    title: str
    media_type: str
    license: str | None
    license_url: str | None
    author: str | None
    attribution_required: bool
    query: str

    def provenance(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "source_url": self.source_url,
            "original_url": self.original_url,
            "author": self.author,
            "license": self.license,
            "license_url": self.license_url,
            "attribution_required": self.attribution_required,
            "query": self.query,
            "usage_status": "unverified" if self.license is None else "verified",
        }


class AssetSearchProvider(Protocol):
    async def search_images(self, query: str, *, limit: int = 10) -> list[AssetSearchResult]: ...

    async def search_videos(self, query: str, *, limit: int = 10) -> list[AssetSearchResult]: ...

    async def get_metadata(self, url: str) -> AssetSearchResult: ...

    async def download(self, result: AssetSearchResult, destination: str) -> int: ...
