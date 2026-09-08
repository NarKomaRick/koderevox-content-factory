from typing import Protocol

from app.schemas.publishing import (
    PlatformValidationResult,
    ProviderStatusResult,
    PublisherContext,
    PublishRequest,
    PublishResult,
)


class Publisher(Protocol):
    async def validate(
        self, request: PublishRequest, context: PublisherContext
    ) -> PlatformValidationResult: ...

    async def publish(
        self, request: PublishRequest, context: PublisherContext
    ) -> PublishResult: ...

    async def get_status(
        self, request: PublishRequest, context: PublisherContext
    ) -> ProviderStatusResult: ...

    async def delete(self, request: PublishRequest, context: PublisherContext) -> None: ...
