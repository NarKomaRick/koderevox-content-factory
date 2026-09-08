from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies import InboxDep
from app.models.enums import SourceStatus, SourceType
from app.schemas.api import DailyDigest, InboxPage

router = APIRouter(prefix="/inbox", tags=["inbox"])


@router.get("", response_model=InboxPage)
async def list_inbox(
    inbox: InboxDep,
    telegram_user_id: int,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=20)] = 5,
    source_type: SourceType | None = None,
    status: SourceStatus | None = None,
    best: bool = False,
    query: Annotated[str | None, Query(max_length=200)] = None,
) -> InboxPage:
    return await inbox.list_inbox(
        telegram_user_id=telegram_user_id,
        page=page,
        page_size=page_size,
        source_type=source_type,
        status=status,
        best=best,
        query_text=query,
    )


@router.get("/digest", response_model=DailyDigest)
async def digest(inbox: InboxDep, telegram_user_id: int) -> DailyDigest:
    return await inbox.digest(telegram_user_id)
