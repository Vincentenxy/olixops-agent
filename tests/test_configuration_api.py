"""Configuration API vertical slice using the local GitLab fixture."""

from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.auth import COOKIE_PATH
from app.cli import create_user, init_keys
from app.core.config import Settings
from app.core.database import Database
from app.main import create_app
from app.models.auth import Base


def test_redis_configuration_save_read_history(tmp_path: Path) -> None:
    key_dir = tmp_path / "keys"
    settings = Settings(
        database_url=SecretStr(f"sqlite+aiosqlite:///{tmp_path / 'configuration.db'}"),
        jwt_private_key_path=key_dir / "private.pem",
        jwt_public_key_path=key_dir / "public.pem",
        template_fixture_root=Path("fixtures/gitlab").resolve(),
        mode="release",
    )
    assert init_keys(settings)
    app = create_app(settings)
    database = cast(Database, app.state.database)

    async def prepare() -> None:
        async with database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        assert await create_user(
            settings, "admin", "Local Admin", "test-only-password-Alpha42", admin=True
        )

    with TestClient(app) as client:
        portal = cast(Any, client.portal)
        assert portal is not None
        portal.call(prepare)
        login = client.post(
            f"{COOKIE_PATH}/login",
            headers={"X-Olixops-Client": "web"},
            json={"username": "admin", "password": "test-only-password-Alpha42"},
        )
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}

        templates = client.get("/api/v1/config/templates", headers=headers)
        assert templates.status_code == 200, templates.text
        assert templates.json()["data"][0]["template_id"] == "redis/standalone/v1"

        save = client.post(
            "/api/v1/config/save",
            headers=headers,
            json={
                "request_id": str(uuid4()),
                "name": "demo-redis",
                "parameters": {"name": "demo-redis", "namespace": "default"},
            },
        )
        assert save.status_code == 200, save.text
        data = save.json()["data"]
        assert data["current_revision"] == 1
        assert "kind: Deployment" in data["rendered_manifest"]
        config_id = data["config_id"]

        detail = client.post(
            "/api/v1/config/detail", headers=headers, json={"config_id": config_id}
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()["data"]["template_commit"] == "fixture-main-redis-v1"

        history = client.post(
            "/api/v1/config/history", headers=headers, json={"config_id": config_id}
        )
        assert history.status_code == 200, history.text
        assert len(history.json()["data"]["items"]) == 1
