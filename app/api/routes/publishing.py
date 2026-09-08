import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    OAuthDep,
    PlatformAccountDep,
    PlatformAdaptationDep,
    PlatformVariantMediaDep,
    PublicationDep,
    PublicationQueueDep,
    PublishingValidationDep,
)
from app.core.config import get_settings
from app.db.session import get_session
from app.models.enums import PublicationStatus, PublishingPlatform
from app.schemas.publishing import (
    OAuthCallbackResponse,
    OAuthStartResponse,
    PackagePrepareRequest,
    PackageWithVariants,
    PlatformAccountCreate,
    PlatformAccountRead,
    PlatformAccountUpdate,
    PlatformValidationResult,
    PlatformVariantRead,
    PlatformVariantUpdate,
    PublicationBatchCreate,
    PublicationBatchResponse,
    PublicationDetail,
    PublicationRead,
    PublicationReschedule,
    PublishPackageRead,
    VariantMediaPrepareResponse,
)
from app.services.errors import InvalidStateError
from app.services.tiktok_webhooks import TikTokWebhookService

router = APIRouter(tags=["publishing"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post("/oauth/{platform}/start", response_model=OAuthStartResponse)
async def start_oauth(
    platform: PublishingPlatform, account_id: uuid.UUID, service: OAuthDep
) -> object:
    from app.models import PlatformAccount
    from app.services.errors import NotFoundError

    account = await service.session.get(PlatformAccount, account_id)
    if account is None or account.platform != platform:
        raise NotFoundError("PlatformAccount not found")
    return await service.start(account_id)


@router.get("/oauth/{platform}/callback", response_model=OAuthCallbackResponse)
async def oauth_callback(
    platform: PublishingPlatform, state: str, code: str, service: OAuthDep
) -> OAuthCallbackResponse:
    account = await service.callback(platform, state, code)
    return OAuthCallbackResponse(platform_account_id=account.id, platform=account.platform)


@router.post("/webhooks/tiktok", status_code=status.HTTP_200_OK)
async def tiktok_webhook(
    request: Request,
    session: SessionDep,
    tiktok_signature: str = Header(alias="TikTok-Signature"),
) -> dict[str, bool]:
    settings = get_settings()
    service = TikTokWebhookService(
        session,
        settings.tiktok_client_key,
        settings.tiktok_client_secret,
        tolerance_seconds=settings.tiktok_webhook_tolerance_seconds,
    )
    try:
        processed = await service.handle(await request.body(), tiktok_signature)
    except InvalidStateError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return {"accepted": True, "processed": processed}


@router.post(
    "/video-projects/{video_project_id}/publish-package",
    response_model=PackageWithVariants,
    status_code=status.HTTP_201_CREATED,
)
async def prepare_publish_package(
    video_project_id: uuid.UUID,
    data: PackagePrepareRequest,
    service: PlatformAdaptationDep,
) -> PackageWithVariants:
    package, variants = await service.prepare_package(
        video_project_id, data.platforms, regenerate=data.regenerate
    )
    return PackageWithVariants(package=package, variants=list(variants))


@router.get("/publish-packages/{package_id}", response_model=PackageWithVariants)
async def get_publish_package(
    package_id: uuid.UUID, service: PlatformAdaptationDep
) -> PackageWithVariants:
    from app.models import PublishPackage

    package = await service.session.get(PublishPackage, package_id)
    if package is None:
        from app.services.errors import NotFoundError

        raise NotFoundError("PublishPackage not found")
    return PackageWithVariants(
        package=package, variants=list(await service.list_variants(package_id))
    )


@router.get("/publish-packages", response_model=list[PublishPackageRead])
async def list_publish_packages(service: PlatformAdaptationDep) -> object:
    from app.models import PublishPackage

    return (
        await service.session.scalars(
            select(PublishPackage).order_by(PublishPackage.created_at.desc()).limit(500)
        )
    ).all()


@router.patch("/platform-variants/{variant_id}", response_model=PlatformVariantRead)
async def update_platform_variant(
    variant_id: uuid.UUID, data: PlatformVariantUpdate, service: PlatformAdaptationDep
) -> object:
    return await service.update_variant(variant_id, data.model_dump(exclude_unset=True))


@router.post(
    "/platform-variants/{variant_id}/prepare-media",
    response_model=VariantMediaPrepareResponse,
)
async def prepare_platform_variant_media(
    variant_id: uuid.UUID,
    service: PlatformVariantMediaDep,
) -> VariantMediaPrepareResponse:
    variant, derivative = await service.prepare_tiktok_derivative(variant_id)
    if derivative is None:
        return VariantMediaPrepareResponse(variant=variant, queued=False)
    if derivative.render_task_id:
        return VariantMediaPrepareResponse(
            variant=variant, queued=False, task_id=derivative.render_task_id
        )
    from app.tasks.queue import CeleryVideoRenderTaskQueue

    assert derivative.render_fingerprint is not None
    task_id = CeleryVideoRenderTaskQueue().enqueue_platform_variant(
        derivative.id, derivative.render_fingerprint, variant.id
    )
    derivative.render_task_id = task_id
    await service.session.commit()
    return VariantMediaPrepareResponse(variant=variant, queued=True, task_id=task_id)


@router.post(
    "/platform-accounts", response_model=PlatformAccountRead, status_code=status.HTTP_201_CREATED
)
async def create_platform_account(
    data: PlatformAccountCreate, service: PlatformAccountDep
) -> object:
    return await service.create(data)


@router.get("/platform-accounts", response_model=list[PlatformAccountRead])
async def list_platform_accounts(
    service: PlatformAccountDep,
    project_id: uuid.UUID | None = None,
    platform: PublishingPlatform | None = None,
) -> object:
    return await service.list(project_id=project_id, platform=platform)


@router.patch("/platform-accounts/{account_id}", response_model=PlatformAccountRead)
async def update_platform_account(
    account_id: uuid.UUID, data: PlatformAccountUpdate, service: PlatformAccountDep
) -> object:
    return await service.update(account_id, data)


@router.post("/platform-variants/{variant_id}/validate", response_model=PlatformValidationResult)
async def validate_variant(
    variant_id: uuid.UUID,
    account_id: uuid.UUID,
    accounts: PlatformAccountDep,
    adaptation: PlatformAdaptationDep,
    validation: PublishingValidationDep,
) -> object:
    from app.models import PlatformVariant
    from app.services.errors import NotFoundError

    variant = await adaptation.session.get(PlatformVariant, variant_id)
    if variant is None:
        raise NotFoundError("PlatformVariant not found")
    return await validation.validate(variant, await accounts.get(account_id))


@router.post(
    "/publications/batch",
    response_model=PublicationBatchResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_publications(
    data: PublicationBatchCreate,
    publications: PublicationDep,
    accounts: PlatformAccountDep,
    adaptation: PlatformAdaptationDep,
    validation: PublishingValidationDep,
    queue: PublicationQueueDep,
) -> PublicationBatchResponse:
    from app.models import PlatformVariant
    from app.services.errors import NotFoundError

    created = []
    reports = []
    for item in data.items:
        variant = await adaptation.session.get(PlatformVariant, item.platform_variant_id)
        if variant is None:
            raise NotFoundError("PlatformVariant not found")
        report = await validation.validate(variant, await accounts.get(item.platform_account_id))
        reports.append(report)
        if not report.ready:
            publication = await publications.create(item)
            issue = report.issues[0]
            publication = await publications.fail_preflight(
                publication.id,
                code=issue.code,
                message="; ".join(problem.message for problem in report.issues),
            )
            created.append(publication)
            continue
        publication = await publications.create(item)
        if publication.status == PublicationStatus.QUEUED and publication.task_id is None:
            task_id = queue.enqueue(publication.id)
            await publications.mark_task_enqueued(publication.id, task_id)
            publication = await publications.get(publication.id)
        created.append(publication)
    return PublicationBatchResponse(publications=created, validation=reports)


@router.get("/publications", response_model=list[PublicationRead])
async def list_publications(
    service: PublicationDep,
    status_filter: PublicationStatus | None = None,
    package_id: uuid.UUID | None = None,
    limit: int = 100,
) -> object:
    return await service.list(status=status_filter, package_id=package_id, limit=limit)


@router.get("/publications/{publication_id}", response_model=PublicationRead)
async def get_publication(publication_id: uuid.UUID, service: PublicationDep) -> object:
    return await service.get(publication_id)


@router.get("/publications/{publication_id}/detail", response_model=PublicationDetail)
async def get_publication_detail(
    publication_id: uuid.UUID, service: PublicationDep
) -> PublicationDetail:
    from app.models import PublicationAttempt, PublicationEvent

    publication = await service.get(publication_id)
    attempts = list(
        await service.session.scalars(
            select(PublicationAttempt)
            .where(PublicationAttempt.publication_id == publication_id)
            .order_by(PublicationAttempt.attempt_number)
        )
    )
    events = list(
        await service.session.scalars(
            select(PublicationEvent)
            .where(PublicationEvent.publication_id == publication_id)
            .order_by(PublicationEvent.created_at)
        )
    )
    return PublicationDetail(publication=publication, attempts=attempts, events=events)


@router.patch("/publications/{publication_id}/content", response_model=PublicationRead)
async def update_publication_content(
    publication_id: uuid.UUID,
    data: PlatformVariantUpdate,
    service: PublicationDep,
) -> object:
    return await service.update_scheduled_content(
        publication_id, data.model_dump(exclude_unset=True)
    )


@router.post("/publications/{publication_id}/schedule", response_model=PublicationRead)
async def schedule_publication(
    publication_id: uuid.UUID, data: PublicationReschedule, service: PublicationDep
) -> object:
    return await service.schedule(publication_id, data.scheduled_at)


@router.post("/publications/{publication_id}/publish-now", response_model=PublicationRead)
async def publish_now(
    publication_id: uuid.UUID, service: PublicationDep, queue: PublicationQueueDep
) -> object:
    publication, should_queue = await service.publish_now(publication_id)
    if should_queue:
        task_id = queue.enqueue(publication.id)
        await service.mark_task_enqueued(publication.id, task_id)
        publication = await service.get(publication.id)
    return publication


@router.post("/publications/{publication_id}/cancel", response_model=PublicationRead)
async def cancel_publication(publication_id: uuid.UUID, service: PublicationDep) -> object:
    return await service.cancel(publication_id)


@router.post("/publications/{publication_id}/retry", response_model=PublicationRead)
async def retry_publication(
    publication_id: uuid.UUID, service: PublicationDep, queue: PublicationQueueDep
) -> object:
    publication, should_queue = await service.manual_retry(publication_id)
    if should_queue:
        task_id = queue.enqueue(publication.id)
        await service.mark_task_enqueued(publication.id, task_id)
        publication = await service.get(publication.id)
    return publication
