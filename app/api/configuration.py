"""Configuration/template APIs for the first local Redis fixture flow."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_session
from app.core.response import ApiResponse, success
from app.schemas.auth import CurrentUser
from app.schemas.configuration import (
    ConfigurationDetail,
    ConfigurationHistory,
    ConfigurationList,
    ConfigurationSaveInput,
    TemplateSummary,
)
from app.services.configuration import ConfigurationService

router = APIRouter(prefix="/api/v1/config", tags=["configuration"])
Identity = Annotated[CurrentUser, Depends(get_current_user)]


def get_service(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> ConfigurationService:
    return ConfigurationService(session, request.app.state.settings)


Service = Annotated[ConfigurationService, Depends(get_service)]


@router.get("/templates", response_model=ApiResponse[list[TemplateSummary]])
async def templates(current: Identity, service: Service) -> ApiResponse[list[TemplateSummary]]:
    return success(service.templates())


@router.get("/list", response_model=ApiResponse[ConfigurationList])
async def list_configs(current: Identity, service: Service) -> ApiResponse[ConfigurationList]:
    return success(await service.list(current.user_id))


@router.post("/save", response_model=ApiResponse[ConfigurationDetail])
async def save(
    payload: ConfigurationSaveInput,
    current: Identity,
    service: Service,
    response: Response,
) -> ApiResponse[ConfigurationDetail]:
    response.headers["Cache-Control"] = "no-store"
    return success(await service.save(current.user_id, payload))


@router.post("/detail", response_model=ApiResponse[ConfigurationDetail])
async def detail(
    payload: dict[str, str], current: Identity, service: Service
) -> ApiResponse[ConfigurationDetail]:
    return success(await service.get(current.user_id, payload["config_id"]))


@router.post("/history", response_model=ApiResponse[ConfigurationHistory])
async def history(
    payload: dict[str, str], current: Identity, service: Service
) -> ApiResponse[ConfigurationHistory]:
    return success(await service.history(current.user_id, payload["config_id"]))
