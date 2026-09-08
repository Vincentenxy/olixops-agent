"""Public process health; external dependencies will need separate readiness checks."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.response import ApiResponse, success

router = APIRouter(prefix="/api/v1/pub", tags=["health"])


class HealthData(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["olixops-agent"] = "olixops-agent"


@router.get("/health", response_model=ApiResponse[HealthData])
async def health() -> ApiResponse[HealthData]:
    """Report API process health without requiring a user identity."""
    return success(HealthData())
