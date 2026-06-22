from __future__ import annotations

from fastapi import FastAPI

from agenttrace.api.analysis import router as analysis_router
from agenttrace.app.routers.health import router as health_router
from agenttrace.app.routers.reports import router as reports_router
from agenttrace.app.routers.summaries import router as summaries_router
from agenttrace.config import configure_runtime_environment


def create_app() -> FastAPI:
    settings = configure_runtime_environment()
    app = FastAPI(title=settings.service_name)
    app.include_router(health_router)
    app.include_router(summaries_router, prefix="/v1")
    app.include_router(reports_router, prefix="/v1")
    app.include_router(analysis_router)
    return app


app = create_app()
