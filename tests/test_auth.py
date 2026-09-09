"""Authentication behavior, credential boundaries and persistent session lifecycle."""

import asyncio
import os
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import cast

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select, update

from app.api.auth import COOKIE_NAME, COOKIE_PATH
from app.cli import create_user, init_keys
from app.core.config import Settings
from app.core.database import Database
from app.core.security import Security, token_hash
from app.main import create_app
from app.models.auth import AuthSession, Base, LocalUser, LoginThrottle, utcnow

PASSWORD = "test-only-password-Alpha42"
NEW_PASSWORD = "test-only-password-Beta42"
WRITE_HEADERS = {"X-Olixops-Client": "web"}


@pytest.fixture(scope="module")
def keys(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    directory = tmp_path_factory.mktemp("auth-keys")
    settings = Settings(
        jwt_private_key_path=directory / "private.pem", jwt_public_key_path=directory / "public.pem"
    )
    assert init_keys(settings)
    original = settings.jwt_private_key_path.read_bytes()
    assert not init_keys(settings)
    assert settings.jwt_private_key_path.read_bytes() == original
    if os.name != "nt":
        assert settings.jwt_private_key_path.stat().st_mode & 0o777 == 0o600
    return settings.jwt_private_key_path, settings.jwt_public_key_path


@pytest.fixture
def client(tmp_path: Path, keys: tuple[Path, Path]) -> Iterator[TestClient]:
    settings = Settings(
        database_url=SecretStr(f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}"),
        jwt_private_key_path=keys[0],
        jwt_public_key_path=keys[1],
        mode="release",
    )
    app = create_app(settings)
    database = cast(Database, app.state.database)

    async def prepare() -> None:
        async with database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        assert await create_user(settings, "admin", "Local Admin", PASSWORD, admin=True)

    with TestClient(app) as test_client:
        assert test_client.portal is not None
        test_client.portal.call(prepare)
        yield test_client


def login(client: TestClient, password: str = PASSWORD, username: str = "admin") -> str:
    result = client.post(
        f"{COOKIE_PATH}/login",
        headers=WRITE_HEADERS,
        json={"username": username, "password": password},
    )
    assert result.status_code == 200, result.text
    token: str = result.json()["data"]["access_token"]
    return token


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_login_cookie_and_public_user_contract(client: TestClient) -> None:
    result = client.post(
        f"{COOKIE_PATH}/login",
        headers=WRITE_HEADERS,
        json={"username": "ADMIN", "password": PASSWORD},
    )
    assert result.status_code == 200
    body = result.json()["data"]
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 900
    assert body["user"]["username"] == "admin"
    assert body["user"]["is_admin"] is True
    cookie = result.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and f"Path={COOKIE_PATH}" in cookie
    assert "Secure" not in cookie
    assert result.headers["Cache-Control"] == "no-store"
    assert PASSWORD not in result.text and "password_hash" not in result.text
    me = client.get("/api/v1/auth/me", headers=bearer(body["access_token"]))
    assert me.status_code == 200 and me.json()["data"] == body["user"]
    assert set(me.json()["data"]) == {"user_id", "username", "name", "is_admin"}
    assert result.headers["X-Request-Id"]


@pytest.mark.parametrize(
    "case", ["missing", "garbage", "expired", "issuer", "audience", "claim", "algorithm"]
)
def test_invalid_bearer_is_unauthorized(client: TestClient, case: str) -> None:
    token = login(client)
    security = cast(Security, cast(FastAPI, client.app).state.security)
    if case == "missing":
        headers: dict[str, str] = {}
    elif case == "garbage":
        headers = bearer("not-a-jwt")
    else:
        claims = jwt.decode(token, options={"verify_signature": False})
        if case == "expired":
            claims["exp"] = utcnow() - timedelta(seconds=1)
        elif case == "issuer":
            claims["iss"] = "other-service"
        elif case == "audience":
            claims["aud"] = "other-client"
        elif case == "claim":
            del claims["staffuserid"]
        assert security.private_key is not None
        modified = (
            jwt.encode(claims, "a-different-hmac-key-for-test-only", algorithm="HS256")
            if case == "algorithm"
            else jwt.encode(claims, security.private_key, algorithm="RS256")
        )
        headers = bearer(modified)
    result = client.get("/api/v1/auth/me", headers=headers)
    assert result.status_code == 401
    assert result.json() == {"code": 401, "msg": "Unauthorized", "data": None}
    assert result.headers["WWW-Authenticate"] == "Bearer"


def test_refresh_rotates_hash_and_logout_revokes_access(client: TestClient) -> None:
    initial = login(client)
    old_cookie = client.cookies.get(COOKIE_NAME)
    refreshed = client.post(f"{COOKIE_PATH}/refresh", headers=WRITE_HEADERS, json={})
    assert refreshed.status_code == 200
    fresh_cookie = client.cookies.get(COOKIE_NAME)
    assert fresh_cookie and fresh_cookie != old_cookie
    fresh_token = refreshed.json()["data"]["access_token"]
    replay = client.post(
        f"{COOKIE_PATH}/refresh",
        headers={**WRITE_HEADERS, "Cookie": f"{COOKIE_NAME}={old_cookie}"},
        json={},
    )
    assert replay.status_code == 401

    async def inspect() -> None:
        database = cast(Database, cast(FastAPI, client.app).state.database)
        async with database.sessions() as session:
            stored = await session.scalar(select(AuthSession))
            assert stored is not None
            assert stored.refresh_hash == token_hash(fresh_cookie)
            assert stored.refresh_hash != fresh_cookie

    assert client.portal is not None
    client.portal.call(inspect)
    assert (
        client.post(
            f"{COOKIE_PATH}/logout", headers={**WRITE_HEADERS, **bearer(fresh_token)}, json={}
        ).status_code
        == 200
    )
    assert client.get("/api/v1/auth/me", headers=bearer(initial)).status_code == 401
    assert client.get("/api/v1/auth/me", headers=bearer(fresh_token)).status_code == 401
    assert client.post(f"{COOKIE_PATH}/refresh", headers=WRITE_HEADERS, json={}).status_code == 401


def test_logout_targets_explicit_bearer_when_shared_cookie_points_to_another_session(
    client: TestClient,
) -> None:
    first = login(client)
    second = login(client)
    second_cookie = client.cookies.get(COOKIE_NAME)
    result = client.post(
        f"{COOKIE_PATH}/logout", headers={**WRITE_HEADERS, **bearer(first)}, json={}
    )
    assert result.status_code == 200
    assert client.cookies.get(COOKIE_NAME) is None
    assert client.get("/api/v1/auth/me", headers=bearer(first)).status_code == 401
    assert client.get("/api/v1/auth/me", headers=bearer(second)).status_code == 200
    # Clearing the shared browser cookie does not revoke the other session's database record.
    assert (
        client.post(
            f"{COOKIE_PATH}/refresh",
            headers={**WRITE_HEADERS, "Cookie": f"{COOKIE_NAME}={second_cookie}"},
            json={},
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    "authorization", ["Bearer", "Basic unsupported", "Bearer malformed", "expired"]
)
def test_logout_falls_back_to_cookie_for_unusable_bearer_and_is_idempotent(
    client: TestClient,
    authorization: str,
) -> None:
    token = login(client)
    if authorization == "expired":
        security = cast(Security, cast(FastAPI, client.app).state.security)
        claims = jwt.decode(token, options={"verify_signature": False})
        claims["exp"] = utcnow() - timedelta(seconds=1)
        assert security.private_key is not None
        authorization = f"Bearer {jwt.encode(claims, security.private_key, algorithm='RS256')}"
    headers = {**WRITE_HEADERS, "Authorization": authorization}
    result = client.post(f"{COOKIE_PATH}/logout", headers=headers, json={})
    assert result.status_code == 200
    assert client.cookies.get(COOKIE_NAME) is None
    assert client.get("/api/v1/auth/me", headers=bearer(token)).status_code == 401
    assert client.post(f"{COOKIE_PATH}/logout", headers=headers, json={}).status_code == 200


def test_password_change_revokes_all_sessions_and_preserves_wrong_password_session(
    client: TestClient,
) -> None:
    first = login(client)
    second = login(client)
    wrong = client.post(
        "/api/v1/auth/password",
        headers={**WRITE_HEADERS, **bearer(second)},
        json={"current_password": "incorrect", "new_password": NEW_PASSWORD},
    )
    assert wrong.status_code == 400
    assert client.get("/api/v1/auth/me", headers=bearer(second)).status_code == 200
    changed = client.post(
        "/api/v1/auth/password",
        headers={**WRITE_HEADERS, **bearer(second)},
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert changed.status_code == 200
    for token in (first, second):
        assert client.get("/api/v1/auth/me", headers=bearer(token)).status_code == 401
    assert (
        client.post(
            f"{COOKIE_PATH}/login",
            headers=WRITE_HEADERS,
            json={"username": "admin", "password": PASSWORD},
        ).status_code
        == 401
    )
    assert login(client, NEW_PASSWORD)


def test_disabled_user_cannot_use_login_access_or_refresh(client: TestClient) -> None:
    token = login(client)

    async def disable() -> None:
        database = cast(Database, cast(FastAPI, client.app).state.database)
        async with database.sessions() as session, session.begin():
            await session.execute(update(LocalUser).values(is_active=False))

    assert client.portal is not None
    client.portal.call(disable)
    assert client.get("/api/v1/auth/me", headers=bearer(token)).status_code == 401
    assert client.post(f"{COOKIE_PATH}/refresh", headers=WRITE_HEADERS, json={}).status_code == 401
    assert (
        client.post(
            f"{COOKIE_PATH}/login",
            headers=WRITE_HEADERS,
            json={"username": "admin", "password": PASSWORD},
        ).status_code
        == 401
    )


def test_expired_session_rejects_unexpired_access_and_refresh(client: TestClient) -> None:
    token = login(client)

    async def expire_session() -> None:
        database = cast(Database, cast(FastAPI, client.app).state.database)
        async with database.sessions() as session, session.begin():
            await session.execute(
                update(AuthSession).values(expires_at=utcnow() - timedelta(seconds=1))
            )

    assert client.portal is not None
    client.portal.call(expire_session)
    assert client.get("/api/v1/auth/me", headers=bearer(token)).status_code == 401
    assert client.post(f"{COOKIE_PATH}/refresh", headers=WRITE_HEADERS, json={}).status_code == 401


def test_password_policy_and_write_headers_are_enforced(client: TestClient) -> None:
    token = login(client)
    payload = {"current_password": PASSWORD, "new_password": "short"}
    assert (
        client.post("/api/v1/auth/password", headers=bearer(token), json=payload).status_code == 403
    )
    assert (
        client.post(
            "/api/v1/auth/password", headers={**WRITE_HEADERS, **bearer(token)}, json=payload
        ).status_code
        == 422
    )
    assert client.get("/api/v1/auth/me", headers=bearer(token)).status_code == 200


def test_login_backoff_persists_and_unknown_user_has_same_error(client: TestClient) -> None:
    responses = [
        client.post(
            f"{COOKIE_PATH}/login",
            headers=WRITE_HEADERS,
            json={"username": "admin", "password": "incorrect"},
        )
        for _ in range(5)
    ]
    locked = client.post(
        f"{COOKIE_PATH}/login",
        headers=WRITE_HEADERS,
        json={"username": "admin", "password": PASSWORD},
    )
    unknown = client.post(
        f"{COOKIE_PATH}/login",
        headers=WRITE_HEADERS,
        json={"username": "not-present", "password": PASSWORD},
    )
    assert all(result.status_code == 401 for result in [*responses, locked, unknown])
    assert locked.json() == unknown.json() == responses[0].json()

    async def inspect_and_unlock() -> None:
        database = cast(Database, cast(FastAPI, client.app).state.database)
        async with database.sessions() as session, session.begin():
            guards = list(await session.scalars(select(LoginThrottle)))
            assert any(guard.failed_count >= 5 and guard.locked_until for guard in guards)
            await session.execute(
                update(LoginThrottle).values(locked_until=utcnow() - timedelta(seconds=1))
            )

    assert client.portal is not None
    client.portal.call(inspect_and_unlock)
    assert login(client)


@pytest.mark.parametrize("endpoint", ["login", "refresh", "logout"])
def test_cookie_auth_rejects_csrf_and_non_json(client: TestClient, endpoint: str) -> None:
    path = f"{COOKIE_PATH}/{endpoint}"
    assert client.post(path, json={}).status_code == 403
    assert (
        client.post(
            path, headers={**WRITE_HEADERS, "Origin": "https://untrusted.example"}, json={}
        ).status_code
        == 403
    )
    assert (
        client.post(path, headers={**WRITE_HEADERS, "Origin": "null"}, json={}).status_code == 403
    )
    assert client.post(path, headers=WRITE_HEADERS, content="username=admin").status_code == 415
    assert (
        client.options(
            path,
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "POST",
            },
        ).status_code
        == 405
    )


def test_bootstrap_user_never_overwrites_existing_identity(client: TestClient) -> None:
    settings = cast(Settings, cast(FastAPI, client.app).state.settings)

    async def attempt_overwrite() -> None:
        assert not await create_user(settings, "admin", "Changed", NEW_PASSWORD, admin=False)

    assert client.portal is not None
    client.portal.call(attempt_overwrite)
    token = login(client)
    result = client.get("/api/v1/auth/me", headers=bearer(token))
    assert result.json()["data"]["name"] == "Local Admin"
    assert result.json()["data"]["is_admin"] is True


def test_missing_keys_leaves_health_alive_and_auth_closed(tmp_path: Path) -> None:
    app = create_app(Settings(jwt_private_key_path=tmp_path / "absent.pem"))
    with TestClient(app) as client:
        assert client.get("/api/v1/pub/health").status_code == 200
        assert (
            client.post(
                f"{COOKIE_PATH}/login",
                headers=WRITE_HEADERS,
                json={"username": "admin", "password": PASSWORD},
            ).status_code
            == 503
        )


def test_concurrent_refresh_only_one_token_is_issued(client: TestClient) -> None:
    login(client)
    cookie = client.cookies.get(COOKIE_NAME)

    async def race() -> None:
        async with AsyncClient(
            transport=ASGITransport(app=client.app), base_url="http://test"
        ) as transport:
            responses = await asyncio.gather(
                *(
                    transport.post(
                        f"{COOKIE_PATH}/refresh",
                        json={},
                        headers={**WRITE_HEADERS, "Cookie": f"{COOKIE_NAME}={cookie}"},
                    )
                    for _ in range(2)
                )
            )
        assert sorted(result.status_code for result in responses) == [200, 401]

    assert client.portal is not None
    client.portal.call(race)
