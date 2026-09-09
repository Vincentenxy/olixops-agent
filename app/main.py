"""FastAPI application factory and ASGI entry point."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http import HTTPStatus
from urllib.parse import urlsplit

from fastapi import FastAPI

from app.api.auth import public_router as public_auth_router
from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.system import router as system_router
from app.core.cache import Cache
from app.core.config import Settings
from app.core.database import Database
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.response import ApiResponse
from app.core.security import Security

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API without requiring a live database for process health."""
    settings = settings or Settings()
    database = Database(settings)
    security = Security(settings)
    cache = Cache(settings.redis_url.get_secret_value() if settings.redis_url else None)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        urls = [settings.database_url.get_secret_value()]
        if settings.redis_url:
            urls.append(settings.redis_url.get_secret_value())
        configure_logging(
            debug=settings.mode == "debug",
            secrets=[*urls, *(urlsplit(url).password or "" for url in urls)],
        )
        await asyncio.to_thread(security.load)
        logger.info("application started")
        try:
            yield
        finally:
            await asyncio.gather(database.close(), cache.close())
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
            for code in (400, 401, 403, 404, 405, 415, 422, 500, 503)
        },
    )
    app.state.settings = settings
    app.state.database = database
    app.state.security = security
    app.state.cache = cache
    register_exception_handlers(app)
    app.add_middleware(RequestContextMiddleware)
    app.include_router(health_router)
    app.include_router(public_auth_router)
    app.include_router(auth_router)
    app.include_router(system_router)
    return app


app = create_app()
