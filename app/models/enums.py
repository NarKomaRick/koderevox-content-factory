from enum import StrEnum


class UserRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    USER = "user"


class ProductionStatus(StrEnum):
    IDEA = "idea"
    RESEARCH = "research"
    SCRIPTING = "scripting"
    READY_FOR_VOICEOVER = "ready_for_voiceover"
    VOICEOVER_PROCESSING = "voiceover_processing"
    VOICEOVER_READY = "voiceover_ready"
    ASSEMBLING = "assembling"
    ROUGH_CUT = "rough_cut"
    REVIEW = "review"
    APPROVED = "approved"
    ARCHIVED = "archived"


class ProductionMaterialRole(StrEnum):
    VOICEOVER = "voiceover"
    FOOTAGE = "footage"
    BROLL = "broll"
    SCREEN_RECORDING = "screen_recording"
    SCREENSHOT = "screenshot"
    MEME = "meme"
    IMAGE = "image"
    CODE = "code"
    REFERENCE = "reference"
    FACT_SOURCE = "fact_source"
    MUSIC = "music"
    OTHER = "other"


class ProductionFactStatus(StrEnum):
    PROPOSED = "proposed"
    VERIFIED = "verified"
    USER_CONFIRMED = "user_confirmed"
    REJECTED = "rejected"


class ScriptSource(StrEnum):
    AI = "ai"
    USER = "user"
    AI_EDITED = "ai_edited"
    IMPORT = "import"


class VoiceoverStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    REPLACED = "replaced"


class TimelineTrack(StrEnum):
    AUDIO_MASTER = "audio_master"
    VIDEO_BASE = "video_base"
    BROLL = "broll"
    OVERLAY = "overlay"
    GRAPHICS = "graphics"
    TEXT = "text"
    SUBTITLES = "subtitles"
    MUSIC = "music"


class RuntimeSettingScope(StrEnum):
    SYSTEM = "system"
    USER = "user"
    PROJECT = "project"


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


class AssetType(StrEnum):
    IMAGE = "image"
    SCREENSHOT = "screenshot"
    SCREEN_RECORDING = "screen_recording"
    VIDEO = "video"
    CODE = "code"
    LOGO = "logo"
    DIAGRAM = "diagram"
    DOCUMENT_PAGE = "document_page"
    GENERATED_GRAPHIC = "generated_graphic"


class AssetStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    ARCHIVED = "archived"


class VisualLayout(StrEnum):
    FULLSCREEN = "fullscreen"
    PICTURE_IN_PICTURE = "picture_in_picture"
    SIDE_BY_SIDE = "side_by_side"
    BACKGROUND = "background"
    DEVICE_FRAME = "device_frame"
    CODE_CARD = "code_card"


class VisualTransition(StrEnum):
    NONE = "none"
    FADE = "fade"
    SCALE_IN = "scale_in"
    SLIDE = "slide"


class ThumbnailStatus(StrEnum):
    DRAFT = "draft"
    RENDERING = "rendering"
    RENDERED = "rendered"
    SELECTED = "selected"
    FAILED = "failed"


class ThumbnailPreset(StrEnum):
    TECH_DARK = "tech_dark"
    CLEAN_LIGHT = "clean_light"
    PRODUCT = "product"


class PublishingPlatform(StrEnum):
    TELEGRAM = "telegram"
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"


class PublishPackageStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    PARTIALLY_PUBLISHED = "partially_published"
    PUBLISHED = "published"
    FAILED = "failed"
    ARCHIVED = "archived"


class PublicationStatus(StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    QUEUED = "queued"
    PUBLISHING = "publishing"
    PROCESSING = "processing"
    PUBLISHED = "published"
    PUBLISHED_WITH_WARNING = "published_with_warning"
    RETRY_WAIT = "retry_wait"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PublicationAttemptStatus(StrEnum):
    STARTED = "started"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    RETRY_SCHEDULED = "retry_scheduled"
    FAILED = "failed"


class PublicationEventType(StrEnum):
    CREATED = "created"
    SCHEDULED = "scheduled"
    CLAIMED = "claimed"
    UPLOAD_STARTED = "upload_started"
    REMOTE_ACCEPTED = "remote_accepted"
    PROCESSING = "processing"
    PUBLISHED = "published"
    FAILED = "failed"
    RETRIED = "retried"
    CANCELLED = "cancelled"
