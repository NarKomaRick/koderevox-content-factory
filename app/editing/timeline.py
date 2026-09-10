"""Compatibility façade for the existing immutable TimelineRevision service."""

from app.services.production_timeline import TimelineRevisionService

__all__ = ["TimelineRevisionService"]
