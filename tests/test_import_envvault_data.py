#!/usr/bin/env python3
"""Create a sizeable, deterministic Env Vault data set through the HTTP API.

The program intentionally uses only the standard library so it can be run from
the repository or from a small utility container without installing requests.
It creates resources in dependency order and never writes directly to the DB.
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import hashlib
import json
import os
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://localhost:8090/api/v1"
ENV_CODES = ("poc", "dev", "test", "sim", "prod")
TAG_SPECS = (
    ("ip", "IP 地址", True),
    ("domain", "域名", True),
    ("db", "数据库", True),
    ("password", "密码", False),
    ("username", "用户名", True),
    ("port", "端口", True),
    ("url", "URL", True),
    ("token", "令牌", False),
    ("kafka", "Kafka", True),
    ("redis", "Redis", True),
    ("app", "应用配置", True),
    ("config", "通用配置", True),
)


class APIError(RuntimeError):
    """An API failure without echoing request data or secret values."""

    def __init__(self, method: str, path: str, status: int, message: str):
        super().__init__(f"{method} {path} failed ({status}): {message}")
        self.method = method
        self.path = path
        self.status = status


class APIClient:
    def __init__(self, base_url: str, token: str, timeout: float, retries: int):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.retries = max(0, retries)

    def call(self, method: str, path: str, body: Optional[dict[str, Any]] = None) -> Any:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        url = f"{self.base_url}/{path.lstrip('/')}"
        attempts = self.retries + 1
        for attempt in range(attempts):
            request = Request(
                url,
                data=payload,
                method=method,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.token}",
                    "X-Request-Id": str(uuid.uuid4()),
                },
            )
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    status = response.status
                    raw = response.read()
                return self._decode(method, path, status, raw)
            except HTTPError as exc:
                # Do not retry POST by default: a timeout can happen after the
                # server committed the record and retrying would create dupes.
                if attempt + 1 < attempts and exc.code >= 500:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raw = exc.read()
                message = self._error_message(raw) or exc.reason or "HTTP error"
                raise APIError(method, path, exc.code, message) from exc
            except (URLError, TimeoutError, OSError) as exc:
                if attempt + 1 < attempts:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise APIError(method, path, 0, str(exc)) from exc

        raise AssertionError("unreachable")

    @staticmethod
    def _error_message(raw: bytes) -> str:
        try:
            value = json.loads(raw.decode("utf-8"))
            if isinstance(value, dict):
                return str(value.get("msg") or value.get("message") or "")
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        return ""

    @classmethod
    def _decode(cls, method: str, path: str, status: int, raw: bytes) -> Any:
        try:
            envelope = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise APIError(method, path, status, "response is not JSON") from exc
        if not isinstance(envelope, dict):
            raise APIError(method, path, status, "invalid response envelope")
        if envelope.get("code") != 0:
            raise APIError(method, path, status, str(envelope.get("msg") or "request failed"))
        return envelope.get("data")


@dataclass(frozen=True)
class ProjectContext:
    tenant_index: int
    org_index: int
    project_index: int
    tenant_id: str
    org_id: str
    project_id: str
    envs: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class FolderContext:
    project: ProjectContext
    code: str
    group_id: str
    folder_id: str


class Progress:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {}

    def add(self, name: str, amount: int = 1) -> int:
        with self._lock:
            self._counts[name] = self._counts.get(name, 0) + amount
            return self._counts[name]

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)

    def report(self, label: str) -> None:
        values = self.snapshot()
        summary = ", ".join(f"{key}={value}" for key, value in sorted(values.items()))
        print(f"[{label}] {summary}", flush=True)


def normalize_base_url(value: str) -> str:
    base = value.rstrip("/")
    if not base.endswith("/api/v1"):
        base += "/api/v1"
    return base


def jwt_staff_user_id(token: str) -> str:
    """Read a manager hint from JWT without treating it as authentication."""
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        claims = json.loads(base64.urlsafe_b64decode(part).decode("utf-8"))
        return str(claims.get("staffuserid") or claims.get("sub") or "")
    except (IndexError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return ""


def require_id(data: Any, resource: str) -> str:
    if not isinstance(data, dict) or not data.get("id"):
        raise RuntimeError(f"{resource} response did not contain an id")
    return str(data["id"])


def require_list(data: Any, resource: str) -> list[dict[str, Any]]:
    if not isinstance(data, list):
        raise RuntimeError(f"{resource} response was not a list")
    return [item for item in data if isinstance(item, dict)]


def create_tags(client: APIClient, tenant_id: str, run_id: str, progress: Progress) -> dict[str, str]:
    result: dict[str, str] = {}
    for code, name, allow_search in TAG_SPECS:
        data = client.call(
            "POST",
            "/tag/create",
            {
                "tenantId": tenant_id,
                # Tags are tenant-scoped, so keep the conventional codes
                # (ip/domain/db/password/username...) that test queries expect.
                # The tenant itself contains the run-id and is unique per run.
                "code": code,
                "name": name,
                "remark": "自动生成的测试标签",
                "allowValueSearch": allow_search,
            },
        )
        result[code] = require_id(data, "tag")
        progress.add("tags")
    return result


def create_tenant(client: APIClient, index: int, run_id: str, manager_id: str, progress: Progress) -> tuple[str, dict[str, str]]:
    data = client.call(
        "POST",
        "/tenant/create",
        {
            "code": f"seed-{run_id}-tenant-{index:02d}",
            "name": f"测试租户 {index:02d}",
            "remark": "自动生成的测试租户",
            "manager": manager_id,
        },
    )
    tenant_id = require_id(data, "tenant")
    progress.add("tenants")
    tags = create_tags(client, tenant_id, run_id, progress)
    if manager_id:
        client.call("POST", "/user/allocate", {"type": "tenant", "operate": "add", "resourceId": tenant_id, "userIdList": [manager_id]})
    return tenant_id, tags


def create_org(client: APIClient, tenant_id: str, tenant_index: int, index: int, run_id: str, manager_id: str, progress: Progress) -> tuple[str, int, int]:
    data = client.call(
        "POST",
        "/organization/create",
        {
            "tenantId": tenant_id,
            "code": f"seed-{run_id}-t{tenant_index:02d}-org-{index:02d}",
            "name": f"测试组织 {tenant_index:02d}-{index:02d}",
            "remark": "自动生成的测试组织",
            "manager": manager_id,
        },
    )
    org_id = require_id(data, "organization")
    if manager_id:
        client.call("POST", "/user/allocate", {"type": "org", "operate": "add", "resourceId": org_id, "userIdList": [manager_id]})
    progress.add("organizations")
    return org_id, tenant_index, index


def create_project(client: APIClient, tenant_index: int, org_index: int, org_id: str, project_index: int, run_id: str, manager_id: str, progress: Progress) -> ProjectContext:
    environments = [
        {"code": code, "name": code.upper(), "remark": "自动生成的测试环境", "isCheckPerm": False}
        for code in ENV_CODES
    ]
    data = client.call(
        "POST",
        "/project/create",
        {
            "orgId": org_id,
            "code": f"seed-{run_id}-t{tenant_index:02d}-o{org_index:02d}-project-{project_index:02d}",
            "name": f"测试项目 {tenant_index:02d}-{org_index:02d}-{project_index:02d}",
            "remark": "自动生成的测试项目",
            "manager": manager_id,
            "environments": environments,
        },
    )
    project_id = require_id(data, "project")
    env_data = require_list(client.call("POST", "/environment/list", {"projectId": project_id}), "environment")
    env_data.sort(key=lambda item: (item.get("orderNo", 0), item.get("code", "")))
    if len(env_data) < len(ENV_CODES):
        raise RuntimeError(f"project {project_id} returned fewer environments than expected")
    progress.add("projects")
    return ProjectContext(tenant_index, org_index, project_index, "", org_id, project_id, tuple(env_data[: len(ENV_CODES)]))


TOP_FOLDERS = (
    ("global", "全局配置", "common"),
    ("groups", "公共配置", "common"),
    ("eff-netf-api", "Netf API", "customer"),
    ("devops-adv-backend", "DevOps 后端", "customer"),
    ("eff-user-cfg", "用户配置", "customer"),
)
GROUP_CHILDREN = (("db", "数据库配置"), ("kafka", "Kafka 配置"), ("redis", "Redis 配置"))


def create_folder(client: APIClient, project: ProjectContext, code: str, name: str, folder_type: str, parent_id: Optional[str], progress: Progress) -> FolderContext:
    body: dict[str, Any] = {"code": code, "name": name, "remark": "自动生成的测试文件夹", "type": folder_type}
    if parent_id:
        body["parentFolderId"] = parent_id
    else:
        body["projectId"] = project.project_id
    items = require_list(client.call("POST", "/folder/create", body), "folder")
    if not items or not items[0].get("groupId") or not items[0].get("id"):
        raise RuntimeError(f"folder {code} did not return groupId/id")
    progress.add("folders")
    return FolderContext(project, code, str(items[0]["groupId"]), str(items[0]["id"]))


def create_project_folders(client: APIClient, project: ProjectContext, progress: Progress) -> list[FolderContext]:
    folders: list[FolderContext] = []
    groups_parent: Optional[str] = None
    for code, name, folder_type in TOP_FOLDERS:
        folder = create_folder(client, project, code, name, folder_type, None, progress)
        folders.append(folder)
        if code == "groups":
            # The API returns one row per environment; the first row id is the
            # parent folder id accepted by the child-folder endpoint.
            groups_parent = folder.folder_id
    if groups_parent:
        for code, name in GROUP_CHILDREN:
            folders.append(create_folder(client, project, code, name, "common", groups_parent, progress))
    return folders


def secret_specs(folder_code: str) -> tuple[tuple[str, str, str], ...]:
    if folder_code == "global":
        return (("APP_IP", "应用 IP", "ip"), ("APP_DOMAIN", "应用域名", "domain"), ("APP_URL", "应用地址", "url"), ("APP_PORT", "应用端口", "port"), ("APP_USERNAME", "应用用户名", "username"))
    if folder_code == "groups":
        return (("SHARED_DB", "共享数据库", "db"), ("SHARED_KAFKA", "共享 Kafka", "kafka"), ("SHARED_REDIS", "共享 Redis", "redis"), ("SHARED_DOMAIN", "共享域名", "domain"), ("SHARED_TOKEN", "共享令牌", "token"))
    if folder_code == "db":
        return (("DB_HOST", "数据库地址", "ip"), ("DB_PORT", "数据库端口", "port"), ("DB_NAME", "数据库名称", "db"), ("DB_USERNAME", "数据库用户名", "username"), ("DB_PASSWORD", "数据库密码", "password"))
    if folder_code == "kafka":
        return (("KAFKA_BROKER", "Kafka 地址", "domain"), ("KAFKA_PORT", "Kafka 端口", "port"), ("KAFKA_USERNAME", "Kafka 用户名", "username"), ("KAFKA_PASSWORD", "Kafka 密码", "password"), ("KAFKA_TOPIC", "Kafka 主题", "config"))
    if folder_code == "redis":
        return (("REDIS_HOST", "Redis 地址", "ip"), ("REDIS_PORT", "Redis 端口", "port"), ("REDIS_DB", "Redis 数据库", "db"), ("REDIS_USERNAME", "Redis 用户名", "username"), ("REDIS_PASSWORD", "Redis 密码", "password"))
    return (("SERVICE_IP", "服务 IP", "ip"), ("SERVICE_DOMAIN", "服务域名", "domain"), ("SERVICE_DB", "服务数据库", "db"), ("SERVICE_USERNAME", "服务用户名", "username"), ("SERVICE_PASSWORD", "服务密码", "password"))


def fake_value(run_id: str, project: ProjectContext, folder_code: str, key: str, env_index: int, tag: str) -> str:
    seed = f"{run_id}-{project.tenant_index}-{project.org_index}-{project.project_index}-{folder_code}-{key}-{env_index}"
    if tag == "ip":
        return f"10.{project.tenant_index}.{project.org_index}.{(project.project_index + env_index) % 250 + 1}"
    if tag == "domain":
        return f"{folder_code}.{ENV_CODES[env_index]}.tenant{project.tenant_index}.example.test"
    if tag == "url":
        return f"https://{folder_code}.{ENV_CODES[env_index]}.example.test/api"
    if tag == "port":
        return str(8000 + env_index)
    if tag == "db":
        return f"seed_db_{project.tenant_index}_{project.org_index}_{env_index}"
    if tag == "username":
        return f"seed_user_{project.tenant_index}_{project.org_index}"
    if tag == "password":
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8]
        return f"SeedOnly-{digest}!"
    if tag == "token":
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
        return f"seed-token-{digest}"
    if tag == "kafka":
        return f"kafka-{ENV_CODES[env_index]}.example.test:9092"
    if tag == "config":
        return f"seed-{ENV_CODES[env_index]}-config"
    return seed


def create_folder_secrets(client: APIClient, folder: FolderContext, run_id: str, progress: Progress) -> list[tuple[str, str]]:
    logical: list[dict[str, Any]] = []
    specs = secret_specs(folder.code)
    tag_by_key = {key: tag for key, _, tag in specs}
    for key, remark, tag in specs:
        logical.append({
            "folderGroupId": folder.group_id,
            "key": key,
            "remark": remark,
            "values": [
                {"envId": env["id"], "value": fake_value(run_id, folder.project, folder.code, key, index, tag)}
                for index, env in enumerate(folder.project.envs)
            ],
        })
    data = require_list(client.call("POST", "/secret/create", {"secretList": logical}), "secret")
    progress.add("secrets", len(logical))
    return [(str(item["groupId"]), tag_by_key.get(str(item.get("key")), "config")) for item in data if item.get("groupId")]


def bind_secret_tags(client: APIClient, group_id: str, tag_ids: dict[str, str], tag_code: str, progress: Progress) -> None:
    client.call("POST", "/secret/tag/update", {"groupId": group_id, "tagIdList": [tag_ids[tag_code]]})
    progress.add("tag_bindings")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("ENV_VAULT_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--token", default=os.getenv("ENV_VAULT_TOKEN", ""), help="JWT; can also be set through ENV_VAULT_TOKEN")
    parser.add_argument("--manager-id", default=os.getenv("ENV_VAULT_MANAGER_ID", ""))
    parser.add_argument("--tenants", type=int, default=10)
    parser.add_argument("--orgs-per-tenant", type=int, default=5)
    parser.add_argument("--projects-per-org", type=int, default=5)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--retries", type=int, default=0, help="Retry transport/5xx failures; keep 0 for non-idempotent POST safety")
    parser.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%y%m%d%H%M%S"))
    parser.add_argument("--skip-tag-bindings", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def print_plan(args: argparse.Namespace) -> None:
    projects = args.tenants * args.orgs_per_tenant * args.projects_per_org
    folder_groups = projects * (len(TOP_FOLDERS) + len(GROUP_CHILDREN))
    logical_secrets = folder_groups * 5
    physical_values = logical_secrets * len(ENV_CODES)
    print("测试数据计划:")
    print(f"  tenants={args.tenants}, organizations={args.tenants * args.orgs_per_tenant}, projects={projects}")
    print(f"  environments={projects * len(ENV_CODES)}, folderGroups={folder_groups}")
    print(f"  logicalSecrets={logical_secrets}, environmentValues={physical_values}")
    print(f"  tags={args.tenants * len(TAG_SPECS)}, tagBindings={'跳过' if args.skip_tag_bindings else logical_secrets}")


def run(args: argparse.Namespace) -> None:
    if args.tenants <= 0 or args.orgs_per_tenant <= 0 or args.projects_per_org <= 0:
        raise ValueError("tenants/orgs-per-tenant/projects-per-org must be positive")
    if args.workers <= 0:
        raise ValueError("workers must be positive")
    print_plan(args)
    if args.dry_run:
        return
    if not args.token:
        raise ValueError("missing JWT: set ENV_VAULT_TOKEN or pass --token")

    manager_id = args.manager_id or jwt_staff_user_id(args.token)
    if not manager_id:
        raise ValueError("missing manager id: set ENV_VAULT_MANAGER_ID or use a JWT with staffuserid/sub")
    client = APIClient(normalize_base_url(args.base_url), args.token, args.timeout, args.retries)
    progress = Progress()
    tenants: list[tuple[str, dict[str, str]]] = []
    print(f"开始创建测试数据，run-id={args.run_id}; 不会输出 JWT 或密钥值。", flush=True)

    for index in range(1, args.tenants + 1):
        tenants.append(create_tenant(client, index, args.run_id, manager_id, progress))
    progress.report("tenants ready")

    org_jobs: list[tuple[str, int, int]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(create_org, client, tenant_id, tenant_index, org_index, args.run_id, manager_id, progress)
                   for tenant_index, (tenant_id, _) in enumerate(tenants, 1)
                   for org_index in range(1, args.orgs_per_tenant + 1)]
        for future in concurrent.futures.as_completed(futures):
            org_jobs.append(future.result())
    progress.report("organizations ready")

    projects: list[ProjectContext] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(create_project, tenant_index, org_index, org_id, project_index, args.run_id, manager_id, progress)
                   for org_id, tenant_index, org_index in org_jobs
                   for project_index in range(1, args.projects_per_org + 1)]
        for future in concurrent.futures.as_completed(futures):
            project = future.result()
            tenant_id = tenants[project.tenant_index - 1][0]
            projects.append(ProjectContext(project.tenant_index, project.org_index, project.project_index, tenant_id, project.org_id, project.project_id, project.envs))
    progress.report("projects ready")

    folders: list[FolderContext] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(create_project_folders, client, project, progress) for project in projects]
        for future in concurrent.futures.as_completed(futures):
            folders.extend(future.result())
    progress.report("folders ready")

    secret_groups: list[tuple[str, str, int]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [(pool.submit(create_folder_secrets, client, folder, args.run_id, progress), folder.project.tenant_index) for folder in folders]
        for future, tenant_index in futures:
            for group_id, folder_code in future.result():
                secret_groups.append((group_id, folder_code, tenant_index))
    progress.report("secrets ready")

    if not args.skip_tag_bindings:
        unique_groups = {(group_id, tag_code, tenant_index) for group_id, tag_code, tenant_index in secret_groups}
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(bind_secret_tags, client, group_id, tenants[tenant_index - 1][1], tag_code, progress)
                       for group_id, tag_code, tenant_index in unique_groups]
            for future in concurrent.futures.as_completed(futures):
                future.result()
    progress.report("done")
    print("测试数据创建完成。失败时不会自动回滚，请记录 run-id 后按业务清理。", flush=True)


def main() -> int:
    try:
        args = parse_args()
        run(args)
        return 0
    except (APIError, RuntimeError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        print("说明：脚本不执行自动回滚；未输出请求体和密钥明文。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
