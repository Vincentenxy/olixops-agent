"""Authenticated infrastructure diagnostics and a dependency readiness probe."""

import asyncio
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from starlette.responses import JSONResponse

from app.api.dependencies import get_current_user
from app.core.cache import Cache
from app.core.config import Settings
from app.core.database import Database
from app.core.response import ApiResponse, http_error, success
from app.core.security import Security
from app.integrations.pulumi.diagnostics import check_runtime
from app.schemas.auth import CurrentUser

router = APIRouter(tags=["system"])


class ComponentStatus(BaseModel):
    status: Literal["ok", "error", "disabled"]
    message: str


class PulumiStatus(ComponentStatus):
    sdk_version: str
    cli_version: str | None


class SystemStatus(BaseModel):
    database: ComponentStatus
    redis: ComponentStatus
    pulumi: PulumiStatus
    auth: ComponentStatus


@router.get("/api/v1/system/status")
async def system_status(
    request: Request, user: Annotated[CurrentUser, Depends(get_current_user)]
) -> ApiResponse[SystemStatus]:
    database = cast(Database, request.app.state.database)
    cache = cast(Cache, request.app.state.cache)
    settings = cast(Settings, request.app.state.settings)
    database_ok, redis_ok, pulumi = await asyncio.gather(
        database.check(),
        cache.check(),
        asyncio.to_thread(check_runtime, cli=settings.pulumi_cli),
    )
    return success(
        SystemStatus(
            database=ComponentStatus(
                status="ok" if database_ok else "error",
                message="数据库连接正常" if database_ok else "数据库暂不可用",
            ),
            redis=ComponentStatus(
                status=("ok" if redis_ok else "error") if cache.enabled else "disabled",
                message=("缓存连接正常" if redis_ok else "缓存暂不可用")
                if cache.enabled
                else "未启用缓存",
            ),
            pulumi=PulumiStatus(
                status="ok" if pulumi.status == "ready" else "error",
                message="Pulumi 运行时可用"
                if pulumi.status == "ready"
                else "Pulumi 未安装或版本不匹配，请检查执行环境",
                sdk_version=pulumi.sdk_version or "未安装",
                cli_version=pulumi.cli_version,
            ),
            auth=ComponentStatus(status="ok", message="本地账户与会话认证正常"),
        )
    )


@router.get("/api/v1/pub/ready", response_model=ApiResponse[dict[str, str]])
async def readiness(request: Request) -> ApiResponse[dict[str, str]] | JSONResponse:
    database = cast(Database, request.app.state.database)
    cache = cast(Cache, request.app.state.cache)
    database_ok, cache_ok = await asyncio.gather(database.check(), cache.check())
    security = cast(Security, request.app.state.security)
    if not database_ok or (cache.enabled and not cache_ok) or not security.ready:
        return http_error(status_code=503)
    return success({"status": "ok"})
