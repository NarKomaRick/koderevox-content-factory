import difflib
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import AIProvider
from app.models import ProductionProject, ScriptVersion
from app.models.enums import ProductionStatus, ScriptSource
from app.schemas.production import ScriptGeneration, ScriptVersionCreate
from app.services.errors import InvalidStateError, NotFoundError
from app.services.production_projects import ProductionContextBuilder


class ScriptVersionService:
    def __init__(self, session: AsyncSession, ai_provider: AIProvider | None = None) -> None:
        self.session = session
        self.ai = ai_provider

    async def create(
        self, production_project_id: uuid.UUID, data: ScriptVersionCreate
    ) -> ScriptVersion:
        production = await self._project(production_project_id)
        previous = (
            await self.session.get(ScriptVersion, production.current_script_version_id)
            if production.current_script_version_id
            else None
        )
        number = (
            int(
                await self.session.scalar(
                    select(func.max(ScriptVersion.version_number)).where(
                        ScriptVersion.production_project_id == production_project_id
                    )
                )
                or 0
            )
            + 1
        )
        sections = data.structured_sections or self._sections(data.content)
        version = ScriptVersion(
            production_project_id=production_project_id,
            version_number=number,
            content=data.content.strip(),
            structured_sections=sections,
            source=data.source,
            user_instruction=data.user_instruction,
            diff=self.diff(previous.content if previous else "", data.content),
        )
        self.session.add(version)
        await self.session.flush()
        production.current_script_version_id = version.id
        production.status = ProductionStatus.SCRIPTING
        await self.session.commit()
        await self.session.refresh(version)
        return version

    async def generate_v1(self, production_project_id: uuid.UUID) -> ScriptVersion:
        production = await self._project(production_project_id)
        if production.current_script_version_id:
            return await self.get(production.current_script_version_id)
        if self.ai is None:
            raise InvalidStateError("AI provider is required to generate a script")
        context = await ProductionContextBuilder(self.session).build(production_project_id)
        result = await self.ai.generate_structured(
            system_prompt=(
                "Create a concise Russian technical video script. Confirmed facts may be stated "
                "as facts; proposed_not_factual items must be framed as suggestions or omitted."
            ),
            user_prompt=f"PRODUCTION_CONTEXT={context}",
            response_model=ScriptGeneration,
        )
        return await self.create(
            production_project_id,
            ScriptVersionCreate(
                content=result.content,
                structured_sections=result.sections,
                source=ScriptSource.AI,
            ),
        )

    async def edit(self, production_project_id: uuid.UUID, instruction: str) -> ScriptVersion:
        production = await self._project(production_project_id)
        if not production.current_script_version_id:
            raise InvalidStateError("Generate a script before editing it")
        current = await self.get(production.current_script_version_id)
        if self.ai is None:
            raise InvalidStateError("AI provider is required to edit a script")
        context = await ProductionContextBuilder(self.session).build(production_project_id)
        result = await self.ai.generate_structured(
            system_prompt=(
                "Edit the supplied script following only the user instruction. Preserve factual "
                "meaning and never promote proposed facts to confirmed facts. Return full script."
            ),
            user_prompt=(
                f"CURRENT_SCRIPT:\n{current.content}\n\nUSER_INSTRUCTION:\n{instruction}\n\n"
                f"SAFE_CONTEXT={context}"
            ),
            response_model=ScriptGeneration,
        )
        return await self.create(
            production_project_id,
            ScriptVersionCreate(
                content=result.content,
                structured_sections=result.sections,
                source=ScriptSource.AI_EDITED,
                user_instruction=instruction,
            ),
        )

    async def approve(self, script_version_id: uuid.UUID) -> ScriptVersion:
        version = await self.get(script_version_id)
        production = await self._project(version.production_project_id)
        version.approved_at = datetime.now(UTC)
        production.approved_script_version_id = version.id
        production.current_script_version_id = version.id
        production.status = ProductionStatus.READY_FOR_VOICEOVER
        await self.session.commit()
        await self.session.refresh(version)
        return version

    async def select(self, script_version_id: uuid.UUID) -> ScriptVersion:
        version = await self.get(script_version_id)
        production = await self._project(version.production_project_id)
        production.current_script_version_id = version.id
        production.status = ProductionStatus.SCRIPTING
        await self.session.commit()
        return version

    async def history(self, production_project_id: uuid.UUID) -> list[ScriptVersion]:
        return list(
            (
                await self.session.scalars(
                    select(ScriptVersion)
                    .where(ScriptVersion.production_project_id == production_project_id)
                    .order_by(ScriptVersion.version_number)
                )
            ).all()
        )

    async def get(self, script_version_id: uuid.UUID) -> ScriptVersion:
        version = await self.session.get(ScriptVersion, script_version_id)
        if version is None:
            raise NotFoundError("ScriptVersion not found")
        return version

    async def _project(self, production_project_id: uuid.UUID) -> ProductionProject:
        production = await self.session.get(ProductionProject, production_project_id)
        if production is None:
            raise NotFoundError("ProductionProject not found")
        return production

    @staticmethod
    def diff(old: str, new: str) -> dict[str, object]:
        old_lines, new_lines = old.splitlines(), new.splitlines()
        changes = list(difflib.ndiff(old_lines, new_lines))
        added = [line[2:] for line in changes if line.startswith("+ ")]
        removed = [line[2:] for line in changes if line.startswith("- ")]
        ratio = difflib.SequenceMatcher(None, old, new).ratio() if old else 0.0
        summary: list[str] = []
        if added:
            summary.append(f"добавлено фрагментов: {len(added)}")
        if removed:
            summary.append(f"удалено фрагментов: {len(removed)}")
        if old and not added and not removed and ratio < 1:
            summary.append("текст изменён")
        return {
            "added": added[:20],
            "removed": removed[:20],
            "similarity": round(ratio, 4),
            "summary": summary or (["создана первая версия"] if not old else ["без изменений"]),
        }

    @staticmethod
    def _sections(content: str) -> list[dict[str, object]]:
        paragraphs = [part.strip() for part in content.split("\n") if part.strip()]
        if len(paragraphs) <= 1:
            sentences = [
                part.strip() for part in content.replace("!", ".").split(".") if part.strip()
            ]
            paragraphs = sentences or [content]
        return [
            {"id": f"section_{index}", "text": text, "order": index}
            for index, text in enumerate(paragraphs, start=1)
        ]
