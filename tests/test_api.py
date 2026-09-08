"""Observable HTTP contracts and isolation of concurrent request context."""

import asyncio
import re
from http import HTTPStatus
from typing import Annotated

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from httpx2 import ASGITransport, AsyncClient
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from app.core.config import Settings
from app.core.context import trace_id
from app.main import create_app


class ProbeInput(BaseModel):
    value: int


@pytest.fixture
def api() -> FastAPI:
    app = create_app(Settings(mode="release", docs_enabled=False))

    @app.post("/api/v1/pub/test-validation")
    async def validate_probe(payload: ProbeInput) -> ProbeInput:
        return payload

    @app.get("/api/v1/pub/test-auth-error")
    async def auth_error() -> None:
        raise HTTPException(401, detail="internal detail", headers={"WWW-Authenticate": "Bearer"})

    @app.get("/api/v1/pub/test-error")
    async def unexpected_error() -> None:
        raise RuntimeError("private exception details")

    @app.get("/api/v1/pub/test-context")
    async def context_probe(x_request_id: Annotated[str, Header()]) -> dict[str, str | None]:
        before = trace_id.get()
        await asyncio.sleep(0)
        return {"before": before, "after": trace_id.get(), "requested": x_request_id}

    return app


def test_health_response_contract() -> None:
    with TestClient(create_app(Settings(mode="release", docs_enabled=False))) as client:
        result = client.get("/api/v1/pub/health")
    assert result.status_code == 200
    assert result.json() == {
        "code": 0,
        "msg": "",
        "data": {"status": "ok", "service": "olixops-agent"},
    }
    assert re.fullmatch(r"[0-9a-f]{32}", result.headers["X-Request-Id"])


@pytest.mark.parametrize(
    ("method", "path", "expected_status"),
    [
        ("GET", "/api/v1/pub/health", 200),
        ("GET", "/api/v1/pub/not-found", 404),
        ("POST", "/api/v1/pub/health", 405),
        ("POST", "/api/v1/pub/test-validation", 422),
        ("GET", "/api/v1/pub/test-auth-error", 401),
        ("GET", "/api/v1/pub/test-error", 500),
    ],
)
def test_http_errors_and_request_id(
    api: FastAPI, method: str, path: str, expected_status: int
) -> None:
    with TestClient(api, raise_server_exceptions=False) as client:
        result = client.request(method, path, headers={"X-Request-Id": "test-trace-123"})
    assert result.status_code == expected_status
    assert result.headers["X-Request-Id"] == "test-trace-123"
    if expected_status != 200:
        assert result.json() == {
            "code": expected_status,
            "msg": HTTPStatus(expected_status).phrase,
            "data": None,
        }
    if expected_status == 401:
        assert result.headers["WWW-Authenticate"] == "Bearer"
    if expected_status == 405:
        assert result.headers["Allow"] == "GET"


def test_unexpected_error_generates_request_id(api: FastAPI) -> None:
    with TestClient(api, raise_server_exceptions=False) as client:
        result = client.get("/api/v1/pub/test-error")
    assert result.status_code == 500
    assert re.fullmatch(r"[0-9a-f]{32}", result.headers["X-Request-Id"])
    assert "private exception" not in result.text


def test_documentation_exposure_is_explicit() -> None:
    with TestClient(create_app(Settings(docs_enabled=False))) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
    with TestClient(create_app(Settings(docs_enabled=True))) as client:
        schema = client.get("/openapi.json")
    assert schema.status_code == 200
    assert "openapi" in schema.json()
    assert "code" not in schema.json()
    response_codes = schema.json()["paths"]["/api/v1/pub/health"]["get"]["responses"]
    assert {"200", "404", "405", "422", "500"} <= response_codes.keys()


def test_concurrent_requests_keep_context_isolated_and_reset_it(api: FastAPI) -> None:
    async def exercise_requests() -> None:
        assert trace_id.get() is None
        async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:

            async def request_with_id(request_id: str) -> None:
                response = await client.get(
                    "/api/v1/pub/test-context", headers={"X-Request-Id": request_id}
                )
                assert response.status_code == 200
                assert response.json() == {
                    "before": request_id,
                    "after": request_id,
                    "requested": request_id,
                }
                assert trace_id.get() is None

            await asyncio.gather(*(request_with_id(f"parallel-{index}") for index in range(20)))
            await request_with_id("after-parallel")
        assert trace_id.get() is None

    asyncio.run(exercise_requests())


def test_context_resets_when_request_raises(api: FastAPI) -> None:
    async def exercise_error() -> None:
        async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
            with pytest.raises(RuntimeError, match="private exception details"):
                await client.get("/api/v1/pub/test-error")
            assert trace_id.get() is None

    asyncio.run(exercise_error())
