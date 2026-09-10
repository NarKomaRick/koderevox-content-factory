from enum import StrEnum


class ContentItemStatus(StrEnum):
    PLANNED = "planned"
    QUEUED = "queued"
    PRODUCER_RUNNING = "producer_running"
    PRODUCER_READY = "producer_ready"
    AWAITING_SCRIPT_APPROVAL = "awaiting_script_approval"
    DIRECTOR_QUEUED = "director_queued"
    DIRECTOR_RUNNING = "director_running"
    PREVIEW_READY = "preview_ready"
    AWAITING_PREVIEW_APPROVAL = "awaiting_preview_approval"
    APPROVED = "approved"
    READY_TO_PUBLISH = "ready_to_publish"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"
    DEFERRED = "deferred"
    MANUAL_REQUIRED = "manual_required"
    ARCHIVED = "archived"


class ApprovalPolicy(StrEnum):
    NONE = "none"
    SCRIPT = "script"
    PREVIEW = "preview"
    BEFORE_PUBLISH = "before_publish"
    SCRIPT_AND_PREVIEW = "script_and_preview"
    FULL_MANUAL = "full_manual"


class ApprovalCheckpoint(StrEnum):
    SCRIPT = "script"
    PREVIEW = "preview"
    FINAL = "final"
    BEFORE_PUBLISH = "before_publish"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class DependencyStatus(StrEnum):
    PENDING = "pending"
    SATISFIED = "satisfied"
    FAILED = "failed"
    WAIVED = "waived"


class ErrorClass(StrEnum):
    TEMPORARY = "temporary"
    RATE_LIMIT = "rate_limit"
    RESOURCE_UNAVAILABLE = "resource_unavailable"
    INVALID_INPUT = "invalid_input"
    EXTERNAL_DEPENDENCY = "external_dependency"
    PERMANENT = "permanent"
    MANUAL_REQUIRED = "manual_required"


class ManualPriority(StrEnum):
    URGENT = "urgent"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"
