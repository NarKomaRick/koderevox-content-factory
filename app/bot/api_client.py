from typing import Any

import httpx


class BackendClient:
    def __init__(self, base_url: str, timeout: float = 180) -> None:
        self.client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)

    async def close(self) -> None:
        await self.client.aclose()

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
