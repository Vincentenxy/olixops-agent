"""Readiness represents required dependencies; private diagnostics require authentication."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user
from app.core.config import Settings
from app.integrations.pulumi.models import PulumiRuntimeStatus
from app.main import create_app
from app.schemas.auth import CurrentUser


def test_private_diagnostics_reject_anonymous_request() -> None:
    app = create_app(Settings(_env_file=None))
    with TestClient(app) as client:
        # Missing key configuration fails closed; configured authentication returns 401.
        response = client.get("/api/v1/system/status")
    assert response.status_code in {401, 503}
    assert response.json()["data"] is None


@pytest.mark.parametrize("database_ok,redis_ok", [(False, True), (True, False), (True, True)])
def test_dependency_outage_changes_readiness_but_not_liveness(
    database_ok: bool, redis_ok: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(Settings(_env_file=None))
    monkeypatch.setattr(app.state.database, "check", AsyncMock(return_value=database_ok))
    monkeypatch.setattr(app.state.cache, "check", AsyncMock(return_value=redis_ok))
    monkeypatch.setattr(type(app.state.cache), "enabled", property(lambda _: True))
    monkeypatch.setattr(type(app.state.security), "ready", property(lambda _: True))
    with TestClient(app) as client:
        response = client.get("/api/v1/pub/ready")
        if database_ok and redis_ok:
            assert response.status_code == 200
            assert response.json()["data"]["status"] == "ok"
        else:
            assert response.status_code == 503
            assert response.json() == {"code": 503, "msg": "Service Unavailable", "data": None}
        assert client.get("/api/v1/pub/health").status_code == 200


def test_status_reports_actual_dependency_outcomes_without_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="test-user",
        username="tester",
        name="Tester",
        is_admin=False,
        session_id="test-session",
        jwt="never-return-this-jwt",
        cookie="private-cookie",
    )
    monkeypatch.setattr(app.state.database, "check", AsyncMock(return_value=True))
    monkeypatch.setattr(
        "app.api.system.check_runtime",
        lambda **_: PulumiRuntimeStatus(
            status="unavailable", sdk_version="3.261.0", cli_version=None, message="missing"
        ),
    )
    with TestClient(app) as client:
        response = client.get("/api/v1/system/status")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["database"]["status"] == "ok"
    assert data["redis"]["status"] == "disabled"
    assert data["pulumi"]["status"] == "error"
    assert "never-return-this-jwt" not in response.text
    assert "postgresql" not in response.text
    assert "private-cookie" not in response.text
