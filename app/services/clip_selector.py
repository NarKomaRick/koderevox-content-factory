from dataclasses import dataclass
from typing import Protocol

import structlog

from app.ai.base import AIProvider
from app.ai.prompts.system import build_system_prompt
from app.ai.prompts.video_editing import build_edit_plan_prompt, build_video_concepts_prompt
from app.models import ContentDraft, Project, SourceItem
from app.schemas.video import EditPlan, VideoConcept, VideoConceptBatch
from app.services.edit_plan import EditPlanValidator
from app.services.errors import InvalidStateError

logger = structlog.get_logger()


@dataclass(frozen=True)
class SelectedEditPlan:
    plan: EditPlan
    attempts: int


class ClipSelector(Protocol):
    async def concepts(
        self, source: SourceItem, brand: Project, draft: ContentDraft | None = None
    ) -> VideoConceptBatch: ...

    async def edit_plan(
        self,
        source: SourceItem,
        brand: Project,
        concept: VideoConcept,
        validator: EditPlanValidator,
        *,
        current_plan: EditPlan | None = None,
        instruction: str | None = None,
    ) -> SelectedEditPlan: ...


class LLMClipSelector:
    def __init__(self, ai_provider: AIProvider, validation_attempts: int = 3) -> None:
        self.ai = ai_provider
        self.validation_attempts = validation_attempts

    async def concepts(
        self, source: SourceItem, brand: Project, draft: ContentDraft | None = None
    ) -> VideoConceptBatch:
        return await self.ai.generate_structured(
            system_prompt=build_system_prompt(brand),
            user_prompt=build_video_concepts_prompt(source, draft),
            response_model=VideoConceptBatch,
        )

    async def edit_plan(
        self,
        source: SourceItem,
        brand: Project,
        concept: VideoConcept,
        validator: EditPlanValidator,
        *,
        current_plan: EditPlan | None = None,
        instruction: str | None = None,
    ) -> SelectedEditPlan:
        validation_error: str | None = None
        for attempt in range(self.validation_attempts):
            proposal = await self.ai.generate_structured(
                system_prompt=build_system_prompt(brand),
                user_prompt=build_edit_plan_prompt(
                    source,
                    concept,
                    current_plan=current_plan,
                    instruction=instruction,
                    validation_error=validation_error,
                ),
                response_model=EditPlan,
            )
            try:
                validated = validator.validate(
                    proposal,
                    source_duration=float(source.duration_seconds or 0),
                    transcript_segments=source.transcript_segments,
                    require_speech_boundaries=True,
                )
                return SelectedEditPlan(validated, attempt + 1)
            except InvalidStateError as exc:
                validation_error = str(exc)
                await logger.awarning(
                    "edit_plan_validation_failed",
                    source_id=str(source.id),
                    attempt=attempt + 1,
                    reason=validation_error,
                )
        raise InvalidStateError(f"Invalid edit plan: {validation_error}")
