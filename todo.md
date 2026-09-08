# 后端待办与问题记录

更新日期：2026-09-08。状态以当前代码和实际验证结果为准；前端事项见独立仓库 `olixops-agent-web/todo.md`。

## 本轮范围

- [x] 保留从原项目迁移的接口、JWT、审计字段和日志规范，更新为 Python / FastAPI / uv 开发约定。
- [x] 初始化可运行的 FastAPI 后端、公开健康检查和统一 HTTP 响应。
- [x] 实现请求 ID 生成与透传、并发请求上下文隔离、debug / release 日志。
- [x] 建立 CPython 3.14 环境、uv 锁文件、Ruff / mypy / pytest 入口。
- [x] 提供多阶段、非 root 的 API Dockerfile 与 Compose 启动配置。
- [x] 通过 README / AGENTS.md 明确开发规范与后续工作入口。

## 后续功能

| 状态 | 事项 | 当前缺口与影响 | 完成条件 |
|---|---|---|---|
| 待实现 | JWT 认证与用户上下文 | 尚未提供公钥、固定算法配置与必需 claims 契约；当前仅公开 health，无受保护业务 API | 实现 README 验签和用户字段约定，覆盖缺失、无效、过期 token 和权限拒绝 |
| 待设计 | 部署目标与应用入口 | 首版云平台 / Kubernetes 目标、代码来源和镜像构建方式尚未明确，无法确定真实部署输入 | 确认一种应用类型和一个目标环境，记录部署规格及接口 |
| 待实现 | PostgreSQL 与 Redis | 当前无数据模型、迁移、持久化任务或缓存，重启不保留业务数据 | 落实 `design/database.md`、审计字段、版本迁移和基础集成测试 |
| 待实现 | LangGraph 工作流 | 当前 API 骨架未接模型或工作流，无自然语言部署功能 | 确认模型配置，建立结构化部署规格、状态流转与 checkpoint 恢复测试 |
| 待接入 | MCP 查询 | 尚未提供实际 MCP 地址、传输方式、工具 schema 和认证方式 | 接入真实查询服务并验证超时、失败、凭据透传及重试边界 |
| 待实现 | Terraform Worker | 当前未执行 Terraform，也未生成任何云资源 | 确定 CLI / Provider 版本、独立工作目录、超时取消、保存 plan 后 apply、错误分类与结果核对 |
| 待配置 | Terraform 远程状态 | 状态后端、锁定机制、目标凭据及同资源并发规则未明确 | 配置支持锁定的状态后端，验证串行协调和恢复，避免盲目重试 apply |
| 待实现 | 任务 API 与事件流 | 当前只有 health；前端不能提交、取消、恢复或订阅部署任务 | 先定义任务模型及接口，再实现持久化任务、授权、日志事件与重连行为 |
| 待实现 | 工具输出与凭据脱敏 | 当前结构化日志仅选择明确上下文字段，未来异常文本和 Terraform / MCP 原始输出仍需专项处理 | 接入每个外部组件时制定输出脱敏规则并覆盖含敏感值的测试 |
| 待验证 | 真实端到端部署 | 当前单元 / HTTP 测试不代表 MCP、Terraform 或云部署成功 | 在授权目标与有效测试凭据下完成真实部署、健康检查及资源清理，记录证据 |
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

## 验证记录

以下结果来自本轮实际检查；外部镜像仓库访问问题与功能待办分别记录。

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
