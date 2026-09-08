from pydantic import BaseModel, Field, model_validator


class TranscriptWord(BaseModel):
    word: str
    start: float = Field(ge=0)
    end: float = Field(ge=0)

    @model_validator(mode="after")
    def valid_range(self) -> "TranscriptWord":
        if self.end <= self.start:
            raise ValueError("word end must be greater than start")
        return self


class TranscriptSegment(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str
    words: list[TranscriptWord] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_range(self) -> "TranscriptSegment":
        if self.end <= self.start:
            raise ValueError("segment end must be greater than start")
        return self


class TranscriptionResult(BaseModel):
    text: str
    language: str | None = None
    duration: float | None = None
    segments: list[TranscriptSegment] = Field(default_factory=list)


class LinkContent(BaseModel):
    requested_url: str
    final_url: str
    title: str | None = None
    description: str | None = None
    site_name: str | None = None
    main_text: str
    content_type: str


class DocumentContent(BaseModel):
    text: str
    truncated: bool = False
    page_count: int | None = None
    extraction_error: str | None = None
