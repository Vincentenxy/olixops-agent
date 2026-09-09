"""Exercise an explicitly configured local/CI API using a disposable test account."""

import http.cookiejar
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any


def main() -> None:
    base = os.environ.get("OLIXOPS_CHECK_URL", "http://127.0.0.1:8000").rstrip("/")
    username = os.environ["OLIXOPS_CHECK_USERNAME"]
    password = os.environ["OLIXOPS_CHECK_PASSWORD"]
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )

    def call(
        path: str, body: dict[str, str] | None = None, token: str | None = None
    ) -> tuple[int, Any]:
        headers = {"X-Olixops-Client": "web", "X-Request-Id": "container-check"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = "Bearer " + token
        request = urllib.request.Request(
            base + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
        )
        try:
            result = opener.open(request, timeout=5)
        except urllib.error.HTTPError as exc:
            result = exc
        with result:
            assert result.headers["X-Request-Id"] == "container-check"
            return result.status, json.load(result)

    for attempt in range(20):
        try:
            if call("/api/v1/pub/ready")[0] == 200:
                break
        except urllib.error.URLError:
            pass
        if attempt == 19:
            raise SystemExit("API did not become ready")
        time.sleep(0.5)
    status, data = call("/api/v1/pub/auth/login", {"username": username, "password": password})
    assert status == 200 and data["code"] == 0, "Login failed"
    token = data["data"]["access_token"]
    assert call("/api/v1/auth/me", token=token)[1]["data"]["username"] == username
    status, data = call("/api/v1/system/status", token=token)
    assert status == 200
    assert all(data["data"][key]["status"] == "ok" for key in ("database", "auth", "pulumi"))
    assert data["data"]["redis"]["status"] in {"ok", "disabled"}
    status, data = call("/api/v1/pub/auth/refresh", {})
    assert status == 200 and data["data"]["access_token"] != token
    token = data["data"]["access_token"]
    assert call("/api/v1/pub/auth/logout", {}, token)[0] == 200
    assert call("/api/v1/auth/me", token=token)[0] == 401
    assert call("/api/v1/pub/auth/refresh", {})[0] == 401
    print("API readiness, login, system diagnostics, refresh and logout checks passed.")


if __name__ == "__main__":
    main()
