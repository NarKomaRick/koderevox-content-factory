from enum import StrEnum

from app.services.errors import InvalidStateError


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


CONTENT_ITEM_TRANSITIONS: dict[ContentItemStatus, set[ContentItemStatus]] = {
    ContentItemStatus.PLANNED: {
        ContentItemStatus.QUEUED,
        ContentItemStatus.CANCELLED,
        ContentItemStatus.PAUSED,
    },
    ContentItemStatus.QUEUED: {
        ContentItemStatus.PRODUCER_RUNNING,
        ContentItemStatus.DEFERRED,
        ContentItemStatus.CANCELLED,
        ContentItemStatus.PAUSED,
    },
    ContentItemStatus.DEFERRED: {
        ContentItemStatus.QUEUED,
        ContentItemStatus.CANCELLED,
        ContentItemStatus.PAUSED,
    },
    ContentItemStatus.PRODUCER_RUNNING: {
        ContentItemStatus.PRODUCER_READY,
        ContentItemStatus.QUEUED,
        ContentItemStatus.FAILED,
        ContentItemStatus.MANUAL_REQUIRED,
        ContentItemStatus.CANCELLED,
    },
    ContentItemStatus.PRODUCER_READY: {
        ContentItemStatus.AWAITING_SCRIPT_APPROVAL,
        ContentItemStatus.DIRECTOR_QUEUED,
        ContentItemStatus.CANCELLED,
    },
    ContentItemStatus.AWAITING_SCRIPT_APPROVAL: {
        ContentItemStatus.DIRECTOR_QUEUED,
        ContentItemStatus.QUEUED,
        ContentItemStatus.CANCELLED,
    },
    ContentItemStatus.DIRECTOR_QUEUED: {
        ContentItemStatus.DIRECTOR_RUNNING,
        ContentItemStatus.CANCELLED,
    },
    ContentItemStatus.DIRECTOR_RUNNING: {
        ContentItemStatus.PREVIEW_READY,
        ContentItemStatus.QUEUED,
        ContentItemStatus.FAILED,
        ContentItemStatus.MANUAL_REQUIRED,
        ContentItemStatus.CANCELLED,
    },
    ContentItemStatus.PREVIEW_READY: {
        ContentItemStatus.AWAITING_PREVIEW_APPROVAL,
        ContentItemStatus.READY_TO_PUBLISH,
        ContentItemStatus.QUEUED,
        ContentItemStatus.CANCELLED,
    },
    ContentItemStatus.AWAITING_PREVIEW_APPROVAL: {
        ContentItemStatus.READY_TO_PUBLISH,
        ContentItemStatus.QUEUED,
        ContentItemStatus.CANCELLED,
    },
    ContentItemStatus.READY_TO_PUBLISH: {
        ContentItemStatus.PUBLISHING,
        ContentItemStatus.CANCELLED,
    },
    ContentItemStatus.PUBLISHING: {
        ContentItemStatus.PUBLISHED,
        ContentItemStatus.FAILED,
        ContentItemStatus.MANUAL_REQUIRED,
    },
    ContentItemStatus.FAILED: {
        ContentItemStatus.QUEUED,
        ContentItemStatus.MANUAL_REQUIRED,
        ContentItemStatus.CANCELLED,
    },
    ContentItemStatus.MANUAL_REQUIRED: {
        ContentItemStatus.QUEUED,
        ContentItemStatus.CANCELLED,
    },
    ContentItemStatus.PAUSED: {
        ContentItemStatus.QUEUED,
        ContentItemStatus.CANCELLED,
    },
}


def ensure_content_item_transition(
    current: ContentItemStatus | str, target: ContentItemStatus | str
) -> None:
    current_status = ContentItemStatus(current)
    target_status = ContentItemStatus(target)
    if current_status != target_status and target_status not in CONTENT_ITEM_TRANSITIONS.get(
        current_status, set()
    ):
        raise InvalidStateError(f"INVALID_TRANSITION: {current_status} -> {target_status}")
