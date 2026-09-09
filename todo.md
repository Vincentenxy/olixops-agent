# 后端待办与验证记录

更新日期：2026-09-09。本轮范围是可运行的非业务基础能力，应用部署业务等待后续设计。

## 本轮完成

- [x] PostgreSQL 异步连接、连接超时、SQLAlchemy session 生命周期与 Alembic 显式迁移；三张认证表及审计字段见 [数据库设计](design/database.md)。
- [x] Redis 异步连接池、应用命名空间、明确 TTL、连接检查及关闭释放；会话有效性仍以 PostgreSQL 为准。
- [x] 本地用户 CLI、3072 位 RSA 密钥初始化、Argon2 密码、固定 RS256 JWT、claims 与数据库会话校验。
- [x] 登录、刷新、退出、当前用户、修改密码；HttpOnly Strict Cookie、JSON/自定义请求头/Origin 校验、用户名/IP 持久化失败退避。
- [x] Refresh token 原子轮换；改密撤销全部会话，退出或用户禁用后旧 access token 拒绝访问。
- [x] 公共健康与就绪探针、受保护的数据库/Redis/认证/Pulumi 实际状态 API。
- [x] 统一结构化日志、请求/用户追踪、请求 ID 校验、配置/凭据形式脱敏、异常类型和堆栈位置记录。
- [x] 固定 Pulumi CLI/SDK 3.261.0、官方校验和安装脚本、隔离 Automation API 适配和独立 Worker 自测，见 [Pulumi 基础集成](design/pulumi-foundation.md)。
- [x] 本地生成配置、独立 PostgreSQL/Redis 数据卷及端口、API/Web Compose profile、容器 CLI/迁移/密钥卷配置。
- [x] React 登录、刷新恢复、退出、账户页面和基础状态页真实联调；更新两端接口文档。

## 本轮验证

- `uv sync --locked`、Ruff lint/format、strict mypy（含脚本）全部通过。
- **70 个 pytest 测试通过，无跳过**；启用了实际 PostgreSQL、Redis 与 Pulumi 引擎。保留 1 条 Starlette/AnyIO 上游弃用警告，无本轮失败。
- PostgreSQL 15：真实迁移和 `alembic check` 通过，表结构与模型一致；并发 refresh 只允许一个请求成功。临时 SQLite 另测迁移升降级。
- Redis 7：连接、读写、TTL 到期与删除均在真实服务通过。
- Pulumi：固定常量及 secret 测试输出程序的 preview → up → outputs → refresh → 无变更 preview → destroy → remove_stack 通过，临时状态清理完成；未使用云 Provider/资源。
- HTTP 经真实 Vite 代理：登录、状态、错误旧密码、改密、全部会话失效、新旧密码验证、退出、旧 token 和 refresh 拒绝通过。
- 浏览器：错误登录、成功登录、刷新恢复、四项基础服务正常、改密后失效与新密码登录、退出及刷新后保护通过；账户/登录页面 1280×720 与 390×844 无页面横向溢出，控制台无 warn/error。
- `docker compose --profile app config --quiet` 通过，PostgreSQL/Redis 容器实际健康。本地 API/Web 构建仍在 Docker Hub 获取 Python 镜像授权 token 时网络超时，未进入应用构建阶段；API/Web 容器启动和 Nginx Cookie 联调不能视为本地完成。
- [ ] 本轮推送后确认 GitHub CI：新增真实数据库/缓存检查、API 容器登录自测和 Pulumi Worker 容器自测。

## 已发现问题与处理

| 问题 | 处理与当前状态 |
|---|---|
| 本机其他项目占用 5432/6379 | 本项目独立使用 15432/16379 和 olixops-agent 数据卷，不复用或修改其他项目实例 |
| Refresh 并发与 SQLite 时区比较 | 使用数据库 CAS 并禁用 ORM 自动同步比较；SQLite 与真实 PostgreSQL 并发用例均通过 |
| 另一个标签页切换用户后旧请求可能以新身份重放 | 前端刷新绑定原 user_id，变化时清身份、缓存、草稿并拒绝原请求和迟到数据 |
| Cookie 与 Bearer 属于不同会话时退出撤销错误对象 | 后端优先有效 Bearer 的 user/sid；无可用 Bearer 时回退 Cookie，回归测试验证不会撤销另一个会话 |
| 公共 logout 携带无效/过期 Bearer | 按可选凭据处理并回退 Cookie，维持幂等；受保护接口仍严格 401 |
| Pulumi CLI 依赖系统用户信息且可能初始化全局状态 | 保留原 HOME/USER，诊断和执行分别设置隔离 PULUMI_HOME；无全局 login 或云凭据继承 |
| 日志异常文本可能带外部凭据 | 保留异常类型及堆栈位置，省略任意异常消息/源码行/局部变量；普通日志仍须明确选择无敏感字段 |
| Docker Hub 本地授权 token 超时 | 使用现有受控数据镜像完成真实 PostgreSQL/Redis；应用镜像与容器以远程 CI 实际结果补充 |
| 初始管理员凭据 | 本地 admin 为随机密码，仅保存在 Git 忽略的 runtime/local-login.json；用户可改密后移除交接文件，仓库无默认密码 |

## 后续平台事项

| 事项 | 当前边界与完成条件 |
|---|---|
| 生产认证与账号管理 | 当前本地 CLI 创建账户；SSO、账号找回、禁用/角色管理 UI、资源级 RBAC 按后续需求设计 |
| 会话维护与密钥轮换 | 增加过期会话和历史限流记录清理、RSA 密钥轮换及旧钥过渡；当前密钥初始化不会覆盖现有值 |
| 多标签页与高级限流 | 当前已有身份变化拒绝与后端原子刷新；跨标签互斥/退出广播、可信代理和多实例流量策略待设计 |
| Windows Worker | 历史 Windows SDK 常量程序已验证；新 Worker 的 taskkill 子进程树终止分支需 Windows CI 验证 |
| 生产运行 | 明确 HTTPS、Secure Cookie、精确 Origin、可信代理、secret 注入、数据备份、资源限制、监控与 Kubernetes 清单 |

## 等待业务设计

- Agent 模型与 LangGraph 状态/恢复、MCP 查询地址/schema/认证。
- 首个应用类型、镜像构建与版本标识、目标平台和环境权限。
- DeploymentSpec、受控组件库、稳定 Stack 归属与 Provider/插件版本。
- 持久业务任务、事件流、同 Stack 跨进程调度、重试/取消/部分失败核对。
- Pulumi 生产远程 backend、secrets provider、凭据作用域及备份恢复。
- preview 摘要与审核绑定、update plan 限制、up 前重新核对、真实资源验证及清理。

现有 Worker 只执行隔离的固定基础自测，不能替代生产任务调度，也不能代表真实部署成功。

## 历史基线

2026-09-08 初始化 FastAPI/React，原后端 14 项测试及前端基础 CI/镜像构建通过；随后 IaC 从 Terraform 改选 Pulumi。2026-09-09 Windows 开发环境已安装 uv 0.12.10、CLI/SDK 3.261.0 并验证常量程序闭环。选型依据及历史兼容结论保留在 [IaC 选型记录](design/iac-selection.md)，本轮新增能力以当前代码和上方验证为准。
