import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PlatformAccount, Project
from app.models.enums import PublishingPlatform
from app.schemas.publishing import PlatformAccountCreate, PlatformAccountUpdate
from app.services.errors import NotFoundError


class PlatformAccountService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, data: PlatformAccountCreate) -> PlatformAccount:
        if await self.session.get(Project, data.project_id) is None:
            raise NotFoundError("Project not found")
        account = PlatformAccount(**data.model_dump())
        self.session.add(account)
        await self.session.commit()
        await self.session.refresh(account)
        return account

    async def get(self, account_id: uuid.UUID) -> PlatformAccount:
        account = await self.session.get(PlatformAccount, account_id)
        if account is None:
            raise NotFoundError("PlatformAccount not found")
        return account

    async def list(
        self,
        *,
        project_id: uuid.UUID | None = None,
        platform: PublishingPlatform | None = None,
    ) -> Sequence[PlatformAccount]:
        query = select(PlatformAccount)
        if project_id:
            query = query.where(PlatformAccount.project_id == project_id)
        if platform:
            query = query.where(PlatformAccount.platform == platform)
        return (await self.session.scalars(query.order_by(PlatformAccount.display_name))).all()

    async def update(self, account_id: uuid.UUID, data: PlatformAccountUpdate) -> PlatformAccount:
        account = await self.get(account_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(account, field, value)
        await self.session.commit()
        await self.session.refresh(account)
        return account
