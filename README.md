# olixops-agent

通过自然语言分析应用需求、查询 MCP 信息、生成 Terraform 配置并组织部署的 DevOps 智能体后端。

本 README 是后端项目后续开发和代码评审的规范入口。接口、认证、数据库和日志约定同时作为前后端联调契约；下文明确区分已实现能力与后续架构要求，待接入事项统一记录在 [todo.md](todo.md)。

## 仓库与当前状态

- `olixops-agent/`：Python 后端、Agent 工作流、MCP 查询适配和 Terraform Worker。
- `olixops-agent-web/`：独立前端项目，通过后端 API 提交需求、查看变更和部署结果。
- 当前已实现：FastAPI 应用、公开健康检查、统一响应与 HTTP 错误处理、请求追踪、应用日志、uv 锁文件、质量检查及 API 容器配置。
- 当前唯一业务 API 是 `GET /api/v1/pub/health`；JWT、数据库、Agent、MCP 和 Terraform Worker 尚未接入，暂不提供受保护业务接口或部署接口。
- 后续开发先阅读本 README，再读取实际存在且适用于修改目录的 `AGENTS.md`。新增专项设计文档时，在对应规范处补充入口。

## 技术栈与环境管理

| 组件 | 目标选型 / 约定 |
|------|----------------|
| Python | CPython 3.14 系列，接入依赖时验证兼容性 |
| 项目管理 | uv；`pyproject.toml` 声明依赖，`uv.lock` 锁定解析结果 |
| Web | FastAPI + Uvicorn，Pydantic 定义输入、输出和配置模型 |
| Agent | LangGraph，持久化工作流进度 |
| 工具查询 | MCP 客户端 / 适配层，对接现有查询能力 |
| IaC | Terraform CLI，由独立 Worker 执行 |
| 数据 | PostgreSQL 持久化；Redis 用于缓存 |
| 质量检查 | Ruff 检查与格式化、mypy 类型检查、pytest 测试 |
| 部署 | Docker 容器化；开发环境采用 Docker Compose，目标部署于 Kubernetes |

运行环境已切换为 CPython 3.14，补丁版本由 `.python-version` 固定，容器镜像同步使用该版本。已有 Python 3.9 环境会在 `uv sync` 时被替换为符合项目约束的环境。FastAPI、Pydantic 与质量工具的实际版本由 `uv.lock` 锁定；LangGraph、MCP、数据库及 Terraform 仍为后续接入目标。

- 统一使用 uv 管理依赖和运行项目命令；通过 `uv add` / `uv add --dev` 更新声明与锁文件。
- 提交 `pyproject.toml`、`uv.lock`、`.python-version`；`.venv/`、本地密钥、真实 `.env` 和工具缓存加入忽略规则。
- 开发环境从锁文件同步依赖；CI 和镜像构建使用 `uv sync --locked`，及时发现依赖声明与锁文件不一致。
- Python 补丁版本、依赖版本和质量工具配置以项目配置文件为准；升级时同步验证测试和镜像构建。

## 目录与职责

以下为目标结构，目录随对应功能引入，不要求预先创建空模块：

```text
olixops-agent/
├── app/
│   ├── main.py             # FastAPI 应用工厂、路由与生命周期
│   ├── api/                # 路由、认证依赖、请求与响应适配
│   ├── core/               # 配置、日志、错误与请求上下文
│   ├── schemas/            # Pydantic 请求与响应模型
│   ├── services/           # 业务用例与事务边界
│   ├── repositories/       # 数据访问
│   ├── models/             # 数据库模型
│   ├── agents/             # LangGraph 状态、节点和工作流
│   ├── integrations/mcp/   # MCP 查询适配
│   └── workers/            # 部署任务领取、Terraform 执行与结果回收
├── terraform/              # 可复用模块和模板；运行产物另行保存
├── migrations/             # 数据库版本迁移
├── tests/                  # 单元和集成测试
├── design/                 # 接口、数据与部署设计
├── pyproject.toml
├── uv.lock
├── Dockerfile
└── README.md
```

路由负责协议适配，业务逻辑放入 service；数据库访问集中在 repository。Agent 节点调用明确的业务和工具接口，Terraform 子进程由 Worker 管理。前端代码保存在 `olixops-agent-web/`。

## Python 编码规范

- 模块、文件、函数、变量、数据库表和字段使用 `snake_case`；类使用 `PascalCase`；常量使用 `UPPER_SNAKE_CASE`。
- 使用 4 个空格缩进，格式与导入排序交由 Ruff 管理，规则集中配置在 `pyproject.toml`。
- 新增函数标注参数和返回类型；跨模块的数据结构使用 Pydantic 模型、dataclass 或明确类型，避免用无结构字典承载业务契约。
- API 请求和响应使用明确的 Pydantic 模型，显式选择对外字段；数据库对象和内部上下文通过映射后再返回。
- 路由通过 FastAPI `Depends` 获取当前用户、数据库会话和业务依赖；初始化与清理由应用生命周期统一管理。
- `async def` 中使用异步 I/O 客户端；同步数据库、阻塞文件操作和子进程等待交给合适的执行层，避免阻塞事件循环。
- 捕获可处理的具体异常，使用 `raise ... from exc` 保留原因；未预期异常由统一入口记录并映射为 HTTP 500。资源使用上下文管理器及时释放。
- 配置集中加载并校验，通过环境变量或挂载配置注入；配置示例只包含字段说明和占位值。
- 注释说明业务约束和设计原因，公开接口的 docstring 描述输入、输出及异常。

## 接口设计规范

### 路径与方法

所有业务接口统一使用 `/api/[版本号]/[pub]/xxx/xxx`：

- `/api/v1/pub/...`：无认证接口，显式注册；公开接口仍进行输入校验。
- `/api/v1/...`（不带 `pub`）：认证接口，请求头携带 `Authorization: Bearer <token>`。
- 业务接口只使用 GET / POST：带参数的接口统一使用 POST；不带参数或用于分享的链接使用 GET。GET 保持只读，部署、取消等操作使用 POST。
- 浏览器 CORS 的 OPTIONS 预检由中间件处理，不作为业务接口。

### 统一响应

业务接口的 JSON 响应，包括错误响应，统一为：

```json
{"code": 0, "msg": "", "data": {}}
```

| code | 含义 |
|------|------|
| `0` | 成功 |
| `-1` | 通用业务失败 |
| `1 ~ 1000` | 系统预留失败码；600 以内与 HTTP 状态码保持一致，不用于自定义业务错误 |
| `10000+` | 业务失败码，新增时记录业务含义及分段 |

成功和可预期的业务结果使用 HTTP 200，通过 `code` 区分；HTTP 错误使用对应的 HTTP 状态。未处理异常使用 HTTP 500，不包装成 HTTP 200 的通用业务失败。

HTTP 400 / 401 / 403 / 404 / 405 / 422 / 500 等错误，`code` 必须等于实际状态码，`msg` 使用 Python `http.HTTPStatus(status_code).phrase`，`data` 为 `null`。例如：

```json
{"code": 401, "msg": "Unauthorized", "data": null}
```

统一响应封装归入 `app/core/response.py`，统一异常处理归入 `app/core/exceptions.py`。模块实现时覆盖 Starlette `HTTPException`、FastAPI `RequestValidationError` 和未处理异常；框架产生的 404、405、422 也遵守该契约。保留认证错误所需的 `WWW-Authenticate` 等响应头。

响应辅助函数已在 `app/core/response.py` 实现；业务错误码仅接受 `-1` 或 `10000+`：

```python
from app.core import response

response.success(data={"task_id": "example-task"})
response.fail(code=10001, msg="部署目标不存在")
response.error(msg="操作失败")
response.http_error(status_code=401)
```

业务提示通过已定义的业务码表达；HTTP 错误正文使用标准文本，详细异常记录在日志中。

### OpenAPI 与前端联调

- 请求参数、成功响应、业务码及 HTTP 错误模型同步到 OpenAPI；对外分发从实际应用导出的 OpenAPI 文档。
- OpenAPI 导出保留规范要求的文档结构，不套用业务响应封装。文档访问权限和部署暴露方式在应用配置中明确。
- 接口契约变更同时更新模型、测试及接口文档，并在涉及前端时同步 `olixops-agent-web`。

## 认证与用户上下文

以下是接入业务接口时必须实现的认证约定；当前仅开放健康检查，JWT 验签与用户解析尚未实现。

- 使用 Bearer JWT 和 RSA 公钥验签；算法允许列表为 RS256 / RS384 / RS512，实际验证使用服务端配置的固定列表。
- 公钥通过配置注入，兼容 base64 编码的 DER 公钥及 PEM 文本；配置模型在启动时解析和校验。
- 认证接口通过统一 FastAPI 依赖完成验签及用户解析；缺失 token、格式错误、验签失败、token 过期或缺少必需用户标识时，统一返回 HTTP 401 和上述错误结构。
- 精确按路由分组区分公开与认证接口；有效身份访问无权限资源时返回 HTTP 403。

用户上下文字段遵守 Python 命名，保留现有 JWT claims 映射：

| 字段 | 来源 | 用途 |
|------|------|------|
| `user_id` | claims.`staffuserid` | 当前用户 ID |
| `name` | claims.`name` | 用户姓名 |
| `jwt` | 原始 token | 按下游认证约定透传 |
| `cookie` | 请求头 `Cookie` | 按下游认证约定透传 |

当前用户由类型明确的对象承载，通过 `Depends(get_current_user)` 注入业务入口；需要中间件共享时放入 `request.state`。向已配置且需要用户身份的下游服务透传 Bearer token / Cookie，日志和对外用户响应只选择必要的非凭证字段。

## 数据库规范

以下为后续持久化约定；当前骨架运行不依赖 PostgreSQL 或 Redis。

- PostgreSQL 保存业务数据和任务状态；Redis 用于缓存，不作为部署任务的唯一持久化来源。
- 所有业务表设计记录在 `design/database.md`，使用 Markdown 与 SQL 代码块。该文件在首次数据库设计时创建，结构变更同步更新设计和版本迁移。
- 所有业务表包含 `create_at` / `update_at` / `create_by` / `update_by`，保留这些字段名。外部组件自管的表遵循其迁移机制。
- 时间字段使用带时区时间，统一保存 UTC；创建人和更新人来自已认证用户，系统任务的操作者取值在表设计中明确。
- 表名、列名、索引名使用 `snake_case`；查询使用参数绑定，事务边界由业务用例管理。
- 数据库结构通过版本迁移演进，并在变更中说明数据兼容及回退方式。

## 日志与请求追踪

- 统一使用 Python `logging`；模块通过 `logging.getLogger(__name__)` 获取 logger，格式器和上下文过滤器集中配置。
- debug 模式输出带颜色的可读文本，INFO 使用蓝绿色、ERROR 使用红色；release 模式输出 JSON，便于采集。时间使用带时区的 ISO 8601 格式。
- 请求入口读取 `X-Request-Id`：携带则透传，未携带则生成 32 位十六进制 ID；响应头回写同名字段。
- 使用 `contextvars.ContextVar` 管理当前执行上下文的 `trace_id`，请求结束时重置；日志有 trace ID 时输出，无值时省略。
- HTTP 访问日志包含 `method`、`path`、`status_code`、`duration_ms`、`client_ip`；部署日志补充 `task_id` 和 `step`。
- 下游 HTTP 请求继续透传 `X-Request-Id`。跨进程 Worker 通过任务记录显式接收 `trace_id` 和 `task_id`，在执行入口绑定，结束后清理。

日志初始化、上下文注入和格式器已实现；用法示例：

```python
import logging

logger = logging.getLogger(__name__)
logger.info("server started", extra={"port": 8000})
logger.info("deployment step finished", extra={"task_id": "example-task", "step": "plan"})
logger.warning("MCP query timed out", extra={"server_name": "inventory"})
```

日志级别统一使用 `debug` / `info` / `warning` / `error`；在异常处理块内使用 `logger.exception` 记录堆栈。过滤 Authorization、Cookie、密钥及 Terraform 输出中的敏感值。

## Agent 与 Terraform 执行规范

- MCP 当前提供信息查询；Agent 负责理解需求和生成配置，实际 Terraform 操作由 Worker 执行。
- 优先生成类型明确的部署规格，再选用可复用 Terraform 模块并生成配置；部署任务记录应用代码版本、模块版本和输入参数引用。
- Terraform 流程按 `init → validate → plan → apply → 验证结果` 组织；执行器使用参数列表启动子进程，固定 Terraform / Provider 版本，并设置超时和退出处理。
- `plan` 保存为任务产物；`apply` 执行该任务对应的保存计划。需要人工审核时，审核结果绑定具体计划；计划或配置变化后重新生成并按环境授权策略处理。
- 每次运行使用独立工作目录；同一套资源的变更串行协调，Terraform 使用支持锁定的远程状态后端。运行生成的 state、plan 和 `.terraform/` 不提交到 Git。
- LangGraph checkpoint、业务任务状态与 Terraform state 分别保存；Worker 重启或调用超时后，先核对已执行结果，再决定恢复或重试。
- 长任务提交后返回 `task_id`，由后端持续执行；客户端断开不等于取消。取消请求由 Worker 协调子进程结束并记录实际结果。
- IaC 管理基础设施资源；需要构建镜像时由独立构建步骤生成镜像及固定标识，再交给部署步骤使用。

## 开发与验证流程

1. 阅读本 README、相关设计和当前代码，确认任务范围及工作区已有改动。
2. 涉及接口、数据结构、状态流转的变更，先明确契约，再实现相应模块并同步文档。
3. 新增或变更行为使用 pytest 验证可观察结果；覆盖认证、统一错误、请求 ID、MCP 失败、Terraform 失败及恢复等相关路径。
4. 单元测试使用可控的外部接口替身；集成测试覆盖实际组件协作。真实云部署验证单独配置目标与凭据，并在任务授权范围内执行，分别报告模拟验证与真实验证结果。
5. 完成适用于改动的检查，修复本次引入的问题；报告实际执行的检查及未执行原因。纯文档变更检查内容、示例和链接。
6. 按任务要求提交本次改动，使用 `feat:` / `fix:` / `docs:` / `refactor:` / `test:` / `chore:` 描述提交目的，保留已有无关改动。

首次运行（需要已安装 uv）：

```bash
uv sync --locked
cp .env.example .env
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

IDE 选择项目 `.venv/bin/python`。也可以使用 `uv run python main.py`，该入口读取 `OLIXOPS_HOST` / `OLIXOPS_PORT`。直接运行 Uvicorn 时监听地址和端口使用其命令行参数。

健康检查：

```bash
curl -i http://127.0.0.1:8000/api/v1/pub/health
```

成功正文为 `{"code":0,"msg":"","data":{"status":"ok","service":"olixops-agent"}}`，响应头包含 `X-Request-Id`。该接口只验证 API 进程存活；尚未接入的数据库、MCP 或 Worker 不在检查范围内。

前端开发服务器将 `/api` 代理到 `http://127.0.0.1:8000`；生产环境由前端反向代理转发同一路径，使用同源访问。

配置项（全部带 `OLIXOPS_` 前缀，完整定义见 `app/core/config.py`）：

| 环境变量 | 默认值 | 用途 |
|---|---|---|
| `OLIXOPS_MODE` | `debug` | `debug` 为彩色文本日志，`release` 为 JSON 日志 |
| `OLIXOPS_HOST` | `127.0.0.1` | `main.py` 启动入口监听地址 |
| `OLIXOPS_PORT` | `8000` | `main.py` 启动入口端口 |
| `OLIXOPS_DOCS_ENABLED` | `false` | 显式开启 `/docs` 与 `/openapi.json`，仅供开发使用 |

容器默认使用 release 模式并关闭文档；`.env.example` 是开启开发文档的本地示例。真实 `.env`、凭据和 Terraform 运行产物均不提交。

质量检查：

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy app tests main.py
uv run pytest
```

容器使用多阶段构建、锁定依赖和非 root 运行用户，内置健康检查。当前 Compose 仅启动已实现的 API：

```bash
docker compose up --build -d
docker compose ps
docker compose logs -f api
```

本地端口绑定 `127.0.0.1:8000`。本轮 Compose 配置校验及 GitHub CI 镜像构建通过；本地镜像构建受 Docker Hub 基础镜像元数据访问超时阻塞，容器运行尚未验证，证据见 [todo.md](todo.md)。后续实现 Worker 时增加独立进程入口与服务；运行产物、日志和数据库状态使用明确的外部存储，Kubernetes 增加就绪与存活探针。

当前测试覆盖健康响应、404/405/401/422/500 统一错误、请求 ID 生成与透传、认证错误响应头保留、并发上下文隔离及异常清理、文档开关、日志格式。真实 MCP、Terraform 和云部署尚未验证，详情见 [todo.md](todo.md)。

## 官方参考

- [uv 项目管理](https://docs.astral.sh/uv/guides/projects/)
- [FastAPI 错误处理](https://fastapi.tiangolo.com/tutorial/handling-errors/)
- [Python contextvars](https://docs.python.org/3/library/contextvars.html)
- [Ruff 格式化](https://docs.astral.sh/ruff/formatter/)
- [Terraform 自动化执行](https://developer.hashicorp.com/terraform/tutorials/automation/automate-terraform)
