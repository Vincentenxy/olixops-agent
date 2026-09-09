# olixops-agent

通过自然语言分析应用需求、查询 MCP 信息、生成结构化部署规格并使用 Pulumi 组织部署的 DevOps 智能体后端。

本 README 是后端项目后续开发和代码评审的规范入口。接口、认证、数据库和日志约定同时作为前后端联调契约；下文明确区分已实现能力与后续架构要求，待接入事项统一记录在 [todo.md](todo.md)。

## 仓库与当前状态

- `olixops-agent/`：Python 后端、Agent 工作流、MCP 查询适配和 Pulumi Worker。
- `olixops-agent-web/`：独立前端项目，通过后端 API 提交需求、查看变更和部署结果。
- 当前已实现：FastAPI、PostgreSQL 异步连接与 Alembic 迁移、Redis 缓存、RSA JWT 本地登录及会话撤销、结构化脱敏日志、健康与就绪检查、Pulumi 运行时诊断及独立 Worker 引擎自测、LangGraph 需求分析与持久会话、前端认证和方案分析入口。
- Agent 支持通过 OpenAI 兼容接口理解 Redis/PostgreSQL 部署需求，追问缺失参数、生成结构化方案、断点恢复和失败重试。任务提交后由后台队列处理。MCP 查询、集群核验及真实部署组件仍待接入，不开放从 HTTP 执行 Pulumi 程序的接口。
- 后续开发先阅读本 README，再读取实际存在且适用于修改目录的 `AGENTS.md`。新增专项设计文档时，在对应规范处补充入口。

## 技术栈与环境管理

| 组件 | 目标选型 / 约定 |
|------|----------------|
| Python | CPython 3.14 系列，接入依赖时验证兼容性 |
| 项目管理 | uv；`pyproject.toml` 声明依赖，`uv.lock` 锁定解析结果 |
| Web | FastAPI + Uvicorn，Pydantic 定义输入、输出和配置模型 |
| Agent | LangGraph，持久化工作流进度 |
| 工具查询 | MCP 客户端 / 适配层，对接现有查询能力 |
| IaC | Pulumi Python + Automation API，由独立 Worker 执行；运行时仍需 Pulumi CLI 和 Provider 插件 |
| 数据 | PostgreSQL 持久化；Redis 用于缓存 |
| 质量检查 | Ruff 检查与格式化、mypy 类型检查、pytest 测试 |
| 部署 | Docker 容器化；开发环境采用 Docker Compose，目标部署于 Kubernetes |

运行环境已切换为 CPython 3.14，补丁版本由 `.python-version` 固定，容器镜像同步使用该版本。已有 Python 3.9 环境会在 `uv sync` 时被替换为符合项目约束的环境。FastAPI、Pydantic、LangGraph、Pulumi Python SDK 与质量工具的实际版本由 `uv.lock` 锁定；MCP 和目标 Provider 仍待接入。

IaC 目标选型已由 Terraform 调整为 Pulumi，优先利用 Python 组件和 Automation API 构建内部平台。选型理由、开发运维对比和接入验证范围见 [IaC 选型记录](design/iac-selection.md)；执行规范仍以本 README 为准。当前已实现独立 Worker 的受控程序验证入口，CLI 与 SDK 固定为 3.261.0；目标 Provider、持久任务和生产 state backend 待接入。模块说明见 [Pulumi 基础集成](design/pulumi-foundation.md)，数据库设计见 [数据库设计](design/database.md)。

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
│   └── workers/            # 部署任务领取、Pulumi Automation API 执行与结果回收
├── iac/                    # Pulumi Python 项目、可复用组件与模板；运行产物另行保存
├── migrations/             # 数据库版本迁移
├── tests/                  # 单元和集成测试
├── design/                 # 接口、数据与部署设计
├── pyproject.toml
├── uv.lock
├── Dockerfile
└── README.md
```

路由负责协议适配，业务逻辑放入 service；数据库访问集中在 repository。Agent 节点调用明确的业务和工具接口，Pulumi Automation API 及其 CLI / Provider 子进程由独立 Worker 管理，不在 FastAPI 请求内运行。前端代码保存在 `olixops-agent-web/`。

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

当前使用本地账号、Argon2 密码哈希和固定 RS256 签名；JWT 校验 issuer、audience、expiry 及必需 claims，并查数据库中的用户状态和有效会话。首次用户由 CLI 创建，没有内置默认密码或公开注册接口。后续外部身份源按以下兼容约定接入。

- 使用 Bearer JWT 和 RSA 公钥验签；当前固定 RS256。旧项目允许的 RS384 / RS512 仅作为未来兼容候选，新增前明确配置和测试，不使用 token 自报算法。
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

已实现 SQLAlchemy async + psycopg、Alembic 迁移及三张认证表、`agent_tasks` / `agent_turns` 两张分析业务表。LangGraph checkpoint 由官方组件在独立 schema 中管理。Redis 使用单个异步连接池，提供命名空间、显式 TTL 和连接状态；认证会话不依赖 Redis 保存。详细 DDL 见 [数据库设计](design/database.md)。

- PostgreSQL 保存业务数据和任务状态；Redis 用于缓存，不作为部署任务的唯一持久化来源。
- 所有业务表设计记录在 `design/database.md`，使用 Markdown 与 SQL 代码块。该文件在首次数据库设计时创建，结构变更同步更新设计和版本迁移。
- 所有业务表包含 `create_at` / `update_at` / `create_by` / `update_by`，保留这些字段名。外部组件自管的表遵循其迁移机制。
- 时间字段使用带时区时间，统一保存 UTC；创建人和更新人来自已认证用户，系统任务的操作者取值在表设计中明确。
- 表名、列名、索引名使用 `snake_case`；查询使用参数绑定，事务边界由业务用例管理。
- 数据库结构通过版本迁移演进，并在变更中说明数据兼容及回退方式。

## 日志与请求追踪

- 统一使用 Python `logging`；模块通过 `logging.getLogger(__name__)` 获取 logger，格式器和上下文过滤器集中配置。
- debug 模式输出带颜色的可读文本，INFO 使用蓝绿色、ERROR 使用红色；release 模式输出 JSON，便于采集。时间使用带时区的 ISO 8601 格式。
- 请求入口读取 `X-Request-Id`：透传 1–128 位字母、数字及 `._:-` 组成且以字母数字开头的值；缺失或无效时生成 32 位十六进制 ID，响应头回写。限制输入避免控制字符进入日志。
- 使用 `contextvars.ContextVar` 管理当前执行上下文的 `trace_id`，请求结束时重置；日志有 trace ID 时输出，无值时省略。
- HTTP 访问日志包含 `method`、`path`、`status_code`、`duration_ms`、`client_ip`；部署日志补充 `task_id` 和 `step`。
- 下游 HTTP 请求继续透传 `X-Request-Id`。跨进程 Worker 通过任务记录显式接收 `trace_id` 和 `task_id`，在执行入口绑定，结束后清理。

日志初始化、上下文注入和格式器已实现；用法示例：

```python
import logging

logger = logging.getLogger(__name__)
logger.info("server started", extra={"port": 8000})
logger.info("deployment step finished", extra={"task_id": "example-task", "step": "preview"})
logger.warning("MCP query timed out", extra={"server_name": "inventory"})
```

日志级别统一使用 `debug` / `info` / `warning` / `error`；异常保留类型和堆栈位置，省略可能含凭据的异常原文、源码行和局部变量。配置值和常见 password/token/Bearer/连接串/私钥形式会脱敏，任意业务文本仍需调用方选择可公开字段，禁止记录请求正文。Automation API 返回值和引擎事件按字段映射、脱敏后再入库或发送前端；支持 `show_secrets` 的调用显式关闭该选项，不直接序列化完整结果。secret 加密不能代替日志脱敏。

## Agent 与 Pulumi 执行规范

当前 LangGraph 实现负责需求分析和部署方案，支持 Kubernetes 单实例 Redis/PostgreSQL、持久卷容量和内部访问需求。输入、输出均通过 Pydantic 校验，模型结果只作为数据。方案中的集群名称尚未经过实际集群查询；`ready` 表示方案生成，不能解释为部署成功。工作流、API、配置及恢复边界见 [LangGraph 集成](design/langgraph.md)。

业务任务与对话保存到 `agent_tasks` / `agent_turns`，官方 PostgreSQL checkpoint 保存到独立 `agent_graph` schema。API 只持久提交，应用生命周期内的后台消费者用 `FOR UPDATE SKIP LOCKED` 领取队列；同一任务只允许一个待处理轮次。用户行锁保护提交限额，revision 防止旧页面覆盖，同一 request_id 的重放不能重复追加对话。LangGraph 使用同步 checkpoint 持久策略，中断节点只等待输入；模型调用在单独节点，恢复不会重新运行已完成的理解节点。模型原始异常不写入 checkpoint，平台不向图状态添加模型密钥或用户登录凭据，默认关闭外部 LangSmith tracing；用户输入作为业务文本保存，禁止在需求中粘贴密码或 kubeconfig。

以下部署规范适用于后续资源执行。当前已有 Automation API 适配层和独立 `self-test` Worker，使用固定常量程序、隔离目录/状态、脱敏结果及进程组超时；尚无业务组件、持久业务 stack 或部署接口。Agent 方案队列和临时 Pulumi 自测不等同于生产部署调度。

- MCP 的接入范围是信息查询；Agent 负责理解需求，输出经过 Pydantic 校验的部署规格。由受控、版本化的 Pulumi Python 组件和模板声明资源；模型生成的新组件先经过代码评审和测试，不作为请求内容直接执行。
- Worker 通过 Python Automation API 管理 project、stack 和资源生命周期；其底层仍调用 Pulumi CLI。固定 Worker 镜像、CLI、Python SDK、Provider SDK / 插件及组件版本，接入时验证完整依赖链与 CPython 3.14、uv 的兼容性。
- 流程按 `校验规格与组件 → 选择 stack 并配置 → 按策略 refresh → preview → 策略检查及环境授权 → up → 验证结果` 组织。`refresh` 用于读取实际资源并更新状态；漂移检测频率及如何接受外部变更由环境策略定义，不把普通 `preview` 当作已检查全部漂移。
- 保存预览摘要及相关产物；需要人工审核时，审核记录绑定部署规格、程序与组件版本、依赖锁、配置版本、目标 stack、状态版本或摘要及预览摘要。配置只保存必要的非敏感字段和密钥版本引用。执行前核对这些绑定，发现变化时重新预览，并按环境策略重新授权；不能仅凭旧预览页面调用 `up`。
- Pulumi 支持 `preview --save-plan` / `up --plan`（Automation API 的 `plan` 参数），但它会重新运行程序，并在执行过程中逐步检查计划约束；发现偏差前可能已有计划内变更完成。计划 JSON 格式仍被官方标为实验性，不作为平台 API 契约。保存计划需在固定版本下验证未知值、动态资源和 Provider 配置的限制，不能视为 Terraform 保存计划的等价替换或事务保证。严格审核环境在此验证完成前不开放执行。
- stack 代表持续管理的一组资源，以项目、应用、环境及资源归属确定稳定身份；`task_id` 代表一次运行，不能每次任务都创建新的 stack。同一 stack 的写操作串行调度，backend lock 提供最终并发保护；共享资源划分独立归属，避免被多个 stack 同时管理。
- 每次运行使用独立工作目录和隔离执行环境，限制凭据作用域、文件及网络访问，设置超时和退出处理。`preview` 同样会运行 Python 程序，不能视为任意代码的安全沙箱。确需直接调用 CLI 时使用参数列表启动子进程，不拼接命令字符串。
- Pulumi state 保存在明确选择的远程 backend，生产执行不依赖 Worker 本地磁盘。可选择 Pulumi Cloud 或自行管理的 DIY backend；DIY 已有锁与历史，但存储权限、备份恢复、可用性和平台审计需自行落实。backend 与 secrets provider 是分别配置的选项，当前均未确定。
- LangGraph checkpoint、PostgreSQL 中的业务任务记录、Pulumi state 分别管理。Worker 重启、取消、超时或部分失败后，先核对操作历史、state 和实际资源，再决定恢复或重试；取消不等于回滚，也不应直接解锁后重复 `up`。删除资源使用独立授权的 `destroy` 操作，不作为失败任务的默认补偿。
- 长任务提交后返回 `task_id`，由后端持续执行；客户端断开不等于取消。Automation API 的结构化引擎事件转换为平台自己的步骤、资源变更和日志事件，持久化后供前端查询或订阅，保留事件顺序与重连游标。
- 受控 Pulumi 程序、`Pulumi.yaml` 和依赖锁可提交；实际 stack 配置按环境管理，仓库只提供不含凭据的示例。state 导出、计划、密钥及运行缓存放入 Git 忽略的 `runtime/` 或外部产物存储，不提交 `.pulumi/`。secret 字段及其派生值应使用 Pulumi 的 secret 机制，普通 state 字段仍可能为明文，状态与产物存储均需权限控制。
- IaC 管理基础设施资源；需要构建镜像时由独立构建步骤生成镜像及固定标识，再交给部署步骤使用。

## 开发与验证流程

1. 阅读本 README、相关设计和当前代码，确认任务范围及工作区已有改动。
2. 涉及接口、数据结构、状态流转的变更，先明确契约，再实现相应模块并同步文档。
3. 新增或变更行为使用 pytest 验证可观察结果；覆盖认证、统一错误、请求 ID、MCP 失败、Pulumi 失败及恢复等相关路径。
4. 单元测试使用可控的外部接口替身；集成测试覆盖实际组件协作。真实云部署验证单独配置目标与凭据，并在任务授权范围内执行，分别报告模拟验证与真实验证结果。
5. 完成适用于改动的检查，修复本次引入的问题；报告实际执行的检查及未执行原因。纯文档变更检查内容、示例和链接。
6. 按任务要求提交本次改动，使用 `feat:` / `fix:` / `docs:` / `refactor:` / `test:` / `chore:` 描述提交目的，保留已有无关改动。

### 本地开发启动

两个仓库保持同级目录。先在后端执行，依赖锁已包含 Python 库；Docker 仅启动本项目的 PostgreSQL/Redis：

```bash
uv sync --locked
uv run python scripts/install_pulumi.py
uv run python scripts/init_local.py
docker compose up -d --wait postgres redis
uv run python -m app.cli init-keys
uv run alembic upgrade head
uv run python -m app.cli create-user --username admin --name 管理员 --admin
uv run python main.py
```

`create-user` 在终端安全读取并确认 12–128 字符密码；自动化可通过 `OLIXOPS_BOOTSTRAP_PASSWORD` 注入。不存在公开默认密码。再次执行生成配置、密钥或创建同名用户会保留已有值，不重置账号。`.env`、密钥和 `runtime/` 不进入 Git；`init_local.py` 为本地数据库生成随机密码。IDE 使用 `.venv/bin/python`。

前端在 `olixops-agent-web` 执行 `pnpm install --frozen-lockfile && pnpm dev`，浏览器地址以终端输出为准。默认代理后端 `127.0.0.1:8000`；登录后可查看连接状态和账户设置。当前机器的本地 `admin` 初始凭据单独保存在忽略的 `runtime/local-login.json`，首次使用后可通过账户页面修改，随后移除这份本地交接文件。

### 接口与会话

所有成功结果仍使用 `{code:0,msg:"",data:...}`，HTTP 错误维持前述统一结构。

| 方法与路径 | 请求/结果 |
|---|---|
| `GET /api/v1/pub/health` | API 进程存活，`data={status:"ok",service:"olixops-agent"}` |
| `GET /api/v1/pub/ready` | 数据库已迁移、RSA 密钥可用、已配置 Redis 可连接时 200，否则统一 503；不检查尚未配置的业务 Provider |
| `POST /api/v1/pub/auth/login` | `{username,password}`；返回 access token、有效秒数和安全用户字段，设置 refresh Cookie |
| `POST /api/v1/pub/auth/refresh` | `{}`；从 Cookie 原子轮换 refresh token，返回新 access token 和当前用户 |
| `POST /api/v1/pub/auth/logout` | `{}`；优先撤销有效 Bearer 的会话，否则使用 Cookie，清理 Cookie，重复退出可安全执行 |
| `GET /api/v1/auth/me` | Bearer 认证，返回 `{user_id,username,name,is_admin}` |
| `POST /api/v1/auth/password` | Bearer + `{current_password,new_password}`，成功撤销此用户全部会话并清 Cookie；旧密码错误返回 400 |
| `GET /api/v1/system/status` | Bearer 认证，返回 database/redis/auth/pulumi 状态和 Pulumi 版本，不返回连接串或密钥 |

Access token 仅保存在前端内存，默认 15 分钟；refresh token 为随机值，数据库仅保存 SHA256，Cookie 使用 HttpOnly、SameSite=Strict、限定路径。数据库会话绝对有效期默认 7 天，刷新不会延长；退出、改密或禁用用户后旧 access token 也会被拒绝。首次页面加载通过 refresh 恢复状态；并发刷新只允许一个 CAS 成功。前端合并当前标签页刷新，跨标签页身份变化不会重放旧用户请求。

认证写接口要求 `Content-Type: application/json`、`X-Olixops-Client: web` 和受信任 Origin（请求携带时校验）；不开放 CORS，浏览器同源访问。生产部署启用 HTTPS、Secure Cookie 并配置准确的 Origin。密码错误使用相同 401，不区分用户不存在；用户名/IP 的失败次数保存在数据库，默认 5 次失败后退避 30 秒，重复失败最长 600 秒。

### 运行配置

以 `app/core/config.py` 与 `.env.example` 为准，环境变量统一 `OLIXOPS_` 前缀：

| 配置 | 默认值/用途 |
|---|---|
| `MODE` / `DOCS_ENABLED` | debug 日志 / 默认关闭文档；容器 release 模式 |
| `DATABASE_URL` | `postgresql+psycopg://...`；开发端口 15432，测试可使用 SQLite |
| `REDIS_URL` | 未配置则禁用；本地配置 `redis://127.0.0.1:16379/0` |
| `JWT_PRIVATE_KEY_PATH` / `JWT_PUBLIC_KEY_PATH` | `runtime/keys/jwt-private.pem` / `jwt-public.pem` |
| `JWT_PUBLIC_KEY` | 可选 PEM 或 base64 DER 公钥文本，必须与本地私钥配对 |
| `JWT_ISSUER` / `JWT_AUDIENCE` | `olixops-agent` / `olixops-agent-web` |
| `ACCESS_TOKEN_SECONDS` / `REFRESH_TOKEN_SECONDS` | 900 / 604800 |
| `REFRESH_COOKIE_SECURE` | 本地 HTTP 为 false；生产 HTTPS 必须设 true |
| `BROWSER_ORIGINS` | 精确 Origin JSON 列表，开发默认 localhost/127.0.0.1 的 5173/5175 |
| `PULUMI_CLI` | 默认 `pulumi`；初始化脚本可指向项目 `runtime/tools/pulumi/pulumi` |
| `AGENT_BASE_URL` / `AGENT_MODEL` / `AGENT_API_KEY` | OpenAI 兼容网关 API 前缀、模型名称和私密 key；未配置模型和 key 时禁用新分析，仍可查历史任务 |
| `AGENT_RESPONSE_FORMAT` | 默认 `json_object` 并在本地校验 schema；服务商支持时可设 `json_schema` |
| `AGENT_MODEL_TIMEOUT_SECONDS` / `AGENT_TURN_TIMEOUT_SECONDS` | 模型请求 45 秒 / 每轮含 checkpoint 90 秒；无 SDK 自动重试，失败后用户显式重试 |
| `AGENT_MAX_OUTPUT_TOKENS` | 默认 4096；超限截断结果按失败处理 |

健康检查不返回内部连接信息。缺少密钥或依赖时认证拒绝服务，进程健康检查仍可用。数据库迁移显式执行，不在 API 启动或请求中自动建表。

### LangGraph 本地接入

将 `.env.example` 中的 `OLIXOPS_AGENT_*` 配置加入私有 `.env`，填写兼容网关地址、模型名称和 key；服务需支持 Chat Completions JSON 输出。先执行以下命令，再从前端工作台点击“分析需求”：

```bash
uv sync --locked
uv run alembic upgrade head
uv run python -m app.cli init-agent
uv run python main.py
```

`init-agent` 使用官方 checkpointer 的显式迁移，在 `agent_graph` schema 中建表；已有数据保留。Windows 的 psycopg 需要 Selector 事件循环，`main.py`、CLI 和迁移入口已统一处理。直接启动 Uvicorn 时使用 `--loop app.core.event_loop:loop_factory`；开发自动重载可附加 `--reload`。

示例需求：“在 poc 集群 demo 命名空间部署 Redis 7.4（10Gi）和 PostgreSQL 16（20Gi），均为单实例、仅集群内访问。”可在任务详情继续修改；重启后仍能查看和恢复。此阶段不调用 Kubernetes 或 Pulumi 创建资源。

### Pulumi 本地基础环境

项目固定 CLI/SDK `3.261.0`；`scripts/install_pulumi.py` 从官方来源下载并校验 SHA256，安装至项目忽略的 `runtime/tools/`，不修改全局登录或 PATH。详细模块和输出约束见 [Pulumi 基础集成](design/pulumi-foundation.md)。

```bash
uv run python -m app.workers.pulumi self-test --cli runtime/tools/pulumi/pulumi --timeout 120
```

Windows 使用 `pulumi.exe`。Worker 以独立子进程执行 `preview → up → outputs → refresh → 无变更 preview → destroy → remove_stack`，返回脱敏 JSON。只验证固定常量程序，无目标 Provider 或云资源；异常不会被描述为已回滚。已验证 macOS 引擎及 POSIX 超时路径，Windows 新 Worker 的终止路径待验证；历史 Windows SDK 验证记录见 todo。

### 质量检查与容器

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy app tests scripts main.py
uv run pytest
uv run alembic check
```

真实 PostgreSQL/Redis 测试分别由 `OLIXOPS_TEST_DATABASE_URL` / `OLIXOPS_TEST_REDIS_URL` 显式启用，数据库需先迁移；Pulumi 引擎测试由 `OLIXOPS_RUN_PULUMI_TEST=1` 与 `OLIXOPS_PULUMI_CLI` 启用。测试只操作自身随机命名记录和临时 stack，不代表业务部署成功。

Dockerfile 包含固定 Pulumi CLI、Python 依赖及迁移，以非 root 用户运行。Compose 默认仅启动数据服务；完整 API/Web 使用 app profile：

```bash
docker compose --profile app build
docker compose up -d --wait postgres redis
docker compose run --rm api python -m app.cli init-keys
docker compose run --rm api alembic upgrade head
docker compose run --rm api python -m app.cli init-agent
docker compose run --rm api python -m app.cli create-user --username admin --name 管理员 --admin
docker compose --profile app up -d
```

Web 地址 `http://127.0.0.1:8080`，Nginx 同源反代 API；容器密钥保存在独立 `api-runtime` 卷，与宿主机密钥分开。本地 DB/Redis 端口只绑定回环地址，数据卷持久保存；普通 `docker compose down` 不删除数据卷。临时引擎自测可运行 `docker compose run --rm worker-check`。

本机数据服务与浏览器联调已通过；本地应用镜像构建受 Docker Hub token 访问超时影响。后端 GitHub CI 已完成镜像构建、API 容器登录和 Pulumi Worker 容器验证，实际结果见 [todo.md](todo.md)。

## 官方参考

- [uv 项目管理](https://docs.astral.sh/uv/guides/projects/)
- [FastAPI 错误处理](https://fastapi.tiangolo.com/tutorial/handling-errors/)
- [Python contextvars](https://docs.python.org/3/library/contextvars.html)
- [Ruff 格式化](https://docs.astral.sh/ruff/formatter/)
- [Pulumi Automation API](https://www.pulumi.com/docs/iac/concepts/automation-api/)
- [Pulumi Python 与 uv](https://www.pulumi.com/docs/iac/languages-sdks/python/)
- [Pulumi Update Plans](https://www.pulumi.com/docs/iac/operations/stack-management/update-plans/)
- [Pulumi State 与 Backends](https://www.pulumi.com/docs/iac/concepts/state-and-backends/)
- [Pulumi Secrets](https://www.pulumi.com/docs/iac/concepts/secrets/)
