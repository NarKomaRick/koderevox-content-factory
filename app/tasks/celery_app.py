from celery import Celery  # type: ignore[import-untyped]

from app.core.config import get_settings
from app.core.logging import silence_sensitive_transport_logs

settings = get_settings()
silence_sensitive_transport_logs()
celery_app = Celery(
    "content_factory",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.processing", "app.tasks.rendering", "app.tasks.publishing"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    task_track_started=True,
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
    task_routes={
        "content_factory.process_source": {"queue": "media"},
        "content_factory.process_source_note": {"queue": "media"},
        "content_factory.render_video": {"queue": "render"},
        "content_factory.render_production": {"queue": "render"},
        "content_factory.render_platform_variant": {"queue": "render"},
        "content_factory.publish": {"queue": "publish"},
        "content_factory.poll_publication": {"queue": "publish"},
    },
)


@celery_app.task(name="content_factory.healthcheck")
def healthcheck() -> str:
    return "ok"
