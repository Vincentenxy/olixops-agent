"""FastAPI application factory and ASGI entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http import HTTPStatus

from fastapi import FastAPI

from app.api.health import router as health_router
from app.core.config import Settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.response import ApiResponse

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the public API; protected business routes await the JWT integration."""
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(debug=settings.mode == "debug")
        logger.info("application started")
        yield
        logger.info("application stopped")

    app = FastAPI(
        title="Olixops Agent API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        responses={
            code: {"model": ApiResponse[None], "description": HTTPStatus(code).phrase}
            for code in (404, 405, 422, 500)
        },
    )
    app.state.settings = settings
    register_exception_handlers(app)
    app.add_middleware(RequestContextMiddleware)
    app.include_router(health_router)
    return app


app = create_app()
