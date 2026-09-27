# 后端待办与验证记录

更新日期：2026-09-25。已有 LangGraph 需求分析和持久方案会话；配置存储仍在设计审阅，最新推荐按用户提出的方向采用 GitLab 公共稳定模板 + PG 个人配置正文和历史。先前全 Git、个人分支方案保留作比较。当前仅完成设计，GitLab、实际集群与资源部署尚未接通；Pulumi 业务接入暂停，现有代码保留。

## Redis 开发计划与阶段进度

完整任务与验收条件见 [Redis 一句话部署开发计划](design/redis-development-plan.md)。本节是跨仓库阶段进度入口；前端 todo 记录前端实现和联调证据。当前从新增阶段 0 开始，文档落档不代表阶段已完成。

- [x] 将用户确认的六阶段计划落档，更新前后端 AGENTS 入口与现行部署口径；仅修改文档。
- [x] 2026-09-13 明确独立软件清单 Git 仓库，补充 catalog/instances 划分、manifest/Kustomize 与参数元数据职责、版本及执行绑定，更新本仓库计划和开发入口。
- [x] 2026-09-13 补充多人配置存放的设计建议：区分集中托管与独立安装、个人设置与实例修订、工作空间归属、共享 Git 读取边界及拆仓后的模板快照。交付模式尚未确定，相关业务能力未实现。
- [x] 2026-09-13 补充个人 Namespace 与外部端口设计建议：稳定归属映射、隔离策略、自动/自定义端口、原子预留、共享 Listener 协调和失败/删除释放规则，映射到现有阶段 1–6；仅设计说明，尚未实现。
- [x] 2026-09-14 完成 [GitLab 配置管理设计草案](design/gitlab-configuration-management.md)，明确正文存储、main/更新分支、固定 SHA 读取、多文件提交、MR、并发恢复、权限和配置页面范围；同步本仓库入口与旧存储建议。
- [x] 2026-09-14 补充 [个人配置分支方案](design/gitlab-personal-branches.md)，说明 main 模板与个人参数组合、固定快照、显式模板升级、个人 MR 目标和分支权限边界。分支模型仍在用户评审中，未实现或创建 GitLab 分支。
- [x] 2026-09-14 补充应用目录发现与配置列表：main 软件索引、个人分支配置索引、固定 SHA 读取、正文与索引同提交、遗漏文件核对和可重建搜索投影。仅设计补充，索引文件、列表接口与同步逻辑未实现。
- [x] 2026-09-14 提供 [GitLab 模板 + PG 用户配置推荐方案](design/gitlab-templates-postgresql-configs.md)，明确 PG 配置正文、不可变修订、模板固定版本、生成产物和备份职责，并同步设计入口。未实现或迁移配置数据。
- [x] 2026-09-25 初始化独立 `E:\goland\projects\olixops-k8s-ctl` Go 项目，参考 Env Vault `origin/init` 建立配置、Gin 路由、Zap 日志、统一响应、请求 ID、健康/就绪接口、测试和 Dockerfile；初始提交为 `9f50411`。`go test ./...`、`go vet ./...`、`go build ./...` 通过，真实 HTTP 健康检查返回 200；尚未接入 client-go 或 POC 集群。
- [x] 2026-09-27 在 `olixops-k8s-ctl` 接入 kubeconfig/client-go、Namespace/StorageClass/工作负载/Gateway 查询，以及受控 kubectl apply dry-run/apply 和 Helm upgrade 接口；提交 `bb2d9b0`。本机 kubeconfig 连接 context `kubernetes-admin@kubernetes` 验证成功：API Server v1.28.15、25 个 Namespace、StorageClass、default Namespace 资源和 GatewayClass 查询返回 200；TCPRoute CRD 当前缺失并被明确报告。ConfigMap server dry-run 通过，Secret manifest 被拒绝；未创建或修改真实集群资源。阶段 1 仍待服务鉴权、Namespace 归属、端口分配和完整 POC 验收。
- [ ] 阶段 0A：建立私有 GitLab 软件清单项目、Redis 包骨架、参数契约与检查入口。GitLab 地址/版本、项目和身份未提供，实际仓库和清单尚未创建。
- [ ] 阶段 0B：配置管理设计待用户审阅；按最终存储模型统一计划和契约，再实现固定模板读取、配置保存/读回、权限、历史与差异页面。最新推荐 PG 保存个人配置，此前个人分支和实例索引不是该方案前提。没有实现代码或创建远端资源。
- [ ] 阶段 1：集群接入与环境核验。补真实鉴权及存储/Gateway 查询，确认目标和 TCP 入口。
- [ ] 阶段 2：固定版本 Redis Kustomize 模板。真实验证认证、读写、持久存储和外部 TCPRoute。
- [ ] 阶段 3：实例、不可变配置修订与 Git 映射。完成数据/接口契约和配置发布错误处理。
- [ ] 阶段 4：独立部署 Worker。指定 commit 执行、持久任务、同实例串行、幂等与故障恢复。
- [ ] 阶段 5：前端固定参数发布。创建、差异、进度、实例详情、修改与显式删除真实联调。
- [ ] 阶段 6：现有 LangGraph 自然语言入口复用上述链路，使用真实模型完成端到端验收。

阶段 0 先落实 GitLab 项目与模板维护流程；0B 先交付可评审的配置管理设计。真实 GitLab 验收需地址/版本、私有项目、读写身份、维护者和检查执行环境。后续环境条件包括 POC 集群/查询地址及执行身份、Namespace/StorageClass、Gateway 控制器与版本及可用 TCP 入口、Worker 读取身份和 Secret 引用方式。真实模型网关在阶段 6 验收。条件缺失时记录已完成的独立工作及阻塞，保留对应阶段待验收状态。

每个阶段完成后在此记录变更与提交、实际检查结果、真实联调范围和剩余问题；既有历史测试结果不作为新增业务阶段验收。

2026-09-10 历史计划落档验证：两端共 13 个 Markdown 文件、80 个本地链接/章节引用检查通过；前端 4 个修改文件的 Prettier 检查通过，两端 `git diff --check` 通过。仅文档变更，未运行应用测试、修改业务代码或连接集群。

2026-09-13 调整范围：新增 [软件清单仓库设计](design/software-manifest-repository.md)，同步本仓库 README、AGENTS、开发计划和本待办。当前仅完成文档约定，未创建远端仓库、提交实际清单或修改应用代码；前端开发入口的阶段顺序待后续跨仓库同步。

2026-09-13 文档验证：本轮 5 个 Markdown 文件、29 个本地链接和代码围栏检查通过，`git diff --check` 通过。仅文档变更，未运行应用测试或连接集群。

2026-09-13 多人配置说明验证：核对现有开发计划、仓库设计、用户归属和认证约定，并对照 GitHub 仓库权限及 Kubernetes 多租户/Secret 官方文档；本次更新的 2 个文档本地链接和代码围栏检查、`git diff --check` 通过。仅补充设计建议，未变更数据库、接口或集群；工作空间权限和各安装仓库绑定待交付模式明确后设计实施。

2026-09-13 Namespace 与端口说明：更新软件清单仓库设计和本待办，对照 Gateway TCP 路由、跨 Namespace 挂接及 Kubernetes 多租户官方文档，并完成独立设计复核。实际 Namespace、端口池、网关版本与权限仍待阶段 1 核实；本次没有变更应用代码或创建集群资源。2 个文档、9 个本地链接及代码围栏检查通过，`git diff --check` 通过；仅文档调整，未运行应用测试。

## 2026-09-14 配置设计与验证

2026-09-15 提交复核：按用户要求收录当前仓库全部 8 个文档改动；45 个本地链接、代码围栏、尾随空白及 Git diff 检查通过。统一 README 分层说明与最新设计入口，保留此前方案用于比较。仅文档变更，未运行应用测试。

新增 GitLab 配置管理设计，并同步本仓库 README、AGENTS、Redis 开发计划、软件清单仓库设计和本待办。已对照 GitLab 官方 API、分支保护、合并方式与 token 范围，并完成配置范围及 API 并发恢复两项独立复核。当前只交付待审阅设计，没有实现接口/数据库/页面，没有创建 GitLab 项目、分支、MR 或连接 POC 集群；前端开发入口的最新阶段顺序仍待后续跨仓库同步。

文档验证：6 个 Markdown 文件、36 个本地链接、代码围栏和尾随空白检查通过，`git diff --check` 通过。仅文档变更，未运行应用测试；真实 GitLab 版本兼容与权限、流水线、并发及恢复行为仍待实施验收。

个人分支补充验证：对照 Git 分支、Kustomize 与 GitLab 权限官方文档，并独立复核模板来源、升级和发布版本边界；本次 4 个文档、18 个本地链接、代码围栏及尾随空白检查通过，`git diff --check` 通过。仅补充待评审方案，未运行应用测试或操作 GitLab。

目录发现补充验证：对照 GitLab 文件与目录 API，独立复核跨版本读取、索引遗漏、权限及并发写入；2 个文档、11 个本地链接、代码围栏和尾随空白检查通过，`git diff --check` 通过。没有创建实际索引文件或调用用户 GitLab，未运行应用测试。

模板与用户配置分离方案验证：对照 PostgreSQL JSONB、GitLab 固定版本读取和 Kustomize 官方文档，独立复核配置修订、发布输入与 PG 备份边界；8 个文档、45 个本地链接、代码围栏及尾随空白检查通过，`git diff --check` 通过。仅设计及入口更新，未运行应用测试、创建业务表、迁移个人配置或操作 GitLab/集群。

## 2026-09-10 框架比较研究

- [x] 对照当前代码与官方文档，比较 LangGraph、LangChain/Deep Agents、Pydantic AI、OpenAI Agents SDK、Google ADK、Microsoft Agent Framework、Dify、CrewAI、Claude Agent SDK，见 [研究笔记](design/agent-framework-comparison.md)。建议保留 LangGraph，未迁移框架或运行替代框架基准。
- [x] 用户已澄清为 DeepSeek Harness 与 Codex harness；专项核实 Python SDK、MCP、审批、会话恢复与现有 runtime 替换边界，见 [Harness 选型研究](design/agent-harness-comparison.md)。有限模板 POC 可保留 LangGraph；通用运维助手可直接选择一个 harness，不默认叠加两套 Agent 循环。
- [ ] 替代框架的 Python 3.14 完整依赖及容器运行兼容性、实际模型网关、MCP 与恢复效果尚未验证；特别验证 DSH SDK 的审批/取消限制，以及 Codex SDK 与 App Server 各集成路径的成熟度边界。

## 2026-09-10 LangGraph 完成

- [x] uv 引入并锁定 LangGraph 1.2.11、PostgreSQL checkpointer 3.1.2、OpenAI SDK 2.54.0；Python 3.14 下可导入、编译并运行真实图。
- [x] OpenAI 兼容网关配置、异步 JSON 结构抽取、Pydantic 部署规格校验；支持 Redis/PostgreSQL 单实例方案，未知参数追问，不支持的需求要求调整。
- [x] LangGraph interrupt/resume、跨运行实例 checkpoint 恢复、pending 节点重试、相同轮次回收；普通 JSON state、限制反序列化类型、关闭外部 tracing。
- [x] 两张带审计字段的业务表与 Alembic 迁移；官方 checkpoint 独立 agent_graph schema，通过 `init-agent` 显式迁移。
- [x] 六个受保护 API、用户会话隔离、请求幂等、revision 冲突、5 个排队任务/20 轮会话限制；后台消费者提交即返回，轮次行锁保护跨实例领取。
- [x] Windows Selector 运行入口、CLI/迁移一致事件循环；模型异常安全映射、SDK 正文日志关闭、trace_id 传递。
- [x] 前端工作台分析入口、任务列表/详情、补充需求与失败重试、方案规格与尚未部署状态。前端检查及浏览器结果见对应仓库 todo。
- [x] 更新 README、数据库设计、[LangGraph 接入文档](design/langgraph.md)、环境变量示例及 Compose/CI 迁移步骤。

## 2026-09-10 验证

- `uv sync --locked`、Ruff lint/format、strict mypy（58 个源文件）通过；实际 OpenAPI 生成包含全部 6 个 Agent 路由。
- **88 个 pytest 通过，6 个跳过**；保留 1 条现有 Starlette/AnyIO 弃用警告。覆盖真实 LangGraph、SQLite checkpoint、模型 HTTP 协议替身、API/Worker/重启恢复，以及既有认证和错误契约。
- SQLite 迁移升降级、`alembic check` 与 PostgreSQL 离线 DDL 生成通过。模型 HTTP 错误、拒绝、截断、非法 JSON、额外代码字段、非法名称和容量均不被当成有效方案；轮次超时取消模型后仍可从 checkpoint 重试，无重复输入。
- 本机 Docker 引擎不可用，启动服务尝试失败；没有创建或修改实际 PostgreSQL/Redis。3 个 PostgreSQL 测试（其中 2 个为新增 checkpoint/并发领取测试）、1 个 Redis 测试未启用；另有 Windows 不适用的 POSIX 测试和未启用的真实 Pulumi 引擎测试跳过。CI 已加入 checkpoint 显式初始化，本轮尚未运行远程 CI。
- 未提供实际网关地址、模型名及 key，因此模型层使用 HTTP 替身验证，不能代表实际模型理解质量或网关联通。没有连接 POC 集群，没有创建 Redis/PostgreSQL 资源。
- 前端 60 项测试及完整检查通过。经 Vite 代理真实登录/API/Worker/LangGraph/SQLite checkpoint 完成创建、追问、补充、两服务规格、列表和刷新恢复；浏览器默认 811px、1280×720 双栏和 390×844 布局通过，无页面横向溢出或控制台 warn/error。模型为临时替身，验收账号退出、临时服务停止，未将替身接入正常配置。

## 2026-09-09 基础能力完成

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

## 2026-09-09 历史验证

- `uv sync --locked`、Ruff lint/format、strict mypy（含脚本）全部通过。
- **70 个 pytest 测试通过，无跳过**；启用了实际 PostgreSQL、Redis 与 Pulumi 引擎。保留 1 条 Starlette/AnyIO 上游弃用警告，无本轮失败。
- PostgreSQL 15：真实迁移和 `alembic check` 通过，表结构与模型一致；并发 refresh 只允许一个请求成功。临时 SQLite 另测迁移升降级。
- Redis 7：连接、读写、TTL 到期与删除均在真实服务通过。
- Pulumi：固定常量及 secret 测试输出程序的 preview → up → outputs → refresh → 无变更 preview → destroy → remove_stack 通过，临时状态清理完成；未使用云 Provider/资源。
- HTTP 经真实 Vite 代理：登录、状态、错误旧密码、改密、全部会话失效、新旧密码验证、退出、旧 token 和 refresh 拒绝通过。
- 浏览器：错误登录、成功登录、刷新恢复、四项基础服务正常、改密后失效与新密码登录、退出及刷新后保护通过；账户/登录页面 1280×720 与 390×844 无页面横向溢出，控制台无 warn/error。
- `docker compose --profile app config --quiet` 通过，PostgreSQL/Redis 容器实际健康。本地完整应用构建在 Docker Hub 获取 Python 镜像授权 token 时网络超时；另用缓存 Nginx 1.27.5 镜像加载前端实际模板，代理宿主 API，已验证登录、身份/状态、Cookie 刷新、退出和撤销。该结果验证真实代理集成，完整生产镜像验收以 CI 为准。
- [x] [Backend CI](https://github.com/Vincentenxy/olixops-agent/actions/runs/34307177818) 在提交 `101cb5a` 上全部通过：真实 PostgreSQL/Redis 测试、迁移检查、应用镜像构建、非 root API 容器登录/刷新/退出验证，以及 Pulumi Worker 容器完整自测。

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

- 当前 Redis 部署工作统一按上方阶段 0–6 推进；先建立软件清单仓库，首次使用固定参数完成部署，最后接真实模型。
- PostgreSQL 实际部署、Redis 高可用、备份恢复及多集群动态管理在首条链路完成后设计。
- Harness 替换、Argo CD/Flux 接管执行仍是后续候选，不是当前开发前置条件。
- Pulumi Provider、业务 Stack、远程 backend、secrets provider 和 update plan 接入暂停，保留历史资料。

现有 Pulumi Worker 只执行隔离的固定基础自测，Agent Worker 只生成部署方案；两者均不能代表真实部署成功。Agent 队列当前使用有界长事务和单进程内消费者；高吞吐独立 Worker、数据保留/删除、生产容量与恢复演练需后续完善。

## 历史基线

2026-09-08 初始化 FastAPI/React，原后端 14 项测试及前端基础 CI/镜像构建通过；随后 IaC 从 Terraform 改选 Pulumi。2026-09-09 Windows 开发环境已安装 uv 0.12.10、CLI/SDK 3.261.0 并验证常量程序闭环。选型依据及历史兼容结论保留在 [IaC 选型记录](design/iac-selection.md)，本轮新增能力以当前代码和上方验证为准。
