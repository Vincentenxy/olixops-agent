# 后端待办与问题记录

更新日期：2026-09-09。状态以当前代码和实际验证结果为准；前端事项见独立仓库 `olixops-agent-web/todo.md`。

## 本轮范围

- [x] 保留从原项目迁移的接口、JWT、审计字段和日志规范，更新为 Python / FastAPI / uv 开发约定。
- [x] 初始化可运行的 FastAPI 后端、公开健康检查和统一 HTTP 响应。
- [x] 实现请求 ID 生成与透传、并发请求上下文隔离、debug / release 日志。
- [x] 建立 CPython 3.14 环境、uv 锁文件、Ruff / mypy / pytest 入口。
- [x] 提供多阶段、非 root 的 API Dockerfile 与 Compose 启动配置。
- [x] 通过 README / AGENTS.md 明确开发规范与后续工作入口。
- [x] 将 IaC 目标选型从 Terraform 调整为 Pulumi Python + Automation API，补充 [IaC 选型记录](design/iac-selection.md)，并按 Pulumi 语义更新 Worker、预览授权、stack/state 与恢复要求；仅完成选型和文档，尚未接入执行能力。
- [x] 安装 Windows 本地 uv 0.12.10、Pulumi CLI 3.261.0，加入并锁定 `pulumi==3.261.0`；在 CPython 3.14.7 下完成无目标 Provider、无云资源的 Automation API 基础验证，业务执行能力仍待接入。

## 后续功能

| 状态 | 事项 | 当前缺口与影响 | 完成条件 |
|---|---|---|---|
| 待实现 | JWT 认证与用户上下文 | 尚未提供公钥、固定算法配置与必需 claims 契约；当前仅公开 health，无受保护业务 API | 实现 README 验签和用户字段约定，覆盖缺失、无效、过期 token 和权限拒绝 |
| 待设计 | 部署目标与应用入口 | 首版云平台 / Kubernetes 目标、代码来源和镜像构建方式尚未明确，无法确定真实部署输入 | 确认一种应用类型和一个目标环境，记录部署规格及接口 |
| 待实现 | PostgreSQL 与 Redis | 当前无数据模型、迁移、持久化任务或缓存，重启不保留业务数据 | 落实 `design/database.md`、审计字段、版本迁移和基础集成测试 |
| 待实现 | LangGraph 工作流 | 当前 API 骨架未接模型或工作流，无自然语言部署功能 | 确认模型配置，建立结构化部署规格、状态流转与 checkpoint 恢复测试 |
| 待接入 | MCP 查询 | 尚未提供实际 MCP 地址、传输方式、工具 schema 和认证方式 | 接入真实查询服务并验证超时、失败、凭据透传及重试边界 |
| 部分完成 | Pulumi 运行时与目标 Provider | 本机 CLI / SDK 3.261.0 已通过 CPython 3.14.7 基础验证；目标 Provider、插件和 Worker 镜像组合尚未验证 | 固定 Worker 镜像、CLI、SDK、组件与插件版本，验证真实资源创建/更新/导入/删除及依赖兼容性 |
| 待实现 | Pulumi Worker | 当前未执行 Pulumi，也未生成任何云资源 | 通过 Automation API 实现隔离运行、preview/up、结构化事件、超时取消、部分失败核对和重启恢复；业务任务不在 API 请求内执行 |
| 待设计 | 部署规格与组件库 | 尚无类型明确的 DeploymentSpec、受控组件或稳定 stack 映射 | 确认一种应用和目标环境，版本化组件及输入契约，按资源归属划分 stack，禁止模型输出直接作为任意程序执行 |
| 待验证 | 预览授权与计划约束 | Pulumi update plan 与 Terraform saved plan 语义不同，计划格式及未知值限制尚未验证 | 绑定规格、程序、依赖、配置、stack/state 和预览摘要；验证变化后重新授权、执行中计划偏差、部分成功及恢复，再开放严格审核环境 |
| 待配置 | Pulumi 远程状态与密钥 | Pulumi Cloud / DIY backend、secrets provider、目标凭据及同 stack 并发规则未明确 | 选定 backend 与密钥管理方式，验证状态锁、串行调度、备份恢复、访问控制和脱敏，避免盲目重试 up |
| 待实现 | 任务 API 与事件流 | 当前只有 health；前端不能提交、取消、恢复或订阅部署任务 | 先定义任务模型及接口，再实现持久化任务、授权、日志事件与重连行为 |
| 待实现 | 工具输出与凭据脱敏 | 当前结构化日志仅选择明确上下文字段，未来异常文本和 Pulumi / MCP 原始输出仍需专项处理 | 显式关闭 Automation API 的 show_secrets，按白名单映射结果和事件，覆盖 secret 派生值、配置、异常与日志泄露测试 |
| 待验证 | 真实端到端部署 | 当前单元 / HTTP 测试不代表 MCP、Pulumi 或云部署成功 | 在授权目标与有效测试凭据下完成真实 preview/up、健康检查、漂移核对及资源清理，记录证据 |
| 待实现 | 生产运行能力 | 当前 health 仅表示 API 进程存活，尚无依赖 readiness、指标、Worker 进程或 Kubernetes 配置 | 按实际组件补充健康检查、可观测性、资源限制和部署清单 |

## 已发现问题与处理

| 问题 | 处理及当前状态 |
|---|---|
| 初始项目使用 Python 3.9.6，入口为 PyCharm 示例，Dockerfile 为空 | 已替换为 FastAPI 骨架；通过 uv 同步 CPython 3.14.7，项目版本约束、`.python-version` 与 Dockerfile 已统一 |
| 框架默认 404 / 405 / 422 与未处理 500 不符合已有响应约定 | 已集中处理为 `{code,msg,data}`，保留实际 HTTP 状态；401 保留 `WWW-Authenticate`，405 保留 `Allow` |
| 未处理 500 的响应位于 Starlette 请求中间件外层，可能丢失请求 ID | 异常处理从请求状态取回 ID 并写入响应头和错误日志；单独覆盖自动生成和透传用例 |
| CPython 3.14 中 422 标准短语为 `Unprocessable Content` | 响应和 OpenAPI 统一动态读取 `HTTPStatus(...).phrase`；前端应按状态 / code 判断错误 |
| 首次开发依赖下载发生 PyPI 连接重置、传输缓慢 | 使用清华 PyPI 镜像取得与官方 `uv.lock` SHA256 一致的 Ruff / mypy wheel，完成本地安装；项目仍锁定官方 PyPI 来源，`uv sync --locked` 已通过 |
| Starlette 测试客户端使用 AnyIO 已弃用的 `anyio.abc.BlockingPortal` 别名 | 已按当前 Starlette 要求使用 `httpx2`；仍有 1 条上游 AnyIO 弃用警告，14 个测试通过。后续依赖更新时复核，当前未修改第三方代码或屏蔽警告 |
| 本地 Docker Hub 基础镜像元数据访问超时 | Docker 服务本身可用，Compose 配置校验通过；GitHub CI 已成功构建镜像，本地构建和容器启动验收仍未完成 |
| 初始规范描述的是完整目标架构，易被误解为已实现 | README 和本文件标明当前唯一业务接口及未接入组件；没有占位部署接口或假执行结果 |
| 原 IaC 文档按 Terraform CLI 和保存计划执行设计 | 已改选 Pulumi，重写为 Python Automation API、preview/up 和稳定 stack；说明 CLI 依赖、update plan 逐步校验及部分失败边界。仓库尚无 Terraform 资源或 state，此次不涉及生产资源迁移 |
| 本机终端找不到 uv 和 Pulumi CLI | 已安装到用户目录并登记用户 PATH；已打开的终端/IDE 需重新加载环境。本轮通过绝对工具路径执行并验证版本 |
| Windows 本地 backend 使用 `file:///E:/...` 时出现盘符重复 | Pulumi CLI 3.261.0 的本地验证改用 `file://` 加 `Path.as_posix()`，即 `file://E:/...`，完整基础流程通过；临时 stack/state 已清理 |

## 验证记录

以下为 API 骨架阶段已有验证记录；不代表已经验证 Pulumi。外部镜像仓库访问问题与功能待办分别记录。

- [x] `uv sync --locked`
- [x] `uv run ruff check .`
- [x] `uv run ruff format --check .`
- [x] `uv run mypy app tests main.py`：14 个源文件通过 strict 类型检查。
- [x] `uv run pytest`：14 passed，1 条上游弃用警告（见“已发现问题与处理”），无失败。
- [x] `docker compose config --quiet` 配置校验通过。
- [x] GitHub CI 中 API 镜像构建通过；本地构建在 Docker Hub 拉取 `python:3.14.7-slim` 元数据时出现 `context deadline exceeded`，未执行到应用构建阶段。
- [ ] 容器启动、非 root 用户及容器健康检查：本地镜像源网络恢复后重新构建并验证。镜像构建通过不等于容器运行验收完成。
- [x] 前端开发代理调用实际 API 的浏览器联调：后端未启动时展示连接失败，启动后健康检查成功。
- [x] [Backend CI #1](https://github.com/Vincentenxy/olixops-agent/actions/runs/34228792131) 对提交 `3ee3382` 执行成功：依赖安装、Ruff、strict mypy、pytest 与 Docker 镜像构建全部通过。

## Pulumi 选型调整验证（2026-09-08）

- [x] 核对 Pulumi / HashiCorp 官方文档和许可证，复核 Automation API 的 CLI 依赖、update plan 语义、DIY backend 锁与历史、secret 输出边界以及内部使用许可；来源见选型记录。
- [x] 同步后端 README / todo / 项目描述，以及前端 README / todo / 接口开发文档；新增选型记录。保留原验证记录的历史含义，未将健康检查结果描述为 Pulumi 验证结果。
- [x] 两个仓库的 `git diff --check` 通过；6 份文档的 27 个本地链接/锚点及代码围栏检查通过。
- [x] `pyproject.toml` 解析通过，确认仅修改项目描述，依赖声明和 `uv.lock` 未改变；9 项 Git 忽略规则检查确认 Pulumi 缓存、实际 stack 配置和运行产物被忽略，程序、项目配置与无凭据示例可提交。
- [ ] Pulumi 安装与真实 preview/up/refresh/destroy：本次只调整文档、描述及忽略规则，未接入运行时，也未运行应用测试、构建或资源操作。

## Pulumi 基础安装验证（2026-09-09）

- [x] 从官方发布地址取得 uv 0.12.10 和 Pulumi CLI 3.261.0，安装到当前用户目录；两者版本命令通过，目录已加入用户 PATH。
- [x] `uv add pulumi==3.261.0`、`uv sync --locked` 通过；SDK 与 grpcio 等传递依赖在 CPython 3.14.7 环境安装成功，依赖锁更新。
- [x] Automation API 使用隔离工作目录、`pulumi_home`、临时文件 backend 和仅导出常量的 inline 程序，验证 preview、结构化引擎事件、up、outputs、refresh 和再次预览无变更；随后 destroy、删除临时 stack 并清理测试状态。未声明目标 Provider 或云资源，未调用全局 login。
- [x] Ruff 检查和格式检查通过；strict mypy 的 14 个源文件通过；pytest 14 passed，保留原有 1 条上游 AnyIO 弃用警告。
- [x] `uv lock --check --offline`、Git 差异检查及文档链接检查通过；锁文件新增 16 个包，原有包版本未改变；临时基础验证目录已清理。
- [ ] 目标 Provider / 插件、业务 Worker、生产远程 backend 及真实云/Kubernetes 部署：未接入，仍需确认首个部署目标及凭据。
- [ ] 本轮未构建或运行 Docker 镜像；现有镜像未安装 Pulumi CLI，Windows 本机验证不代表 Worker 容器验收。
