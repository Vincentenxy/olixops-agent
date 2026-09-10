# LangGraph、DeepSeek Harness 与 Codex Harness 的适配研究

> 当前实施入口：[Redis 开发计划](redis-development-plan.md)。用户已暂停 Pulumi 业务接入，先保留现有 LangGraph 完成 Redis 链路；本文是候选运行时研究，以下迁移方案和 Pulumi 路线不代表当前开发任务。

研究日期：2026-09-10。用户确认此前的 `dsh` 指 **DeepSeek Harness**，另一个候选指 **Codex 的 harness**。DeepSeek Harness 是 DeepSeek 官方独立开源项目，与 LangChain Deep Agents 不同；本篇补充 [原框架比较](agent-framework-comparison.md)，不代表已迁移或安装。

当前业务目标是为已有 POC Kubernetes 集群开通 Redis/PostgreSQL。项目已有 Python 3.14、FastAPI、React、LangGraph 分析与追问、持久任务和 Pulumi 基础 Worker；实际 MCP 查询、Helm 模板与部署闭环仍待开发。[当前实现](langgraph.md)、[执行规范](../README.md#agent-与部署执行规范)。

## 三者首先是不同层次的选择

| 选择 | 本项目主要评估什么 | 仍由平台负责什么 |
| --- | --- | --- |
| LangGraph | 显式状态、流程分支、追问和 checkpoint；已有实现 | 用户与环境权限、任务调度、模板、资源幂等、Pulumi state |
| DeepSeek Harness | 组合 Agent 循环、模型、工具、上下文、会话、沙箱和 UI 的可替换插件运行时 | 上述业务职责，以及 Harness 子进程、会话存储与现有任务的映射 |
| Codex harness | Codex 执行 Agent 的运行底座，通过官方 Python/TypeScript SDK 或 App Server 嵌入产品 | 上述业务职责，以及运行时进程、会话存储和事件/审批适配 |

这个分层是针对本项目的架构判断。Harness 可以承载完整 Agent，不必强行套在 LangGraph 里面；也可以只承接仓库分析、诊断等局部工作。只有确实需要两个层次各自的能力时，才同时运行两个编排循环。

下表的事实来源在后文各节，适配评价是工程判断，未进行速度、成本或准确率排名。

| 对比项 | LangGraph（当前项目） | DeepSeek Harness | Codex harness |
| --- | --- | --- | --- |
| 控制方式 | Python 显式图，当前只做理解、校验和追问 | 完整工具循环，各子系统可通过插件替换 | 完整工具循环，通过 SDK、MCP、Skills、配置和协议扩展 |
| Python 接入 | Python 库，已经落地 | 官方 Python SDK + 配套独立 runtime | 官方 Python SDK + 固定版本 CLI runtime |
| 深度定制 | 自己编写节点和状态 | 适合需要替换循环、存储或模型适配的团队；原生插件主要是 TypeScript | 优先使用公开接口；修改内部运行机制需评估源码维护成本 |
| 现有私有 MCP | 待接客户端/适配器 | stdio、HTTP；目前桥接 tools | stdio、HTTP；有工具筛选与审批配置 |
| 人工交互 | 已有 interrupt/resume；部署审核仍待开发 | Harness 有审批，SDK 尚未接通双向审批及轮次取消 | App Server 已有审批请求/答复协议；具体 SDK 与传输路径需验证 |
| 恢复 | 已有 PostgreSQL checkpoint | 持久会话日志和恢复；本地后台 jobs 不是持久队列 | 存储的 thread 可继续/分叉；不是部署操作事务 |
| 当前适用方向 | 有限模板的一键开通 | 深度定制的通用运维 Agent | 复用现有完整执行能力的通用运维 Agent |

## DeepSeek Harness 官方核实

### 项目、语言与可扩展性

官方站点明确链接到 `deepseek-ai/deepseek-harness`，以 MIT 许可证开放源码。Cordis 内核负责插件加载、卸载和依赖；Agent 循环、模型、工具、会话、存储、沙箱和 UI 都能通过配置组合。标准模式具有代码、文件、Shell、查询、Skills、子 Agent 等能力；PTC 模式可让模型用 TypeScript 组合多步工具操作。[官方介绍](https://www.deepseek.com/harness/)、[官方仓库](https://github.com/deepseek-ai/deepseek-harness)。

插件及运行时扩展以 TypeScript/Cordis 为主，`agent/*`、`tools/*` 等事件提供拦截位置。`web`、`sdk`、`headless` 等是不同组合；自有 React 前端可以使用 SDK 集成，不必嵌入原生 Web UI。插件注册接口、运行循环及存储实现均可替换。[架构文档](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/architecture.md)、[工具执行管线](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/tool-execution-pipeline.md)。

### Python 与 TypeScript 接入

已有官方 `deepseek-harness-sdk`，Python 声明要求为 `>=3.10`，依赖 Pydantic 2。客户端通过 stdio JSON-RPC 启动并控制 `dsh` 子进程；普通安装包含匹配版本的原生运行时 wheel，因此 **使用 Python SDK 不需要另装系统 Node.js**。这仍是嵌入 Node 依赖树的独立运行时，不是将 Cordis 改写成 Python。源码构建和外部插件管理另需相应 Node/pnpm 工具链。[Python SDK](https://github.com/deepseek-ai/deepseek-harness/blob/master/python/sdk/README.md)、[运行时分发](https://github.com/deepseek-ai/deepseek-harness/blob/master/python/sdk-runtime/README.md)、[Python 依赖声明](https://github.com/deepseek-ai/deepseek-harness/blob/master/python/sdk/pyproject.toml)。

TypeScript 有 `@deepseek-ai/dsh-sdk-client`，同样拥有子进程并使用该 JSON-RPC 协议，可接收会话事件和通知。SDK 返回最后提交的根会话响应；一次 `run()` 表示从输入入队到整个 Agent 空闲的活动区间，不保证回答仅由这一条 prompt 产生。[TypeScript SDK](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sdk/client/README.md)。

对本项目而言，可以保留 Python/FastAPI，通过独立 Worker 调用官方 Python SDK。若要新增 Harness 内部能力，可写 TypeScript 插件；已有 Python 查询或部署服务可通过受控 MCP/API 暴露。不能把“提供 Python 客户端”理解成“所有原生插件都用 Python 开发”。Python 3.14 在声明范围内，但本次没有安装验证其完整依赖与平台 wheel。

### 模型与私有 MCP

默认有 DeepSeek 直连适配器，官方 `llm-pi-ai` 插件还能连接多个供应商、OpenAI 兼容网关和自托管服务，支持单独指定路由、协议、模型及凭据。因此不能评价为只能使用 DeepSeek；实际网关的工具调用、思考字段、上下文及结果质量仍需逐项验证。[多供应商适配器](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/llm/llm-pi-ai/README.md)。

官方 MCP 插件支持私有 `stdio` 和 `streamable-http`，HTTP 可配置鉴权 headers，本地服务可配置环境变量。工具通过稳定名字注册到 Harness；有超时、重连及工具列表更新。当前桥接 **tools**，不支持 MCP resources/prompts；若现有 MCP 查询用 resources 提供，需要另做适配。默认不启用任何 MCP server。[MCP 客户端](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.md)。

### 工具权限、审批与隔离的实际边界

工具管线具备调用前后拦截、不可放宽的 guard，以及单次审批。审批服务支持 `ask`/`never`，无可用答复时拒绝；`never` 不是自动允许。[审批服务](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/approval.md)。

但当前 **SDK 协议尚未实现服务端向客户端发起审批请求，也没有单会话关闭或轮次取消方法**；需要放弃运行时，客户端通过关闭进程处理。协议文档也明确目前没有版本协商保证。不能把 DSH Web 的交互审批直接标成我们的 React 通过 SDK 已经可用。我们可以继续使用平台自己的持久审核接口、授权令牌和受控执行工具，或另行实现经过验证的审批插件桥接。[SDK 协议及限制](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sdk/protocol/README.md)、[SDK 服务端边界](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sdk/server/README.md)。

本地沙箱提供 Linux、macOS、Windows 后端；其 `read-only`/`workspace-write` 词汇约束的是文件效果，网络和进程可见性不在此承诺内，部分平台或旧内核只能提供 partial enforcement。因此 K8s 权限和可访问网络仍需由 Worker 容器、凭据作用域和环境配置限制。[沙箱文档](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/sandbox.md)。

官方 Python 教程的 `sdk-minimal` 为最小实验组合，固定为 `danger-full-access`，只有持久 Shell 等少量组件，也没有上下文压缩和完整工具集；不可把这个演示配置直接作为我们的默认部署 Worker。[Python 教程的配置说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/guide/python-sdk.md#understand-the-minimal-profile)。

### 会话恢复与后台执行

DSH 有持久事件日志、会话恢复与分叉，存储后端可以替换。当前常规文件后端使用 JSONL；持久层区分 append 接收和 flush 落盘屏障，恢复时会补齐中断轮次的结束标记与缺失工具结果。这有助于继续对话，但不能推导为失败的外部创建操作绝不会重复。[持久化与崩溃恢复](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/persistence.md)。

后台 jobs 抽象提供运行、等待、输出读取和取消。官方 `LocalJobRegistry` 是进程内 provider，所属 Agent 释放时会取消并等待其工作；生产者自己拥有执行资源。它不能直接替代本项目 PostgreSQL 持久部署队列，不能将 runtime 的后台 Bash 等同于 Worker 重启后的可靠业务任务。[后台任务运行时](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/jobs.md)。

## Codex harness 官方核实

### 定位与 Python 接入

这里的 Codex harness 指 Codex 的 Agent 运行底座；公开嵌入入口是 **Codex SDK / App Server**，不同于 OpenAI Agents SDK，也不是当前项目安装的模型 API 客户端 `openai`。

官方 Python 包为 `openai-codex`，要求 Python `>=3.10`，提供同步 `Codex` 和异步 `AsyncCodex`，通过本地 App Server JSON-RPC 工作，发布包包含固定版本 CLI runtime。文档将 Python SDK 标为 stable；TypeScript SDK 为 `@openai/codex-sdk`，服务端运行要求 Node.js 18+。因此本项目无需为了调用 Codex 将 FastAPI 改写为 Node 服务。[Codex SDK](https://learn.chatgpt.com/docs/codex-sdk)。

SDK 是嵌入入口，仍需要管理独立运行时进程和工作目录。对我们的 Python 3.14 与目标容器，版本声明不能代替安装、平台二进制和运行验证。

### MCP、模型与交互

Codex 支持本地 stdio 和远程 Streamable HTTP MCP，支持 headers、Bearer/OAuth、工具白名单、超时及逐工具审批配置。现有查询 MCP 可以继续作为平台工具来源，不要求改成公网服务。[MCP 配置](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)。

官方允许自定义 model provider、网关地址和鉴权，也支持本地模型 provider，因此不能说 Codex 只能接 OpenAI。当前项目使用 Chat Completions；接入前仍要验证所选 runtime/provider 的协议、流式工具调用和模型行为，不能仅靠更换 base URL 假设兼容。[模型 Provider 配置](https://learn.chatgpt.com/docs/config-file/config-advanced#custom-model-providers)。

App Server 面向自定义客户端，提供会话历史、流式事件和双向审批；命令/文件审批请求携带 thread/turn/item 标识，客户端返回决定后继续或拒绝操作。已有 thread 可以 resume/fork。这些接口适合映射到我们的 React 对话与待确认界面，但不会自动生成平台前端。[App Server：审批](https://learn.chatgpt.com/docs/app-server#approvals)、[会话恢复](https://learn.chatgpt.com/docs/app-server#start-or-resume-a-thread)。

### 成熟度必须按接口判断

Python SDK 文档标为 stable；与此同时，App Server 文档在远程 Code Mode 章节明确将 app-server command 和 WebSocket transport 标为 experimental、不支持生产负载，Protocol 章节也重复标注 WebSocket 的实验性。因此不能将 SDK 的 stable 标签扩展为所有 App Server/远程接入路径均已生产支持。[SDK 发布状态](https://learn.chatgpt.com/docs/codex-sdk#python-library)、[App Server 传输说明](https://learn.chatgpt.com/docs/app-server#protocol)。

本项目若试接，优先验证固定版本官方 Python SDK 与本地运行时，单独核对审批处理和重启恢复；React 通过现有 FastAPI 访问。是否需要直接使用协议，应由 SDK 实际覆盖情况决定。官方已将 `codex mcp-server` 标为 deprecated，新接入不以此作为默认方案。[SDK 集成入口](https://learn.chatgpt.com/docs/codex-sdk)。

## 接入 olixops-agent 的实际新增工作

当前 [Agent Worker](../app/workers/agent.py) 已依赖 `AgentTurnRunner.run_turn(task_id, turn_id, message) → GraphResult` 协议。可以用任一 harness 实现这一层适配，替换 [AgentRuntime](../app/agents/runtime.py) 的图与 checkpoint 管理，保留 FastAPI、鉴权、业务任务表、Pydantic 和前端 API。现有实现还不是通用工具 Agent 循环，因此完整迁移无需默认叠加 LangGraph 与 harness。

选择 Codex 时需要关联平台 task/turn 与 Codex thread/turn，处理审批事件和 runtime 生命周期；选择 DSH 时需要处理对应会话、插件及 SDK 缺口。二者都应继续保留业务任务的请求幂等、用户归属和 revision 约束，不能直接把会话日志当作业务数据库。

以 DSH 为例，具体新增工作集中在 Agent 执行层：

1. 固定 SDK、runtime 和插件版本，构建 Worker 镜像；生命周期明确管理子进程、执行超时、退出和容量。SDK 普通轮次默认可能无总时限，需要设置平台边界。
2. 定义本平台 `user_id/task_id/turn_id` 与 DSH `home/session_id/message_id` 的关系；同一会话串行处理，事件经验证和脱敏后投影到已有前端状态。
3. 持久挂载或实现 DSH 会话存储，统一备份和删除；DSH home 还可能包含配置、凭据和插件，不能仅凭不同 session_id 就认为完成用户隔离。
4. 组合专用运维 profile，只开放环境查询、模板选择、校验、预览和受控任务工具；继续由 Pydantic 验证输出规格。平台审核、Stack 归属及凭据都在受控服务边界内落实。
5. 迁移或保留已有进行中的 LangGraph 会话；现有 checkpoint 与 DSH 日志不是兼容格式。继续保持请求幂等、revision 冲突和错误契约。
6. Pulumi 的长任务仍由部署 Worker 执行，恢复后核对 Stack、操作历史和真实资源。Agent 的 `completed`/`idle` 不能表示 Redis 已完成 PING 或 PostgreSQL 已通过 SELECT 1。

以上是基于公开接口与本项目状态的工程推断，不是已经运行过的集成结果。

## 当前取舍与验证范围

仅就“已知集群开通 Redis/PostgreSQL”而言，LangGraph 加受控模板足以完成目标，继续现有实现的新增成本较小。若目标扩大到通用运维助理，需要自主选择查询工具、查日志、阅读仓库、组合诊断步骤，**直接选择一个完整 harness 是合理路线**，已有分析图不构成否决迁移的理由。

如果优先复用执行能力并接入现有 Python/React 产品，建议先验证 Codex 官方 Python SDK 及审批事件接入；如果优先掌握和替换循环、上下文、存储、模型等内部机制，DSH 的插件架构更贴近该目标。前者需要确认 SDK/协议成熟度边界和目标模型适配；后者需要选择平台审批工具或补齐 SDK 审批桥接，设计 SDK 取消缺口的处理方式，并接受预览期变更。这是原型验证顺序的建议，尚不是最终迁移决定，也不是模型能力高低的结论。

无论采用哪种方案，建议产品结构保持为 `React → FastAPI → 单一 Agent runtime → 受控查询/部署工具 → Pulumi Worker → Kubernetes`。长时间部署从当前持有数据库事务的分析消费者中分离，由持久部署任务承接；集群凭据、预览与规格版本绑定、同 Stack 串行和执行结果核对仍由平台实现。用户继续通过 Web 使用，后端和 Worker 可以容器化运行，不要求每位用户安装 harness 客户端。

DSH 官方明确提示开发者预览期间会有兼容性破坏。采用它应固定版本并验证升级迁移、会话恢复、SDK 取消和审批桥接，而不是直接跟随 `latest`。本次检索到的官方仓库 master tree 为 `b2e3b2a0125854567a4a5fcba75782e42fe84901`；文档链接指向 master，后续实现前应核对实际发布版本。[官方预览说明](https://github.com/deepseek-ai/deepseek-harness#developer-preview)。

本次仅阅读官方介绍、仓库文档和 SDK 声明；没有运行 npx、安装替代框架、连接 MCP/K8s、变更依赖或部署资源，也没有模型质量、时延、成本和恢复实测。建议原型共用验收集：缺参追问、MCP 断线、权限拒绝、修改参数后旧预览失效、重复提交、用户隔离、等待输入时重启、资源已创建但响应丢失，以及取消后的资源核对。
