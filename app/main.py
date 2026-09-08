from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import (
    assets,
    drafts,
    ideas,
    inbox,
    projects,
    sources,
    thumbnails,
    video_projects,
)
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.services.errors import InvalidStateError, NotFoundError, ProcessingError

settings = get_settings()
configure_logging(settings.log_level)

app = FastAPI(
    title="Koderevox AI Content Factory",
    version="0.4.0",
    description="Self-hosted content inbox, drafting and human-controlled video rendering API.",
)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.app_env}


@app.exception_handler(NotFoundError)
async def not_found_handler(_request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(InvalidStateError)
async def invalid_state_handler(_request: Request, exc: InvalidStateError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


app.include_router(projects.router)
app.include_router(sources.router)
app.include_router(inbox.router)
app.include_router(ideas.router)
app.include_router(drafts.router)
app.include_router(video_projects.router)
app.include_router(assets.router)
app.include_router(thumbnails.router)


@app.exception_handler(ProcessingError)
async def processing_error_handler(_request: Request, exc: ProcessingError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})
