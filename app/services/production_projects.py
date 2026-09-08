import builtins
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ProductionFact,
    ProductionMaterial,
    ProductionProject,
    Project,
    ScriptVersion,
    SourceItem,
    SourceNote,
    User,
    VisualAsset,
)
from app.models.enums import (
    AssetType,
    ProductionFactStatus,
    ProductionMaterialRole,
    ProductionStatus,
)
from app.schemas.production import FactCreate, MaterialAttach, ProductionProjectCreate
from app.services.errors import InvalidStateError, NotFoundError


class ProductionProjectService:
    """Owns the durable one-video workspace; Telegram FSM is only a navigation aid."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, data: ProductionProjectCreate) -> ProductionProject:
        project = await self.session.get(Project, data.project_id)
        user = await self.session.get(User, data.user_id)
        if project is None or user is None:
            raise NotFoundError("Project or user not found")
        if data.initial_source_item_id:
            source = await self.session.get(SourceItem, data.initial_source_item_id)
            if (
                source is None
                or source.project_id != data.project_id
                or source.user_id != data.user_id
            ):
                raise InvalidStateError("Initial material belongs to another project or user")
        item = ProductionProject(
            project_id=data.project_id,
            user_id=data.user_id,
            initial_source_item_id=data.initial_source_item_id,
            title=data.title.strip(),
            working_title=data.title.strip(),
            target_format=data.target_format,
            target_duration=data.target_duration,
            production_context={"initial_idea": data.title.strip()},
            persistent_instructions=[
                "technical, modern, clean, dark and minimal",
                "prefer real UI, code and footage over generated visuals",
                "avoid gaming/cyberpunk styling and excessive memes",
            ],
        )
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        if data.initial_source_item_id:
            await ProductionMaterialService(self.session).attach(
                item.id,
                MaterialAttach(
                    source_item_id=data.initial_source_item_id,
                    roles=[ProductionMaterialRole.REFERENCE],
                ),
            )
        return item

    async def get(self, production_project_id: uuid.UUID) -> ProductionProject:
        item = await self.session.get(ProductionProject, production_project_id)
        if item is None:
            raise NotFoundError("ProductionProject not found")
        return item

    async def list_for_user(self, user_id: uuid.UUID) -> Sequence[ProductionProject]:
        return (
            await self.session.scalars(
                select(ProductionProject)
                .where(ProductionProject.user_id == user_id)
                .order_by(ProductionProject.updated_at.desc())
            )
        ).all()

    async def list_for_telegram_user(self, telegram_user_id: int) -> Sequence[ProductionProject]:
        return (
            await self.session.scalars(
                select(ProductionProject)
                .join(User, User.id == ProductionProject.user_id)
                .where(User.telegram_id == telegram_user_id)
                .order_by(ProductionProject.updated_at.desc())
            )
        ).all()

    async def update(
        self, production_project_id: uuid.UUID, **changes: object
    ) -> ProductionProject:
        item = await self.get(production_project_id)
        allowed = {
            "working_title",
            "target_format",
            "target_duration",
            "production_context",
            "persistent_instructions",
        }
        for key, value in changes.items():
            if key not in allowed:
                raise InvalidStateError(f"Production field cannot be changed: {key}")
            setattr(item, key, value)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def transition(
        self, production_project_id: uuid.UUID, status: ProductionStatus
    ) -> ProductionProject:
        item = await self.get(production_project_id)
        if item.status == ProductionStatus.ARCHIVED and status != ProductionStatus.ARCHIVED:
            raise InvalidStateError("Archived production project cannot be reopened")
        if status == ProductionStatus.READY_FOR_VOICEOVER and not item.approved_script_version_id:
            raise InvalidStateError("Approve a script before requesting voiceover")
        if status in {ProductionStatus.ROUGH_CUT, ProductionStatus.REVIEW}:
            if not item.active_timeline_revision_id:
                raise InvalidStateError("A timeline is required for this state")
        if status == ProductionStatus.APPROVED and not item.active_video_project_id:
            raise InvalidStateError("A rendered VideoProject is required for approval")
        item.status = status
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def archive(self, production_project_id: uuid.UUID) -> ProductionProject:
        return await self.transition(production_project_id, ProductionStatus.ARCHIVED)


class ProductionMaterialService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def attach(
        self, production_project_id: uuid.UUID, data: MaterialAttach
    ) -> ProductionMaterial:
        production = await self.session.get(ProductionProject, production_project_id)
        if production is None:
            raise NotFoundError("ProductionProject not found")
        source = (
            await self.session.get(SourceItem, data.source_item_id) if data.source_item_id else None
        )
        asset = await self.session.get(VisualAsset, data.asset_id) if data.asset_id else None
        if source is None and asset is None:
            raise NotFoundError("Material source or asset not found")
        owner_project_id = source.project_id if source else asset.project_id  # type: ignore[union-attr]
        if owner_project_id != production.project_id:
            raise InvalidStateError("Material belongs to another brand project")
        query = select(ProductionMaterial).where(
            ProductionMaterial.production_project_id == production_project_id
        )
        if source:
            query = query.where(ProductionMaterial.source_item_id == source.id)
        elif asset:
            query = query.where(ProductionMaterial.asset_id == asset.id)
        existing = await self.session.scalar(query)
        roles = [role.value for role in data.roles] or self._infer_roles(source, asset)
        if existing:
            existing.roles = list(dict.fromkeys([*existing.roles, *roles]))
            existing.user_instruction = data.user_instruction or existing.user_instruction
            existing.is_user_locked = existing.is_user_locked or data.is_user_locked
            material = existing
        else:
            material = ProductionMaterial(
                production_project_id=production_project_id,
                source_item_id=source.id if source else None,
                asset_id=asset.id if asset else None,
                roles=roles,
                user_instruction=data.user_instruction,
                is_user_locked=data.is_user_locked,
            )
            self.session.add(material)
        await self.session.commit()
        await self.session.refresh(material)
        return material

    async def detach(self, production_project_id: uuid.UUID, material_id: uuid.UUID) -> None:
        material = await self.session.scalar(
            select(ProductionMaterial).where(
                ProductionMaterial.id == material_id,
                ProductionMaterial.production_project_id == production_project_id,
            )
        )
        if material is None:
            raise NotFoundError("Production material not found")
        await self.session.delete(material)
        await self.session.commit()

    async def list(
        self, production_project_id: uuid.UUID, *, used: bool | None = None
    ) -> Sequence[ProductionMaterial]:
        query = select(ProductionMaterial).where(
            ProductionMaterial.production_project_id == production_project_id
        )
        if used is not None:
            query = query.where(ProductionMaterial.is_used == used)
        return (await self.session.scalars(query.order_by(ProductionMaterial.created_at))).all()

    @staticmethod
    def _infer_roles(source: SourceItem | None, asset: VisualAsset | None) -> builtins.list[str]:
        if source and source.type.value in {"voice", "audio"}:
            return [ProductionMaterialRole.VOICEOVER.value]
        mapping = {
            AssetType.SCREENSHOT: ProductionMaterialRole.SCREENSHOT,
            AssetType.SCREEN_RECORDING: ProductionMaterialRole.SCREEN_RECORDING,
            AssetType.VIDEO: ProductionMaterialRole.FOOTAGE,
            AssetType.CODE: ProductionMaterialRole.CODE,
            AssetType.IMAGE: ProductionMaterialRole.IMAGE,
        }
        return [mapping.get(asset.type, ProductionMaterialRole.OTHER).value] if asset else ["other"]


class ProductionFactService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, production_project_id: uuid.UUID, data: FactCreate) -> ProductionFact:
        if await self.session.get(ProductionProject, production_project_id) is None:
            raise NotFoundError("ProductionProject not found")
        # AI suggestions remain PROPOSED. Only explicit user/provider evidence may elevate them.
        fact = ProductionFact(production_project_id=production_project_id, **data.model_dump())
        self.session.add(fact)
        await self.session.commit()
        await self.session.refresh(fact)
        return fact

    async def set_status(
        self,
        fact_id: uuid.UUID,
        status: ProductionFactStatus,
        *,
        user_confirmed: bool = False,
    ) -> ProductionFact:
        fact = await self.session.get(ProductionFact, fact_id)
        if fact is None:
            raise NotFoundError("ProductionFact not found")
        if status == ProductionFactStatus.USER_CONFIRMED and not user_confirmed:
            raise InvalidStateError("Explicit user confirmation is required")
        fact.status = status
        await self.session.commit()
        await self.session.refresh(fact)
        return fact


class ProductionContextBuilder:
    """Builds bounded, predictable LLM input instead of replaying Telegram history."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def build(self, production_project_id: uuid.UUID) -> dict[str, Any]:
        production = await self.session.get(ProductionProject, production_project_id)
        if production is None:
            raise NotFoundError("ProductionProject not found")
        materials = (
            await self.session.scalars(
                select(ProductionMaterial).where(
                    ProductionMaterial.production_project_id == production_project_id
                )
            )
        ).all()
        source_ids = [item.source_item_id for item in materials if item.source_item_id]
        sources = (
            (
                await self.session.scalars(select(SourceItem).where(SourceItem.id.in_(source_ids)))
            ).all()
            if source_ids
            else []
        )
        note_rows = (
            (
                await self.session.scalars(
                    select(SourceNote).where(SourceNote.source_item_id.in_(source_ids))
                )
            ).all()
            if source_ids
            else []
        )
        facts = (
            await self.session.scalars(
                select(ProductionFact).where(
                    ProductionFact.production_project_id == production_project_id
                )
            )
        ).all()
        scripts = (
            await self.session.scalars(
                select(ScriptVersion).where(
                    ScriptVersion.id.in_(
                        [
                            value
                            for value in (
                                production.current_script_version_id,
                                production.approved_script_version_id,
                            )
                            if value
                        ]
                    )
                )
            )
        ).all()
        assets = (
            await self.session.scalars(
                select(VisualAsset).where(
                    VisualAsset.id.in_([item.asset_id for item in materials if item.asset_id])
                )
            )
        ).all()
        context = {
            "production": {
                "id": str(production.id),
                "title": production.working_title,
                "status": production.status.value,
                "target_format": production.target_format,
                "target_duration": production.target_duration,
            },
            "initial_idea": production.production_context.get("initial_idea", production.title),
            "persistent_instructions": production.persistent_instructions,
            "sources": [
                {
                    "id": str(item.id),
                    "type": item.type.value,
                    "text": (item.original_text or item.transcript or item.extracted_text or "")[
                        :20_000
                    ],
                    "summary": item.summary,
                    "intelligence": item.content_analysis,
                }
                for item in sources
            ],
            "notes": [(item.text or item.transcript or "")[:10_000] for item in note_rows],
            "facts": {
                "confirmed": [
                    item.text
                    for item in facts
                    if item.status
                    in {ProductionFactStatus.VERIFIED, ProductionFactStatus.USER_CONFIRMED}
                ],
                "proposed_not_factual": [
                    item.text for item in facts if item.status == ProductionFactStatus.PROPOSED
                ],
            },
            "scripts": [
                {
                    "id": str(item.id),
                    "version": item.version_number,
                    "approved": item.approved_at is not None,
                    "content": item.content,
                    "sections": item.structured_sections,
                }
                for item in scripts
            ],
            "materials": [
                {
                    "id": str(item.id),
                    "asset_id": str(item.asset_id) if item.asset_id else None,
                    "roles": item.roles,
                    "instruction": item.user_instruction,
                    "used": item.is_used,
                }
                for item in materials
            ],
            "assets": [
                {
                    "id": str(item.id),
                    "type": item.type.value,
                    "title": item.title,
                    "description": item.description,
                    "tags": item.tags,
                    "extracted_text": (item.extracted_text or "")[:5_000],
                }
                for item in assets
            ],
        }
        production.production_context = {**production.production_context, "snapshot": context}
        await self.session.commit()
        return context


class AssetCandidateRetriever:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def retrieve(
        self, production_project_id: uuid.UUID, query: str, *, limit: int = 5
    ) -> list[tuple[ProductionMaterial, VisualAsset, float]]:
        rows = await self.session.execute(
            select(ProductionMaterial, VisualAsset)
            .join(VisualAsset, VisualAsset.id == ProductionMaterial.asset_id)
            .where(ProductionMaterial.production_project_id == production_project_id)
        )
        tokens = {part for part in query.casefold().split() if len(part) > 2}
        ranked: list[tuple[ProductionMaterial, VisualAsset, float]] = []
        for material, asset in rows.all():
            haystack = " ".join(
                [asset.title, asset.description, " ".join(asset.tags), asset.extracted_text or ""]
            ).casefold()
            score = sum(token in haystack for token in tokens) / max(1, len(tokens))
            score += 0.15 if not material.is_used else 0
            score += 0.1 if material.is_user_locked else 0
            ranked.append((material, asset, min(score, 1.0)))
        return sorted(ranked, key=lambda item: item[2], reverse=True)[:limit]


async def production_counts(
    session: AsyncSession, production_project_id: uuid.UUID
) -> dict[str, int]:
    total = await session.scalar(
        select(func.count())
        .select_from(ProductionMaterial)
        .where(ProductionMaterial.production_project_id == production_project_id)
    )
    used = await session.scalar(
        select(func.count())
        .select_from(ProductionMaterial)
        .where(
            ProductionMaterial.production_project_id == production_project_id,
            ProductionMaterial.is_used.is_(True),
        )
    )
    return {"total": int(total or 0), "used": int(used or 0)}
