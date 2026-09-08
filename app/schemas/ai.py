from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.enums import ContentFormat, ContentPillar


class ContentAngle(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    hook: str = Field(min_length=3)
    angle: str = Field(min_length=3)
    description: str = Field(min_length=3)
    format: ContentFormat = ContentFormat.SHORT_VIDEO
    estimated_duration: int = Field(ge=15, le=180)
    content_pillar: ContentPillar
    target_audience: str = Field(min_length=3)
    score: float = Field(ge=0, le=10)


class ContentAngleBatch(BaseModel):
    angles: list[ContentAngle] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def ensure_distinct(self) -> "ContentAngleBatch":
        normalized = {item.angle.strip().lower() for item in self.angles}
        if len(normalized) != 3:
            raise ValueError("All three angles must be genuinely distinct")
        return self


class Scene(BaseModel):
    start_second: int = Field(ge=0)
    end_second: int = Field(gt=0)
    spoken_text: str
    on_screen: str

    @model_validator(mode="after")
    def end_after_start(self) -> "Scene":
        if self.end_second <= self.start_second:
            raise ValueError("end_second must be greater than start_second")
        return self


class ShortScript(BaseModel):
    title: str
    hook: str
    script: str
    scenes: list[Scene] = Field(min_length=2)
    caption: str
    description: str
    call_to_action: str
    estimated_duration: int = Field(ge=20, le=75)


class RepurposedItem(BaseModel):
    title: str
    hook: str
    script: str
    caption: str
    description: str
    call_to_action: str
    estimated_duration: int | None = None


class RepurposeBundle(BaseModel):
    youtube_short: RepurposedItem
    tiktok: RepurposedItem
    telegram_post: RepurposedItem


class ContentIntelligence(BaseModel):
    topic: str = Field(min_length=3, max_length=500)
    summary: str = Field(min_length=3)
    source_facts: list[str]
    key_points: list[str]
    interesting_details: list[str]
    ai_suggestions: list[str]
    content_angles: list[str]
    content_pillars: list[ContentPillar]
    target_audiences: list[str]
    content_potential_score: int = Field(ge=0, le=100)
    why_it_is_interesting: str
    recommended_formats: list[str]
    requires_more_context: bool = False
    questions_to_user: list[str] = Field(default_factory=list, max_length=3)
    content_type: Literal["talking_head", "screen_recording", "mixed", "unknown"] = "unknown"

    @model_validator(mode="after")
    def context_questions_are_consistent(self) -> "ContentIntelligence":
        if not self.requires_more_context:
            self.questions_to_user = []
        return self
