from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import (
    ContentChannelProfile,
    ProducerRun,
    ProductionFact,
    ProductionProject,
    Project,
    ResearchFactSource,
    ResearchSource,
    ScriptVersion,
    User,
)
from app.models import (
    ResearchFact as ResearchFactRow,
)
from app.models.enums import ProductionFactStatus, ProductionStatus, ScriptSource
from app.producer.domain import (
    ApprovalState,
    AssetPlan,
    ContentAngle,
    ContentBrief,
    DirectorHandoffPackage,
    FactConflict,
    ProducerIntent,
    ProducerReport,
    ProducerStatus,
    ResearchFact,
    ScriptOutline,
    ScriptReview,
    TopicCandidate,
)
from app.producer.model import FakeProducerModel, ProducerModel, StructuredProducerModel
from app.producer.preferences import ProducerPreferenceResolver
from app.producer.research import (
    ControlledResearchRuntime,
    FakeResearchProvider,
    ResearchDocument,
    ResearchProvider,
    ResearchSearchResult,
    canonical_url,
    contains_prompt_injection,
)
from app.services.errors import InvalidStateError, NotFoundError


class ProducerCancelled(Exception):
    pass


class ProductionBuilder:
    """Materializes only the compact producer handoff into Phase 7 tables."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, run: ProducerRun, handoff: DirectorHandoffPackage) -> ProductionProject:
        if run.production_project_id:
            existing = await self.session.get(ProductionProject, run.production_project_id)
            if existing:
                return existing
        production = ProductionProject(
            project_id=run.project_id,
            user_id=run.user_id,
            title=handoff.brief.title,
            working_title=handoff.brief.title,
            status=ProductionStatus.SCRIPTING,
            target_format="short_video"
            if handoff.brief.platform == "youtube_shorts"
            else handoff.brief.platform,
            target_duration=handoff.brief.target_duration,
            production_context={
                "producer_run_id": str(run.id),
                "producer_handoff": handoff.model_dump(mode="json"),
                "story_intent": handoff.story_intent,
                "asset_requirements": handoff.asset_plan.model_dump(mode="json"),
            },
        )
        self.session.add(production)
        await self.session.flush()
        script = ScriptVersion(
            production_project_id=production.id,
            version_number=1,
            content=handoff.final_script.content,
            structured_sections=[
                item.model_dump(mode="json") for item in handoff.final_script.segments
            ],
            source=ScriptSource.AI,
        )
        self.session.add(script)
        await self.session.flush()
        production.current_script_version_id = script.id
        for fact in handoff.verified_facts:
            self.session.add(
                ProductionFact(
                    production_project_id=production.id,
                    text=fact.claim,
                    source_url=(
                        handoff.source_references[0].get("url")
                        if handoff.source_references
                        else None
                    ),
                    status=ProductionFactStatus.VERIFIED,
                )
            )
        run.production_project_id = production.id
        await self.session.flush()
        return production


class ProducerRuntime:
    """Resumable bounded state machine. Every artifact is committed before advancing."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
        *,
        model: ProducerModel | None = None,
        research_provider: ResearchProvider | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or Settings()
        self.model = model or FakeProducerModel()
        self.research_provider = research_provider or FakeResearchProvider()

    async def run(self, run_id: uuid.UUID) -> ProducerRun:
        run = await self.session.get(ProducerRun, run_id)
        if run is None:
            raise NotFoundError("Producer run not found")
        if run.status == ProducerStatus.COMPLETED:
            return run
        if run.status == ProducerStatus.CANCELLED:
            raise ProducerCancelled("Producer run is cancelled")
        try:
            await self._stage_understanding(run)
            await self._stage_research(run)
            await self._stage_verifying(run)
            await self._stage_angle(run)
            await self._stage_brief(run)
            await self._stage_script(run)
            await self._stage_review(run)
            if run.approval_mode and run.approval_state == ApprovalState.PENDING:
                return run
            await self._stage_assets(run)
            await self._stage_production(run)
            run.status = ProducerStatus.COMPLETED
            run.current_stage = ProducerStatus.COMPLETED
            run.completed_at = datetime.now(UTC)
            await self.session.commit()
            return run
        except ProducerCancelled:
            await self.session.rollback()
            return await self.session.get(ProducerRun, run_id)  # type: ignore[return-value]
        except Exception as exc:
            await self.session.rollback()
            failed = await self.session.get(ProducerRun, run_id)
            if failed is None:
                raise
            failed.status = ProducerStatus.FAILED
            failed.error = str(exc)[:2000]
            failed.errors = [
                *failed.errors,
                {"stage": failed.current_stage, "error": str(exc)[:2000]},
            ]
            await self.session.commit()
            return failed

    async def approve(self, run_id: uuid.UUID) -> ProducerRun:
        run = await self._get(run_id)
        if not run.approval_mode or run.approval_state != ApprovalState.PENDING:
            raise InvalidStateError("This Producer run is not waiting for script approval")
        run.approval_state = ApprovalState.APPROVED
        run.status = ProducerStatus.PLANNING_ASSETS
        run.current_stage = ProducerStatus.PLANNING_ASSETS
        await self.session.commit()
        return run

    async def cancel(self, run_id: uuid.UUID) -> ProducerRun:
        run = await self._get(run_id)
        if run.status in {
            ProducerStatus.COMPLETED,
            ProducerStatus.FAILED,
            ProducerStatus.CANCELLED,
        }:
            return run
        run.status = ProducerStatus.CANCELLED
        run.current_stage = ProducerStatus.CANCELLED
        run.cancelled_at = datetime.now(UTC)
        await self.session.commit()
        return run

    async def resume(self, run_id: uuid.UUID) -> ProducerRun:
        run = await self._get(run_id)
        if run.status == ProducerStatus.COMPLETED:
            return run
        if run.status == ProducerStatus.CANCELLED:
            run.status = ProducerStatus.CREATED
            run.current_stage = ProducerStatus.CREATED
            run.cancelled_at = None
        elif run.status == ProducerStatus.FAILED:
            run.status = ProducerStatus(run.current_stage)
        await self.session.commit()
        return await self.run(run.id)

    async def _stage_understanding(self, run: ProducerRun) -> None:
        if "intent" in run.artifacts:
            return
        await self._enter(run, ProducerStatus.UNDERSTANDING_GOAL)
        project = await self.session.get(Project, run.project_id)
        profile = await self._channel_profile(run, project)
        preferences = await ProducerPreferenceResolver(self.session).resolve(
            project_id=run.project_id,
            user_id=run.user_id,
            platform=run.platform,
        )
        defaults = {
            "audience": preferences.get("audience", profile.get("audience", "")),
            "platform": run.platform,
            "target_duration": run.target_duration
            or profile.get("preferred_duration")
            or self._platform_duration(run.platform),
            "tone": preferences.get("tone")
            or run.tone
            or profile.get("tone")
            or "clear, useful, conversational",
            "research_mode": run.research_mode,
            "approval_mode": run.approval_mode,
            "language": project.language if project else "ru",
        }
        intent = await self._call(run, self.model.understand, run.raw_prompt, defaults)
        run.artifacts = {
            **run.artifacts,
            "intent": intent.model_dump(mode="json"),
            "channel_profile": profile,
            "preferences": preferences,
            "brand_profile": {
                "brand_context": project.brand_context if project else "",
                "target_audience": project.target_audience if project else "",
                "brand_preset": project.brand_preset if project else {},
            },
            "output_profile": {
                "platform": run.platform,
                "duration": defaults["target_duration"],
            },
        }
        await self._commit(run, ProducerStatus.UNDERSTANDING_GOAL)

    async def _stage_research(self, run: ProducerRun) -> None:
        if "research_documents" in run.artifacts:
            return
        await self._enter(run, ProducerStatus.RESEARCHING)
        intent = ProducerIntent.model_validate(run.artifacts["intent"])
        plan = await self._call(run, self.model.plan_research, intent)
        if intent.research_mode.value == "none":
            documents: list[ResearchDocument] = []
        else:
            controlled = ControlledResearchRuntime(self.research_provider, self.settings)
            results = await controlled.search(plan.queries)
            known_urls = {canonical_url(item.url) for item in results}
            for url in plan.source_urls[: self.settings.producer_max_sources]:
                if canonical_url(url) not in known_urls:
                    results.append(ResearchSearchResult(url=url, title=url))
                    known_urls.add(canonical_url(url))
            documents = []
            for result in results:
                try:
                    documents.append(await controlled.fetch(result.url))
                except Exception as exc:
                    run.errors = [
                        *run.errors,
                        {"stage": "researching", "url": result.url, "error": str(exc)[:500]},
                    ]
            run.search_query_count = controlled.search_count
            run.source_count = len(documents)
            run.fetch_count = controlled.fetch_count
        source_refs: list[dict[str, Any]] = []
        for document in documents:
            source = await self._upsert_source(run, document, intent)
            source_refs.append(
                {
                    "id": str(source.id),
                    "url": source.canonical_url,
                    "title": source.title,
                    "stale": source.stale,
                    "untrusted": True,
                }
            )
        run.artifacts = {
            **run.artifacts,
            "research_plan": plan.model_dump(mode="json"),
            "research_documents": [
                {
                    "url": item.final_url,
                    "title": item.title,
                    "text": item.text[:20_000],
                    "published_at": item.published_at.isoformat() if item.published_at else None,
                }
                for item in documents
            ],
            "source_references": source_refs,
        }
        await self._commit(run, ProducerStatus.RESEARCHING)

    async def _stage_verifying(self, run: ProducerRun) -> None:
        if "facts" in run.artifacts:
            return
        await self._enter(run, ProducerStatus.VERIFYING)
        intent = ProducerIntent.model_validate(run.artifacts["intent"])
        documents = [
            ResearchDocument(
                requested_url=item["url"],
                final_url=item["url"],
                title=item["title"],
                text=item["text"],
                published_at=datetime.fromisoformat(item["published_at"])
                if item.get("published_at")
                else None,
            )
            for item in run.artifacts.get("research_documents", [])
        ]
        facts = await self._call(run, self.model.extract_facts, intent, documents)
        source_ids = [
            uuid.UUID(item["id"])
            for item in run.artifacts.get("source_references", [])
            if item.get("id")
        ]
        source_rows = (
            list(
                (
                    await self.session.scalars(
                        select(ResearchSource).where(ResearchSource.id.in_(source_ids))
                    )
                ).all()
            )
            if source_ids
            else []
        )
        for fact in facts:
            fact.source_ids = [
                row.id
                for row in source_rows
                if set(_tokens(fact.claim)) & set(_tokens(row.extracted_text))
            ]
            if not fact.source_ids and source_rows:
                fact.source_ids = [source_rows[0].id]
            for row in source_rows:
                if row.stale and fact.time_sensitive:
                    fact.stale = True
        conflicts = self._conflicts(facts)
        for conflict in conflicts:
            for fact in facts:
                if fact.id in conflict.fact_ids:
                    fact.conflict_group = str(conflict.fact_ids[0])
        for fact in facts:
            fact_row = ResearchFactRow(
                run_id=run.id,
                claim=fact.claim,
                normalized_claim=fact.normalized_claim,
                confidence=fact.confidence,
                status="verified" if fact.verified and not fact.stale else "stale",
                critical=fact.critical,
                time_sensitive=fact.time_sensitive,
                stale=fact.stale,
                conflict_group=fact.conflict_group,
                provenance_json={"source_ids": [str(item) for item in fact.source_ids]},
            )
            self.session.add(fact_row)
            await self.session.flush()
            for source_id in fact.source_ids:
                self.session.add(ResearchFactSource(fact_id=fact_row.id, source_id=source_id))
        run.artifacts = {
            **run.artifacts,
            "facts": [item.model_dump(mode="json") for item in facts],
            "conflicts": [item.model_dump(mode="json") for item in conflicts],
        }
        await self._commit(run, ProducerStatus.VERIFYING)

    async def _stage_angle(self, run: ProducerRun) -> None:
        if "angle" in run.artifacts:
            return
        await self._enter(run, ProducerStatus.PLANNING_ANGLE)
        intent = ProducerIntent.model_validate(run.artifacts["intent"])
        topic = intent.topic or intent.raw_prompt
        candidates = [
            TopicCandidate(
                title=f"{topic}: что ломает интеграцию",
                core_message="Изолируйте нестабильную интеграцию за стабильным backend-контрактом.",
                rationale="cause → consequence → solution",
                score=0.9,
            ),
            TopicCandidate(
                title=f"{topic}: защита от дублей",
                core_message="Идемпотентность делает повтор запроса безопасным.",
                score=0.78,
            ),
            TopicCandidate(
                title=f"{topic}: проверяемые факты",
                core_message="Архитектурное решение должно опираться на проверяемые источники.",
                score=0.7,
            ),
        ]
        history = await self._content_history(run)
        angle = await self._call(
            run,
            self.model.choose_angle,
            intent,
            candidates[: self.settings.producer_max_angle_candidates],
            history,
        )
        if angle.duplicate:
            raise InvalidStateError("No non-duplicate content angle is available")
        run.artifacts = {
            **run.artifacts,
            "topic_candidates": [item.model_dump(mode="json") for item in candidates],
            "angle": angle.model_dump(mode="json"),
        }
        await self._commit(run, ProducerStatus.PLANNING_ANGLE)

    async def _stage_brief(self, run: ProducerRun) -> None:
        if "brief" in run.artifacts:
            return
        await self._enter(run, ProducerStatus.BUILDING_BRIEF)
        intent = ProducerIntent.model_validate(run.artifacts["intent"])
        angle = ContentAngle.model_validate(run.artifacts["angle"])
        facts = [ResearchFact.model_validate(item) for item in run.artifacts.get("facts", [])]
        brief = await self._call(run, self.model.build_brief, intent, angle, facts)
        run.artifacts = {**run.artifacts, "brief": brief.model_dump(mode="json")}
        await self._commit(run, ProducerStatus.BUILDING_BRIEF)

    async def _stage_script(self, run: ProducerRun) -> None:
        if "script" in run.artifacts:
            return
        await self._enter(run, ProducerStatus.WRITING_SCRIPT)
        brief = ContentBrief.model_validate(run.artifacts["brief"])
        facts = [ResearchFact.model_validate(item) for item in run.artifacts.get("facts", [])]
        script = await self._call(run, self.model.write_script, brief, facts)
        run.artifacts = {**run.artifacts, "script": script.model_dump(mode="json")}
        await self._commit(run, ProducerStatus.WRITING_SCRIPT)

    async def _stage_review(self, run: ProducerRun) -> None:
        if "review" in run.artifacts and run.approval_state != ApprovalState.PENDING:
            return
        await self._enter(run, ProducerStatus.REVIEWING_SCRIPT)
        brief = ContentBrief.model_validate(run.artifacts["brief"])
        script = ScriptOutline.model_validate(run.artifacts["script"])
        facts = [ResearchFact.model_validate(item) for item in run.artifacts.get("facts", [])]
        review = await self._call(
            run, self.model.review_script, script, facts, brief.target_duration
        )
        if (
            not review.passed
            and run.script_iterations < self.settings.producer_max_script_iterations
        ):
            run.script_iterations += 1
            script = await self._call(run, self.model.revise_script, script, review, facts)
            review = await self._call(
                run, self.model.review_script, script, facts, brief.target_duration
            )
            run.artifacts = {**run.artifacts, "script": script.model_dump(mode="json")}
        if self.settings.producer_strict_factuality:
            blocking = [item for item in review.unsupported_claims]
            blocking.extend(
                item.claim
                for item in facts
                if item.critical and (item.stale or item.conflict_group)
            )
            if blocking:
                review.passed = False
                review.issues = [*review.issues, "strict factuality blocked completion"]
        run.artifacts = {**run.artifacts, "review": review.model_dump(mode="json")}
        if not review.passed:
            raise InvalidStateError("Script review failed: " + "; ".join(review.issues))
        if run.approval_mode and run.approval_state == ApprovalState.NOT_REQUIRED:
            run.approval_state = ApprovalState.PENDING
        await self._commit(run, ProducerStatus.REVIEWING_SCRIPT)

    async def _stage_assets(self, run: ProducerRun) -> None:
        if "asset_plan" in run.artifacts:
            return
        await self._enter(run, ProducerStatus.PLANNING_ASSETS)
        brief = ContentBrief.model_validate(run.artifacts["brief"])
        script = ScriptOutline.model_validate(run.artifacts["script"])
        plan = await self._call(run, self.model.plan_assets, brief, script)
        run.artifacts = {**run.artifacts, "asset_plan": plan.model_dump(mode="json")}
        await self._commit(run, ProducerStatus.PLANNING_ASSETS)

    async def _stage_production(self, run: ProducerRun) -> None:
        if run.production_project_id:
            return
        await self._enter(run, ProducerStatus.CREATING_PRODUCTION)
        handoff = self._handoff(run)
        await ProductionBuilder(self.session).create(run, handoff)
        run.artifacts = {**run.artifacts, "handoff": handoff.model_dump(mode="json")}
        await self._commit(run, ProducerStatus.CREATING_PRODUCTION)

    async def _upsert_source(
        self, run: ProducerRun, document: ResearchDocument, intent: ProducerIntent
    ) -> ResearchSource:
        key = canonical_url(document.final_url)
        existing = await self.session.scalar(
            select(ResearchSource).where(ResearchSource.canonical_url == key)
        )
        if existing:
            return existing
        existing = await self.session.scalar(
            select(ResearchSource).where(
                ResearchSource.content_hash == document.content_hash,
                ResearchSource.extractor_version
                == self.settings.producer_research_extractor_version,
            )
        )
        if existing:
            return existing
        candidates = (await self.session.scalars(select(ResearchSource).limit(100))).all()
        document_tokens = set(_tokens(document.text))
        for candidate in candidates:
            candidate_tokens = set(_tokens(candidate.extracted_text))
            similarity = len(document_tokens & candidate_tokens) / max(
                1, len(document_tokens | candidate_tokens)
            )
            if similarity >= 0.92:
                return candidate
        injection = contains_prompt_injection(document.text)
        time_sensitive = any(
            token in (intent.topic or "").casefold() for token in ("цена", "сегодня", "текущ")
        )
        stale = ControlledResearchRuntime(self.research_provider, self.settings).mark_stale(
            document, time_sensitive=time_sensitive
        )
        row = ResearchSource(
            run_id=run.id,
            canonical_url=key,
            final_url=document.final_url,
            title=document.title[:1000],
            content_hash=document.content_hash,
            extractor_version=self.settings.producer_research_extractor_version,
            content_type=document.content_type,
            extracted_text=document.text[:100_000],
            metadata_json={"untrusted": True, "prompt_injection_detected": injection},
            published_at=document.published_at,
            retrieved_at=document.retrieved_at,
            time_sensitive=time_sensitive,
            stale=stale,
            prompt_injection_detected=injection,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def _channel_profile(self, run: ProducerRun, project: Project | None) -> dict[str, Any]:
        profile = await self.session.scalar(
            select(ContentChannelProfile).where(
                ContentChannelProfile.project_id == run.project_id,
                ContentChannelProfile.platform == run.platform,
            )
        )
        if profile:
            return {
                "audience": profile.audience,
                "tone": profile.tone,
                "content_pillars": profile.content_pillars,
                "preferred_duration": profile.preferred_duration,
                "cta_strategy": profile.cta_strategy,
                "taboo_topics": profile.taboo_topics,
                "brand_voice": profile.brand_voice,
            }
        return {
            "audience": project.target_audience if project else "",
            "tone": (project.brand_preset or {}).get("tone", "") if project else "",
            "preferred_duration": None,
            "brand_voice": project.brand_context if project else "",
        }

    async def _content_history(self, run: ProducerRun) -> list[str]:
        rows = (
            await self.session.scalars(
                select(ProducerRun)
                .where(ProducerRun.project_id == run.project_id, ProducerRun.id != run.id)
                .order_by(ProducerRun.created_at.desc())
                .limit(50)
            )
        ).all()
        history = []
        for row in rows:
            angle = row.artifacts.get("angle", {})
            history.extend(
                [str(angle.get("core_message", "")), str(angle.get("title", "")), row.raw_prompt]
            )
        projects = (
            await self.session.scalars(
                select(ProductionProject)
                .where(ProductionProject.project_id == run.project_id)
                .limit(50)
            )
        ).all()
        history.extend(item.title for item in projects)
        return [item for item in history if item]

    def _handoff(self, run: ProducerRun) -> DirectorHandoffPackage:
        return DirectorHandoffPackage(
            brief=ContentBrief.model_validate(run.artifacts["brief"]),
            final_script=ScriptOutline.model_validate(run.artifacts["script"]),
            verified_facts=[
                ResearchFact.model_validate(item)
                for item in run.artifacts.get("facts", [])
                if item.get("verified") and not item.get("stale") and not item.get("conflict_group")
            ],
            story_intent={
                "topic": run.artifacts.get("intent", {}).get("topic"),
                "angle": run.artifacts.get("angle", {}),
                "core_message": run.artifacts.get("angle", {}).get("core_message", ""),
            },
            asset_plan=AssetPlan.model_validate(run.artifacts["asset_plan"]),
            brand_profile=run.artifacts.get("brand_profile", {}),
            channel_profile=run.artifacts.get("channel_profile", {}),
            output_profile=run.artifacts.get(
                "output_profile", {"platform": run.platform, "duration": run.target_duration}
            ),
            source_references=run.artifacts.get("source_references", []),
        )

    async def _get(self, run_id: uuid.UUID) -> ProducerRun:
        run = await self.session.get(ProducerRun, run_id)
        if run is None:
            raise NotFoundError("Producer run not found")
        return run

    async def _enter(self, run: ProducerRun, status: ProducerStatus) -> None:
        if run.status == ProducerStatus.CANCELLED:
            raise ProducerCancelled("Producer run cancelled")
        if run.step_count >= self.settings.producer_max_steps:
            raise InvalidStateError("Producer step limit reached")
        run.step_count += 1
        run.status = status
        run.current_stage = status
        await self.session.flush()

    async def _commit(self, run: ProducerRun, status: ProducerStatus) -> None:
        run.status = status
        run.current_stage = status
        await self.session.commit()

    async def _call(self, run: ProducerRun, function: Any, *args: Any) -> Any:
        if (
            run.llm_call_count >= self.settings.producer_max_llm_calls
            and type(self.model) is not FakeProducerModel
        ):
            raise InvalidStateError("Producer LLM call limit reached")
        if type(self.model) is not FakeProducerModel:
            run.llm_call_count += 1
        return await function(*args)

    @staticmethod
    def _platform_duration(platform: str) -> float:
        return 45.0 if platform == "youtube_shorts" else 60.0

    @staticmethod
    def _conflicts(facts: list[ResearchFact]) -> list[FactConflict]:
        groups: list[FactConflict] = []
        for left in facts:
            for right in facts:
                if (
                    left.id >= right.id
                    or "кэш" not in left.claim.casefold()
                    or "кэш" not in right.claim.casefold()
                ):
                    continue
                if ("всегда" in left.claim.casefold()) != ("всегда" in right.claim.casefold()):
                    groups.append(
                        FactConflict(
                            fact_ids=[left.id, right.id],
                            claims=[left.claim, right.claim],
                            critical=True,
                        )
                    )
        return groups


class ProducerService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or Settings()

    async def create(self, data: Any) -> ProducerRun:
        if data.idempotency_key:
            existing = await self.session.scalar(
                select(ProducerRun).where(ProducerRun.idempotency_key == data.idempotency_key)
            )
            if existing:
                return existing
        user = (
            await self.session.get(User, data.user_id)
            if data.user_id
            else await self.session.scalar(
                select(User).where(User.telegram_id == data.telegram_user_id)
            )
        )
        if user is None:
            raise NotFoundError("User not found")
        project = (
            await self.session.get(Project, data.project_id)
            if data.project_id
            else await self.session.scalar(select(Project).order_by(Project.created_at))
        )
        if project is None:
            raise NotFoundError("Project not found")
        profile = await self.session.scalar(
            select(ContentChannelProfile).where(
                ContentChannelProfile.project_id == project.id,
                ContentChannelProfile.platform == data.platform,
            )
        )
        duration = data.duration or (
            profile.preferred_duration
            if profile and profile.preferred_duration
            else (45.0 if data.platform == "youtube_shorts" else 60.0)
        )
        tone = data.tone or (
            profile.tone if profile and profile.tone else project.brand_context[:255]
        )
        run = ProducerRun(
            project_id=project.id,
            user_id=user.id,
            raw_prompt=data.prompt.strip(),
            platform=data.platform,
            target_duration=duration,
            tone=tone,
            research_mode=data.research_mode.value,
            approval_mode=data.approval_mode,
            approval_state=ApprovalState.PENDING
            if data.approval_mode
            else ApprovalState.NOT_REQUIRED,
            status=ProducerStatus.CREATED,
            current_stage=ProducerStatus.CREATED,
            idempotency_key=data.idempotency_key,
        )
        self.session.add(run)
        await self.session.commit()
        await self.session.refresh(run)
        return run

    async def get(self, run_id: uuid.UUID) -> ProducerRun:
        run = await self.session.get(ProducerRun, run_id)
        if run is None:
            raise NotFoundError("Producer run not found")
        return run

    async def report(self, run_id: uuid.UUID) -> ProducerReport:
        run = await self.get(run_id)
        artifacts = run.artifacts
        return ProducerReport(
            run_id=run.id,
            status=ProducerStatus(run.status),
            current_stage=ProducerStatus(run.current_stage),
            approval_state=ApprovalState(run.approval_state),
            topic=artifacts.get("intent", {}).get("topic"),
            facts=[ResearchFact.model_validate(item) for item in artifacts.get("facts", [])],
            conflicts=[
                FactConflict.model_validate(item) for item in artifacts.get("conflicts", [])
            ],
            brief=ContentBrief.model_validate(artifacts["brief"])
            if artifacts.get("brief")
            else None,
            script=ScriptOutline.model_validate(artifacts["script"])
            if artifacts.get("script")
            else None,
            review=ScriptReview.model_validate(artifacts["review"])
            if artifacts.get("review")
            else None,
            asset_plan=AssetPlan.model_validate(artifacts["asset_plan"])
            if artifacts.get("asset_plan")
            else None,
            handoff=DirectorHandoffPackage.model_validate(artifacts["handoff"])
            if artifacts.get("handoff")
            else None,
            production_project_id=run.production_project_id,
            error=run.error,
            created_at=run.created_at,
            completed_at=run.completed_at,
        )

    async def cancel(self, run_id: uuid.UUID) -> ProducerRun:
        return await ProducerRuntime(self.session, self.settings).cancel(run_id)

    async def resume(self, run_id: uuid.UUID) -> ProducerRun:
        return await ProducerRuntime(self.session, self.settings).resume(run_id)

    async def approve(self, run_id: uuid.UUID) -> ProducerRun:
        return await ProducerRuntime(self.session, self.settings).approve(run_id)


def create_producer_model(settings: Settings, provider: Any | None = None) -> ProducerModel:
    if settings.ai_provider == "mock" or provider is None:
        return FakeProducerModel()
    return StructuredProducerModel(provider, settings)


def _tokens(value: str) -> list[str]:
    return [item for item in re.findall(r"[\w-]+", value.casefold()) if len(item) > 3]
