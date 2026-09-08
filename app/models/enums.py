from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "admin"
    USER = "user"


class SourceType(StrEnum):
    TEXT = "text"
    VOICE = "voice"
    AUDIO = "audio"
    VIDEO = "video"
    VIDEO_NOTE = "video_note"
    IMAGE = "image"
    URL = "url"
    DOCUMENT = "document"


class SourceStatus(StrEnum):
    NEW = "new"
    PROCESSING = "processing"
    READY = "ready"
    USED = "used"
    FAILED = "failed"
    ARCHIVED = "archived"


class ProcessingStage(StrEnum):
    RECEIVED = "received"
    DOWNLOADED = "downloaded"
    MEDIA_PREPARED = "media_prepared"
    TRANSCRIBED = "transcribed"
    EXTRACTED = "extracted"
    ENRICHED = "enriched"
    READY = "ready"
    FAILED = "failed"


class IdeaStatus(StrEnum):
    DRAFT = "draft"
    SELECTED = "selected"
    ARCHIVED = "archived"


class DraftStatus(StrEnum):
    GENERATING = "generating"
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"


class Platform(StrEnum):
    YOUTUBE = "youtube"
    YOUTUBE_SHORTS = "youtube_shorts"
    TIKTOK = "tiktok"
    TELEGRAM = "telegram"


class ContentFormat(StrEnum):
    SHORT_VIDEO = "short_video"
    LONG_VIDEO = "long_video"
    POST = "post"
    THREAD = "thread"


class ContentPillar(StrEnum):
    EDUCATION = "education"
    CASE = "case"
    OPINION = "opinion"
    BUILD_IN_PUBLIC = "build_in_public"
    BEHIND_THE_SCENES = "behind_the_scenes"
    EXPERIMENT = "experiment"
    SALES = "sales"


class VideoProjectStatus(StrEnum):
    DRAFT = "draft"
    ANALYZING = "analyzing"
    READY_TO_RENDER = "ready_to_render"
    RENDERING = "rendering"
    RENDERED = "rendered"
    APPROVED = "approved"
    CANCEL_REQUESTED = "cancel_requested"
    FAILED = "failed"
    ARCHIVED = "archived"


class FramingMode(StrEnum):
    CENTER_CROP = "center_crop"
    FIT_BLUR = "fit_blur"
    MANUAL = "manual"
    SCREEN_FIT = "screen_fit"


class SubtitlePreset(StrEnum):
    CLEAN = "clean"
    DYNAMIC = "dynamic"
    TECH = "tech"
