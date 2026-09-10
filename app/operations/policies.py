from dataclasses import dataclass

from app.core.config import Settings
from app.operations.domain import ApprovalPolicy


@dataclass(frozen=True)
class OperationsPolicy:
    enabled: bool
    dry_run: bool
    planning_horizon_days: int
    max_planned_items: int
    max_active_items: int
    max_pending_render: int
    max_pending_approval: int
    auto_publish: bool
    max_producer_retries: int
    max_director_retries: int
    max_render_retries: int
    max_publish_retries: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "OperationsPolicy":
        return cls(
            enabled=settings.operations_enabled,
            dry_run=settings.operations_dry_run,
            planning_horizon_days=settings.operations_planning_horizon_days,
            max_planned_items=settings.operations_max_planned_items,
            max_active_items=settings.operations_max_active_items,
            max_pending_render=settings.operations_max_pending_render,
            max_pending_approval=settings.operations_max_pending_approval,
            auto_publish=settings.operations_auto_publish,
            max_producer_retries=settings.operations_max_producer_retries,
            max_director_retries=settings.operations_max_director_retries,
            max_render_retries=settings.operations_max_render_retries,
            max_publish_retries=settings.operations_max_publish_retries,
        )

    @staticmethod
    def requires_script_approval(policy: str) -> bool:
        return policy in {
            ApprovalPolicy.SCRIPT,
            ApprovalPolicy.SCRIPT_AND_PREVIEW,
            ApprovalPolicy.FULL_MANUAL,
        }

    @staticmethod
    def requires_preview_approval(policy: str) -> bool:
        return policy in {
            ApprovalPolicy.PREVIEW,
            ApprovalPolicy.SCRIPT_AND_PREVIEW,
            ApprovalPolicy.FULL_MANUAL,
        }

    @staticmethod
    def requires_publish_approval(policy: str) -> bool:
        return policy in {ApprovalPolicy.BEFORE_PUBLISH, ApprovalPolicy.FULL_MANUAL}
