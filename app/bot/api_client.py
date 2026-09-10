from datetime import datetime
from typing import Any

import httpx


class BackendClient:
    def __init__(self, base_url: str, timeout: float = 180) -> None:
        self.client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)

    async def close(self) -> None:
        await self.client.aclose()

    async def create_producer_run(
        self, *, telegram_user_id: int, prompt: str, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "telegram_user_id": telegram_user_id,
            "prompt": prompt,
            "platform": "youtube_shorts",
            "research_mode": "fixtures",
        }
        if idempotency_key:
            payload["idempotency_key"] = idempotency_key
        return await self._request("POST", "/producer/runs", json=payload)

    async def operations_status(self) -> dict[str, Any]:
        return await self._request("GET", "/operations/status")

    async def producer_progress(self, run_id: str) -> dict[str, Any] | None:
        return await self._request("GET", f"/producer/runs/{run_id}/progress")

    async def attach_progress_message(
        self, run_id: str, *, chat_id: int, message_id: int
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/producer/runs/{run_id}/progress-message",
            json={"chat_id": chat_id, "message_id": message_id},
        )

    async def operations_calendar(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/operations/calendar")

    async def operations_approvals(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/operations/approvals", params={"status": "pending"})

    async def create_text_source(
        self, *, telegram_user_id: int, telegram_username: str | None, text: str
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/sources",
            json={
                "telegram_user_id": telegram_user_id,
                "telegram_username": telegram_username,
                "type": "text",
                "original_text": text,
            },
        )

    async def generate_ideas(self, source_id: str) -> list[dict[str, Any]]:
        return await self._request("POST", f"/sources/{source_id}/generate-ideas")

    async def generate_draft(self, idea_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/ideas/{idea_id}/generate-draft")

    async def ingest(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/sources/telegram-ingestion", json=payload)

    async def get_source(self, source_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/sources/{source_id}")

    async def list_projects(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/projects")

    async def list_assets(self, project_id: str, query: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"project_id": project_id}
        if query:
            params["query"] = query
        return await self._request("GET", "/assets", params=params)

    async def create_production(self, source: dict[str, Any], title: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/production-projects",
            json={
                "project_id": source["project_id"],
                "user_id": source["user_id"],
                "initial_source_item_id": source["id"],
                "title": title,
                "target_format": "short_video",
            },
        )

    async def list_productions(self, telegram_user_id: int) -> list[dict[str, Any]]:
        return await self._request("GET", f"/production-projects/telegram-user/{telegram_user_id}")

    async def get_production(self, production_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/production-projects/{production_id}")

    async def attach_production_material(
        self,
        production_id: str,
        *,
        source_item_id: str,
        roles: list[str],
        instruction: str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/production-projects/{production_id}/materials",
            json={
                "source_item_id": source_item_id,
                "roles": roles,
                "user_instruction": instruction,
            },
        )

    async def production_materials(
        self, production_id: str, used: bool | None = None
    ) -> list[dict[str, Any]]:
        params = {"used": str(used).lower()} if used is not None else None
        return await self._request(
            "GET", f"/production-projects/{production_id}/materials", params=params
        )

    async def generate_production_script(self, production_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/production-projects/{production_id}/scripts/generate")

    async def edit_production_script(self, production_id: str, instruction: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/production-projects/{production_id}/scripts/edit",
            json={"instruction": instruction},
        )

    async def approve_production_script(self, production_id: str, script_id: str) -> dict[str, Any]:
        return await self._request(
            "POST", f"/production-projects/{production_id}/scripts/{script_id}/approve"
        )

    async def assemble_production(self, production_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/production-projects/{production_id}/assembly")

    async def run_autonomous_director(self, production_id: str, instruction: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/production-projects/{production_id}/director/autonomous",
            json={"instruction": instruction},
        )

    async def replan_production(self, production_id: str, instruction: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/production-projects/{production_id}/replan",
            json={"instruction": instruction},
        )

    async def render_production(self, production_id: str, profile: str) -> dict[str, Any]:
        return await self._request("POST", f"/production-projects/{production_id}/render/{profile}")

    async def setup_ai(
        self,
        *,
        telegram_user_id: int,
        base_url: str,
        model: str,
        api_key: str | None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/setup/ai/test-and-activate",
            json={
                "telegram_user_id": telegram_user_id,
                "private_chat": True,
                "provider": "openai_compatible",
                "base_url": base_url,
                "model": model,
                "api_key": api_key,
            },
        )

    async def select_production_placement(
        self, material_id: str, candidate_index: int
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/production-projects/materials/{material_id}/placement",
            json={"candidate_index": candidate_index},
        )

    async def setup_summary(self, telegram_user_id: int) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/setup/summary",
            params={"telegram_user_id": telegram_user_id, "private_chat": "true"},
        )

    async def setup_diagnostics(self, telegram_user_id: int) -> dict[str, str]:
        return await self._request(
            "GET",
            "/setup/diagnostics",
            params={"telegram_user_id": telegram_user_id, "private_chat": "true"},
        )

    async def suggest_visuals(self, video_project_id: str) -> dict[str, Any]:
        return await self._request(
            "POST", f"/video-projects/{video_project_id}/visual-suggestions", json={}
        )

    async def set_visual_plan(self, video_project_id: str, plan: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "PUT", f"/video-projects/{video_project_id}/visual-plan", json={"visual_plan": plan}
        )

    async def add_visual(self, video_project_id: str, insertion: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/video-projects/{video_project_id}/visual-plan/insertions",
            json={"insertion": insertion},
        )

    async def edit_visuals(self, video_project_id: str, instruction: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/video-projects/{video_project_id}/visual-plan/instruction",
            json={"instruction": instruction},
        )

    async def generate_thumbnails(
        self, video_project_id: str, headline: str | None = None
    ) -> list[dict[str, Any]]:
        return await self._request(
            "POST",
            f"/thumbnail-projects/video-projects/{video_project_id}",
            json={"headline": headline},
        )

    async def select_thumbnail(self, thumbnail_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/thumbnail-projects/{thumbnail_id}/select")

    async def download_thumbnail(self, thumbnail_id: str) -> bytes:
        response = await self.client.get(f"/thumbnail-projects/{thumbnail_id}/file")
        response.raise_for_status()
        return response.content

    async def list_inbox(
        self,
        telegram_user_id: int,
        *,
        page: int = 1,
        source_type: str | None = None,
        best: bool = False,
        query: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "telegram_user_id": telegram_user_id,
            "page": page,
            "page_size": 5,
            "best": str(best).lower(),
        }
        if source_type:
            params["source_type"] = source_type
        if query:
            params["query"] = query
        return await self._request("GET", "/inbox", params=params)

    async def digest(self, telegram_user_id: int) -> dict[str, Any]:
        return await self._request(
            "GET", "/inbox/digest", params={"telegram_user_id": telegram_user_id}
        )

    async def archive_source(self, source_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/sources/{source_id}/archive")

    async def retry_source(self, source_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/sources/{source_id}/retry")

    async def delete_source(self, source_id: str) -> None:
        await self._request("DELETE", f"/sources/{source_id}")

    async def add_source_note(
        self, source_id: str, telegram_user_id: int, text: str
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/sources/{source_id}/notes",
            json={"telegram_user_id": telegram_user_id, "text": text},
        )

    async def add_source_voice_note(
        self, source_id: str, telegram_user_id: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/sources/{source_id}/notes",
            json={
                "telegram_user_id": telegram_user_id,
                "telegram_file_id": payload["telegram_file_id"],
                "telegram_unique_file_id": payload.get("telegram_unique_file_id"),
                "telegram_update_id": payload.get("telegram_update_id"),
                "mime_type": payload.get("mime_type"),
                "file_size": payload.get("file_size"),
            },
        )

    async def generate_source_short(self, source_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/sources/{source_id}/generate-short")

    async def generate_source_post(self, source_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/sources/{source_id}/generate-telegram-post")

    async def create_video_project(self, source_id: str) -> dict[str, Any]:
        return await self._request(
            "POST", f"/sources/{source_id}/video-projects", json={"target_duration": 45}
        )

    async def create_manual_video_project(
        self, source_id: str, start: float, end: float
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/sources/{source_id}/video-projects/manual",
            json={"source_start": start, "source_end": end, "framing": "center_crop"},
        )

    async def get_video_project(self, video_project_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/video-projects/{video_project_id}")

    async def regenerate_video_concepts(self, video_project_id: str) -> dict[str, Any]:
        return await self._request(
            "POST", f"/video-projects/{video_project_id}/regenerate-concepts"
        )

    async def generate_video_edit_plan(
        self, video_project_id: str, concept_index: int, instruction: str | None = None
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/video-projects/{video_project_id}/generate-edit-plan",
            json={"concept_index": concept_index, "instruction": instruction},
        )

    async def render_video(self, video_project_id: str, force: bool = False) -> dict[str, Any]:
        endpoint = "rerender" if force else "render"
        payload = None if force else {"force": False}
        return await self._request(
            "POST", f"/video-projects/{video_project_id}/{endpoint}", json=payload
        )

    async def set_video_style(self, video_project_id: str, preset: str) -> dict[str, Any]:
        return await self._request(
            "POST", f"/video-projects/{video_project_id}/style", json={"preset": preset}
        )

    async def approve_video(self, video_project_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/video-projects/{video_project_id}/approve")

    async def prepare_publish_package(
        self, video_project_id: str, platforms: list[str], regenerate: bool = False
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/video-projects/{video_project_id}/publish-package",
            json={"platforms": platforms, "regenerate": regenerate},
        )

    async def get_publish_package(self, package_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/publish-packages/{package_id}")

    async def update_platform_variant(self, variant_id: str, **fields: Any) -> dict[str, Any]:
        return await self._request("PATCH", f"/platform-variants/{variant_id}", json=fields)

    async def list_platform_accounts(
        self, project_id: str, platform: str | None = None
    ) -> list[dict[str, Any]]:
        params = {"project_id": project_id}
        if platform:
            params["platform"] = platform
        return await self._request("GET", "/platform-accounts", params=params)

    async def create_publications(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        return await self._request("POST", "/publications/batch", json={"items": items})

    async def validate_platform_variant(self, variant_id: str, account_id: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/platform-variants/{variant_id}/validate",
            params={"account_id": account_id},
        )

    async def prepare_platform_variant_media(self, variant_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/platform-variants/{variant_id}/prepare-media")

    async def list_publications(self, status: str | None = None) -> list[dict[str, Any]]:
        params = {"status_filter": status} if status else None
        return await self._request("GET", "/publications", params=params)

    async def get_publication(self, publication_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/publications/{publication_id}")

    async def reschedule_publication(
        self, publication_id: str, scheduled_at: datetime
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/publications/{publication_id}/schedule",
            json={"scheduled_at": scheduled_at.isoformat()},
        )

    async def update_publication_content(
        self, publication_id: str, **fields: Any
    ) -> dict[str, Any]:
        return await self._request("PATCH", f"/publications/{publication_id}/content", json=fields)

    async def publish_now(self, publication_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/publications/{publication_id}/publish-now")

    async def cancel_publication(self, publication_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/publications/{publication_id}/cancel")

    async def retry_publication(self, publication_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/publications/{publication_id}/retry")

    async def archive_video(self, video_project_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/video-projects/{video_project_id}/archive")

    async def update_transcript(self, video_project_id: str, old: str, new: str) -> dict[str, Any]:
        return await self._request(
            "PATCH",
            f"/video-projects/{video_project_id}/transcript-overrides",
            json={"replacements": {old: new}},
        )

    async def regenerate(self, draft_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/drafts/{draft_id}/regenerate")

    async def approve(self, draft_id: str) -> dict[str, Any]:
        return await self._request(
            "PATCH", f"/drafts/{draft_id}/status", json={"status": "approved"}
        )

    async def repurpose(self, draft_id: str) -> list[dict[str, Any]]:
        return await self._request("POST", f"/drafts/{draft_id}/repurpose")

    async def delete_draft(self, draft_id: str) -> None:
        await self._request("DELETE", f"/drafts/{draft_id}")

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = await self.client.request(method, path, **kwargs)
        response.raise_for_status()
        if response.status_code == 204:
            return None
        return response.json()
