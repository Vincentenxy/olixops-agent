# GitLab 配置管理设计

日期：2026-09-14。状态：供用户审阅的设计草案，尚未实现、连接 GitLab 或创建仓库。

最新推荐讨论：[GitLab 稳定模板 + PostgreSQL 用户配置](gitlab-templates-postgresql-configs.md)。用户正在考虑将个人配置正文改存 PG；若采用，本文的全 Git 保存/个人 MR 流程仅作前期方案对照，需按新模型统一实施。当前没有实现可供迁移的配置功能。

最新讨论补充：[main 稳定模板 + 个人配置分支方案](gitlab-personal-branches.md)。用户正在评审分支模型；下文保留前一版“main 汇总稳定配置”方案用于对照。个人分支方案会调整默认读取源、稳定状态与 MR 目标，实施时须统一选定模型，不能把两套规则混用。

用户希望先完成配置保存与读取：配置内容保存在 GitLab，`main` 表示稳定版本，其他分支承载更新。本设计建议将配置管理前移到 [Redis 开发计划](redis-development-plan.md) 的阶段 0B；真实集群和部署仍按后续阶段推进。软件包基础约定见 [软件清单仓库设计](software-manifest-repository.md)。

## 1. 第一版交付什么

提供一个“配置管理”模块：查看稳定配置、创建更新分支、编辑并保存草稿、重新读取、比较差异、提交 Merge Request（MR）、同步合并结果、查看历史和从历史内容创建恢复变更。

后端通过 GitLab REST API 读写指定的私有项目。第一版由维护者在 GitLab 中合并 MR，平台展示检查与合并状态；普通用户通过平台访问自己的配置。后续可增加平台内的合并操作。

本阶段的“稳定”表示配置通过适用的静态检查并进入 main。是否已解析环境、模板是否经过集群验证、实例是否部署成功分别记录。合并 main 不触发资源部署。

## 2. 数据存放

| 内容 | 存放位置 |
| --- | --- |
| 软件 manifest、Kustomize base、参数 schema、模板元数据 | GitLab `catalog/` |
| 个人空间的部署默认值 | GitLab `workspaces/<workspace_id>/defaults.yaml` |
| 实例期望参数、凭据引用、解析后生成的 overlay | GitLab `instances/<workspace_id>/<config_id>/` |
| 已保存的配置草稿 | 同一 GitLab 项目的更新分支 |
| 稳定配置与历史正文 | main 及对应完整 commit，可选发布 tag |
| 用户、空间归属、访问权限 | PostgreSQL |
| Git 项目/路径/SHA 索引、MR 关联、操作幂等、验证和流程状态 | PostgreSQL；不保存第二份配置正文 |
| 密码、模型 key、GitLab token、集群凭据 | 受控凭据存储；Git 只保存引用 |

这里的“配置全部在 Git”包括部署默认值和保存后的草稿，覆盖之前“默认值/草稿在数据库”的建议。用户尚未点击保存的编辑内容只在页面内存中；只有 GitLab 提交成功并核对后才显示“已保存”。配置正文不进入数据库、请求日志或审计正文；缓存可以保存受控的临时副本，但必须能按 SHA 重建。

GitLab 地址、项目 ID、访问凭据引用和平台自身数据库连接属于启动配置，通过环境变量/受控挂载注入，避免读取配置仓库前又必须先读取自身连接配置。GitLab 凭据不放回其所访问的仓库。

## 3. 仓库与目录

建议一个私有 GitLab 项目 `olixops-manifests`，名称和项目地址待提供。目录使用稳定 ID；用户名、配置显示名称修改不移动文件。

```text
olixops-manifests/
├── README.md
├── .gitlab-ci.yml
├── catalog/
│   └── redis/standalone/v1/
│       ├── package.yaml
│       ├── parameters.schema.json
│       ├── base/
│       └── examples/
├── workspaces/
│   └── <workspace_id>/defaults.yaml
├── instances/
│   └── <workspace_id>/<config_id>/
│       ├── config.yaml          # 用户期望；含模板、参数、访问策略
│       └── overlay/             # 环境解析后才生成
│           ├── kustomization.yaml
│           └── patches/
└── tests/
```

`config_id` 是配置对象的稳定身份，后续真实实例关联此 ID。第一版个人空间映射到已有认证用户，团队成员管理不作为配置存取前提。服务端依据授权决定目录，用户不直接提交仓库路径。目录不是 GitLab 的用户权限边界；共享项目只向平台身份和受信任维护者开放，客户需要直接 clone 时使用独立私有项目。

软件包元数据和配置 schema 是平台约定。参数到 overlay 由固定实现生成；修改参数时禁止独立修改生成文件形成两套相互矛盾的内容。软件维护者可以维护包内 YAML，普通用户仅修改 schema 允许的参数。已发布的模板 `v1` 不原地修改，修复或升级发布 `v2` 等新版本。

## 4. 分支和版本

| 引用 | 作用与建议规则 |
| --- | --- |
| `main` | 当前稳定配置集合；受保护，只通过 MR 更新 |
| `changes/<config_id>/<change_id>` | 某个配置的一次更新；从确定的 main SHA 创建，允许多次保存提交 |
| `templates/redis/<change_id>` | 维护者的软件包更新，单独审查 |
| `defaults/<workspace_id>/<change_id>` | 部署默认值更新，仅影响以后生成的配置 |
| `stable-2026.09.1` 等 tag | 可选的全仓稳定快照名称；发布后按约定禁止移动/覆盖 |
| 完整 commit SHA | 精确读取、检查、审阅和后续部署的版本身份 |

分支承载修改过程，commit 固定一次保存的内容；tag 给稳定快照命名。模板版本、Redis 软件版本、镜像 digest 分别表达各自内容，不能用一个分支名代替。

第一版使用 main + 短期更新分支即可。需要同时维护多条长期版本线时，再引入 `release/<version>`。用户/环境通过目录和权限归属管理，不以长期分支充当用户隔离。已合并更新分支可清理；尚需读取的未合并历史保留可达引用，第一版不自动删除未合并分支。

建议 GitLab 设置：main 禁直接 push、禁 force push，允许 Maintainer 合并；合并方式使用 fast-forward，禁用 squash 和自动 rebase before merge。main 前进导致无法快进时，更新候选基线并重新检查、审阅，不能继承旧检查结果。配置并发量增大后再评估合并队列。

基础方案使用 MR、分支保护和成功流水线：项目启用 `Pipelines must succeed`，不允许 skipped pipeline 作为成功，CI 确保每个 MR 的最新候选 SHA 都实际运行适用的检查。此方案不依赖付费的强制多人审批/Code Owner 规则。第一版的维护者审阅是操作流程；是否增加 GitLab 强制审批，按实际版本和许可证决定。

## 5. 配置读取

1. 后端先检查当前用户对配置对象、个人空间或模板的权限。
2. 默认选择 main；查看更新时使用平台已登记且有权访问的变更，查看历史时使用该对象已登记的修订。
3. 将分支或 tag 解析为完整 commit SHA。一次详情、差异或文件包读取的所有文件均固定在同一 SHA，避免 main 在请求中途变化导致混合版本。
4. 读取对应文件，校验大小、格式、schema 和引用，返回配置正文、SHA、配置检查状态及环境待解析项。
5. 如使用缓存，按 `(GitLab项目, SHA, 文件路径)` 标识，并在命中缓存前继续鉴权。GitLab 不可用时明确报错；若提供历史缓存，必须显示其版本与过期状态。

列表、目录、文件内容、历史、diff、MR 摘要及导出均按对象范围过滤。用户不能通过任意项目 ID、文件路径、分支名或裸 SHA 读取同项目其他用户内容。全仓 commit 消息和 MR 标题也可能包含其他用户信息，不原样透传给普通用户。

## 6. 保存、审阅与进入 main

以“将我的 Redis 内存从 512Mi 改成 1Gi”为例：

```text
读取 main@A 的本人配置
  → 创建 changes/<config_id>/<change_id>，基线固定为 A
  → 编辑参数并校验
  → 一次提交保存相关文件，得到候选提交 B
  → 按 B 重新读取和查看差异，运行检查
  → 创建目标为 main 的 MR
  → 维护者检查当前候选与流水线，在 GitLab 合并
  → 平台核对实际合并结果，登记稳定修订
```

保存采用 Commits API 的多文件 `actions[]`：同一组配置以一个 Git commit 保存，不逐文件生成互不完整的修订。后端对同一变更串行处理，客户端提交 `expected_commit_sha`；已知版本不同则返回配置冲突，由用户重新读取。更新/删除已有文件同时使用其 `last_commit_id`。

`last_commit_id` 仅是文件级前置条件，不是分支 HEAD 的原子 CAS；`start_sha` 也不提供已有分支的 CAS。平台锁只能协调自身请求。写后要求返回 commit 为单父提交，且 `parent_ids[0] == expected_commit_sha`；这里比较保存前的更新分支 HEAD，不是最初 main 基线。同时核对文件摘要和整个变更范围；发现意外内容时保留返回 SHA，标记“已写入但冲突待核对”，禁止提交为稳定配置或立即重复保存，不通过 force 覆盖。

检查与审阅绑定候选 SHA、基线 SHA、允许路径和验证器版本。MR 更新、候选 rebase 或配置默认值解析变化都需要重新生成检查结果。第一版禁止用户修改 CI、模板目录、其他空间目录及可执行文件；维护者的模板变更走单独流程。GitLab CI 对候选提交检查 schema、文件引用、生成内容一致性和适用的 Kustomize 渲染；未解析环境的配置只接受“意图校验”，不会被标记可部署。

合并后登记该 MR 实际进入 main 的提交，核对候选内容及其在 main 历史中的关系；不能简单读取当时最新 HEAD 后把别人的后续提交当成本次版本。快进且不 squash 时应与被核对的候选一致。未来若增加 API 合并，MR merge 的 `sha` 参数只校验源分支，仍需遵守 main 的快进与重新检查规则。

main 上其他用户配置的变更不自动发布本人的实例。阶段 3–4 的发布任务只消费明确实例、配置路径及完整稳定 SHA，部署结果另行记录。

## 7. 未接集群时如何保存

先保存部署意图，例如 `namespace_policy: workspace`、`access.mode: external`、`port_allocation: auto`，或用户提出的 `requested_port`。这些是平台业务参数，不是可直接提交给 Kubernetes 的字段。

本阶段可验证参数类型、模板引用和允许范围。Namespace 是否存在、StorageClass 是否可用、端口是否可分配仍是待核验状态。阶段 1–3 完成真实环境解析和端口原子预留后，将确定的 Namespace、端口及 overlay 保存为新的具体修订，再进入发布流程。Worker 不在执行时悄悄替换配置值。

修改默认值不会改变已经保存的实例参数；生成配置时将实际使用的默认值展开并固化。配置状态建议分别展示“草稿 / 审阅中 / 已稳定”“检查待运行 / 通过 / 失败”“环境未解析 / 已解析”；后续增加独立部署状态，避免一个 ready 字段混用。

修改已解析配置的参数时，原解析结果和生成 overlay 必须失效。保存意图修订时移除不再匹配的生成文件；重新解析、生成和检查一致的新修订后才允许部署。旧稳定修订仍可按其 SHA 查询，不将新参数与旧 overlay 混用。

## 8. 失败、幂等和历史恢复

| 情况 | 处理 |
| --- | --- |
| GitLab 鉴权失败、超时或限流 | 明确错误/待核对状态，不显示已保存，不写 main |
| 同一个 request_id 重试 | 按操作者和操作范围匹配请求摘要；内容不同拒绝，内容相同复用结果 |
| Commit 已成功但回执或 DB 写入失败 | 操作元数据记录预定分支、基线、文件摘要与 operation_id；查询 GitLab 提交并核对内容，恢复索引，避免重复提交 |
| 尚无远端提交且请求正文已丢失 | 不从不存在的 DB 副本重建；要求客户端以同一操作标识重新提交原内容，页面保留未保存状态 |
| MR 创建成功但回执丢失 | 根据项目、受控源分支及操作标识核对已有 MR，不重复创建 |
| 多人修改同一配置或 main 已前进 | 返回冲突/需要更新基线；重新读取、生成差异和检查，不自动覆盖 |
| GitLab 已合并但平台未收到结果 | 通过按需刷新/恢复任务读取 MR 和确定提交，更新索引；第一版不依赖 webhook 才能恢复 |
| 恢复旧配置 | 从当前 main 创建新更新分支，只恢复该配置的历史内容，经 MR 进入 main；保留其他用户的更新 |

数据库操作记录只保存恢复所需的 ID、引用、摘要和状态，不持久保存配置正文。Git 与数据库没有跨系统事务，外部结果未知时优先核对；不宣称 REST 写操作天然 exactly-once。历史恢复不会 reset main，也不恢复 Redis 数据。配置删除同样先作为变更审阅；Git 删除不直接删除集群资源。

外部写入前先提交持久操作意图；commit message trailer 或 MR 描述附带不含敏感信息的 operation ID。恢复同时核对操作标记、受控分支、预期父 SHA 和内容摘要，不能仅凭相同正文判定重试成功。存在未决操作时阻止同一变更继续保存或提交 MR，核对完成后再继续。持久意图不含配置正文，必要时由客户端重传原请求。

## 9. 后端与页面接口草案

延用 README 的 API → service → repository 分层，GitLab HTTP 调用封装到 integration。所有接口需认证，遵守 GET/POST 和统一 `{code,msg,data}`；以下是待实现契约名称。

| 平台接口 | 主要输入/结果 |
| --- | --- |
| `POST /api/v1/configs/list` | 个人空间、分页条件；返回有权查看的配置摘要 |
| `POST /api/v1/configs/read` | config_id + 稳定/变更/历史选择；返回正文、完整 SHA 和状态 |
| `POST /api/v1/configs/changes/create` | 创建配置或修改已有配置，request_id + 期望基线；返回 change_id |
| `POST /api/v1/configs/changes/save` | change_id、expected_commit_sha、受控配置内容、request_id；返回提交 SHA 或待核对操作 |
| `POST /api/v1/configs/changes/diff` | change_id；返回指定两个 SHA 间、本配置范围内的完整差异 |
| `POST /api/v1/configs/changes/submit` | change_id + expected_commit_sha；触发检查并创建/复用 MR |
| `POST /api/v1/configs/changes/status` | change_id；读取检查和 MR 状态，核对 GitLab 后同步结果 |
| `POST /api/v1/configs/history` | config_id、分页；返回该配置的可访问历史修订 |
| `POST /api/v1/configs/changes/restore` | config_id + 历史修订 ID；创建恢复变更，不直接覆盖稳定版本 |
| `POST /api/v1/configs/operations/read` | operation_id；读取保存/提交结果与待核对状态 |

模板和默认值通过同一存储服务复用流程，分别校验维护者与个人空间权限。正式 API/schema 和错误码在实现时补入 OpenAPI；配置冲突、GitLab 不可用等使用明确业务码，HTTP 错误仍按 README 标准正文。此处没有发布集群的接口。

个人空间默认值提供 `POST /api/v1/configs/defaults/read` 和 `POST /api/v1/configs/defaults/changes/create`，后续保存、差异和 MR 复用 change_id 流程；页面包含“部署默认值”的读取与修改入口。

页面第一版包括配置列表、参数编辑及只读 YAML 预览、稳定/更新版本切换、差异与检查结果、MR 状态和配置历史。普通用户由平台查看差异；只有具备 GitLab 项目权限的维护者需要打开 MR 链接。保存会显示提交版本，提交审阅后显示当前候选版本，避免把本地未保存文本当成远端内容。

需要持久化的逻辑对象为配置索引、配置修订索引、变更单和 Git 操作记录；包含所有者、project/path/SHA、摘要、幂等标识及状态。实现前按 README 在 `design/database.md` 补正式表结构、审计字段及迁移，当前不创建数据库表。

## 10. GitLab 接入方式

| 用途 | GitLab 能力 |
| --- | --- |
| 解析分支与创建分支 | Branches API；使用确定的起点 SHA |
| 读取指定文件 | Repository Files API，`ref=<完整SHA>` |
| 原子保存多个文件 | Commits API，单次 actions 提交 |
| 创建/读取审阅状态 | Merge Requests API |
| 固定提交下载配置包 | Repository Archive API，`sha=<完整SHA>` + 受控 path |
| 可选稳定版本命名 | Tags API；第一版不要求自动创建 tag |

目录列表需处理分页。Tree API 在目标 GitLab 版本下使用 SHA 的行为列入联调；整包读取可使用明确支持 SHA 的 Archive API。文件包校验路径、大小、数量、符号链接和外部引用，不能从归档访问授权目录外文件。API diff 如被截断，须补齐文件比较或拒绝提交审阅，不能展示不完整差异后标记检查通过。

后端 REST 读身份使用满足接口范围的 `read_api`，写身份使用 `api` 并限制项目角色；`write_repository` 只授权 Git-over-HTTP，不足以调用 REST 写接口。第一版写身份负责更新分支和 MR，main 由维护者合并。未来 Worker 仅 fetch 时使用 `read_repository`。凭据只在服务端使用，验证 GitLab TLS，不向请求任意地址或重定向转发 token。

优先使用目标项目范围内的访问身份。自建 GitLab 的 Project Access Token 与 GitLab.com 对该能力的许可要求不同，实际安装时核对；如目标不支持项目 token，可用仅加入该项目的专用账号，避免复用个人管理员凭据。

## 11. 实施顺序与验收

1. **0A：仓库和契约。** 确定 GitLab 项目、main 规则、目录、Redis 包与参数 schema；安装/固定适用的配置验证器。
2. **0B-1：只读链路。** 接通认证后的配置列表、固定 SHA 读取、历史和空间权限；同一次多文件读取不会混入另一个版本。
3. **0B-2：更新保存。** 更新分支、多文件提交、重新读取、差异、并发冲突和幂等恢复；配置正文及草稿均可在 GitLab 定位。
4. **0B-3：稳定版本流程。** MR、校验、维护者合并、平台同步；配置页面完成真实 GitLab 联调，并能从历史创建恢复变更。
5. **后续阶段：** 核实集群并验证模板，建立真实实例/Namespace/端口预留和可部署修订，再实现部署 Worker、完整发布页面与自然语言入口。

验收至少覆盖两个用户不能互读配置/历史/差异、保存后重启仍能按 SHA 读取、多文件提交一致性、并发更新、GitLab 失败与回执丢失、main 前进后重验、MR 合并后版本定位、恢复单个配置不影响其他配置，以及仓库和日志不含凭据。真实 GitLab 检查与替身测试分别记录。配置管理验收不连接 POC 集群，也不代表 Redis 可部署。

实施需要的外部信息：GitLab base URL、实际版本及部署形态、私有项目 ID/路径、main 当前状态、服务身份与受控凭据注入方式、维护者、CI Runner 或可落实的检查执行环境。此次只交付设计，未向用户索取密钥，未创建项目、分支或 MR。

## 官方依据

- [Repository Files API](https://docs.gitlab.com/api/repository_files/)：固定 ref 读取与文件内容接口。
- [Branches API](https://docs.gitlab.com/api/branches/)、[Commits API](https://docs.gitlab.com/api/commits/)：分支及多文件提交、文件版本前置条件。
- [Repositories API](https://docs.gitlab.com/api/repositories/)：目录、归档与比较限制。
- [Merge Requests API](https://docs.gitlab.com/api/merge_requests/)、[合并方式](https://docs.gitlab.com/user/project/merge_requests/methods/)：合并条件及重验边界。
- [Protected branches](https://docs.gitlab.com/user/project/repository/branches/protected/)、[MR approvals](https://docs.gitlab.com/user/project/merge_requests/approvals/)：保护与审批能力边界。
- [合并前要求流水线成功](https://docs.gitlab.com/user/project/merge_requests/auto_merge/#require-a-successful-pipeline-for-merge)：稳定配置的检查门禁。
- [Token scopes](https://docs.gitlab.com/security/tokens/access_token_scopes/)、[Project access tokens](https://docs.gitlab.com/user/project/settings/project_access_tokens/)：凭据范围及许可区别。
