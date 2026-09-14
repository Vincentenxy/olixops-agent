# 软件部署清单 Git 仓库

2026-09-14 最新推荐讨论见 [GitLab 稳定模板 + PostgreSQL 用户配置](gitlab-templates-postgresql-configs.md)。采用该模型时 GitLab 只管理公共模板，个人配置与历史在 PG；下文包含先前全 Git 方案的目录和流程约定，实施前按最终选定模型统一，不能同时将两处当作个人配置的权威存储。

2026-09-13 用户调整：平台需要一个独立 Git 仓库，集中存放各软件的部署 manifest。2026-09-14 进一步指定 GitLab、main 稳定分支和更新分支，先设计配置保存与读取；详见 [GitLab 配置管理设计](gitlab-configuration-management.md)。本文将原计划中的“配置 Git 仓库”具体化，作为 [Redis 开发计划](redis-development-plan.md) 的阶段 0。本文只完成架构约定；仓库名称、远端地址及访问身份尚未确定，实际仓库和 Redis 清单尚未创建。

## 仓库职责

软件清单仓库与后端、前端代码仓库分开，初版使用一个独立的私有 GitLab 项目，按目录区分通用软件包、部署默认值和具体实例。main 保存稳定配置，短期更新分支保存修改与草稿；完整 commit 固定一次读取或发布的内容。`olixops-manifests` 是建议名称，尚未指定或创建同名远端仓库。

| 内容 | 保存位置与用途 |
| --- | --- |
| 软件标准部署包 | `catalog/`：Kubernetes YAML manifest、Kustomize 配置、软件配置、支持参数、来源与版本说明 |
| 部署默认值与草稿 | `workspaces/` 保存默认值；更新分支保存已提交草稿，配置正文均在 GitLab |
| 实例期望配置 | `instances/`：固定模板引用、非敏感参数、Kustomize overlay、Secret 引用及变更历史 |
| 容器镜像 | 镜像仓库；Git 只保存镜像地址、软件版本和 digest |
| 运行状态与权限 | 平台数据库：实例所有者、配置修订、部署任务、执行事件和实际验证结果 |
| 密码与集群凭据 | 已确定的凭据存储；Git 只保存引用，不保存明文或仅作 base64 编码的 Secret 数据 |

manifest 是 Kubernetes 资源声明文件，如 StatefulSet、Service、PVC、ConfigMap 和 TCPRoute。Kustomize 用 base 保存通用声明，用 overlay 表达具体实例差异；软件参数到 overlay 的转换由平台的确定性实现负责。平台自定义的参数 schema 和元数据不是 Kustomize 自动读取的配置，也不把任意字符串替换当成渲染过程。

## 建议目录

以下是待创建仓库的目录约定，不代表目录或软件包已经存在：

```text
olixops-manifests/
├── README.md
├── catalog/
│   └── redis/
│       └── standalone/
│           └── v1/                       # 模板版本，不是 Redis 软件版本
│               ├── package.yaml          # 平台元数据：标识、来源、兼容范围、镜像与版本
│               ├── parameters.schema.json # 平台输入字段及约束
│               ├── README.md             # 配置说明、更新/删除规则、验证证据
│               ├── base/
│               │   ├── kustomization.yaml
│               │   ├── statefulset.yaml
│               │   ├── service.yaml
│               │   ├── pvc.yaml
│               │   └── configmap.yaml
│               ├── components/
│               │   └── tcp-access/       # 选用外部访问时的 TCPRoute 及关联配置
│               └── examples/
│                   └── poc/              # 示例 overlay，不是已部署实例
├── workspaces/
│   └── <workspace_id>/defaults.yaml      # 非敏感部署默认值
├── instances/
│   └── <workspace_id>/<config_id>/       # 稳定配置身份，后续关联实例
│       ├── config.yaml                  # 模板、非敏感参数与环境选择意图
│       └── overlay/                     # 真实环境解析后才生成
│           ├── kustomization.yaml        # 引用同一快照中的通用部署包
│           └── patches/                  # CPU/内存、存储、名称、入口和 Secret 引用等
└── tests/                                # 参数、渲染、资源归属与版本一致性校验
```

先收录单实例 Redis；PostgreSQL 等软件后续按相同目录规范扩展，不创建空目录冒充可用软件。`pvc.yaml` 表示本计划采用独立 PVC 的初版设计；阶段 2 需验证 StatefulSet 引用和默认保留策略，不能同时生成第二套 volumeClaimTemplates 卷。

每个实例的 overlay 引用同一检出目录中的固定模板路径。base 定义内部访问所需资源，外部访问配置才引入实例所属的 TCPRoute；共享 Gateway/Listener 由平台单独管理，不能纳入 Redis 实例删除清单。StorageClass、Gateway 和 Secret 的实际值由授权环境提供，示例不能用作已核实的环境事实。

## 版本、写入与执行

1. 区分软件版本、模板版本、Git commit 和镜像 digest。模板版本如 `redis/standalone/v1` 描述部署约定；Redis 版本描述软件；Git commit 固定文件快照；digest 固定镜像内容。阶段 0 规定这些字段，阶段 2 填入并验证实际版本和摘要。
2. 软件包由维护者审查与测试后发布。已经发布的模板目录不原地改变；修复或升级发布新模板版本，已有实例须通过新配置修订显式切换。平台的软件列表只暴露经过收录且满足所需验证条件的版本。
3. 后端读取受控软件包及参数 schema，校验用户输入，生成实例 overlay。实例参数通过确定的 patch、images、replacements 等配置表达，具体机制随模板测试固定；Agent 只选择软件、模板和参数，不能提交任意 manifest、脚本或远端资源地址。
4. 模板维护和实例配置写入走不同的变更校验。平台发布代码校验实例路径、归属、允许字段和变更范围；模板目录额外经过仓库审查及 CI。Git token 通常不能仅凭目录提供权限隔离，若需要强制分开写入权限，再拆分模板仓库和实例仓库。
5. 实例配置成功发布到远端后，数据库将该配置修订绑定到仓库标识、完整 Git commit、实例路径、模板路径/版本、镜像 digest、渲染工具版本和结果摘要。最终 commit 不写入它自身的文件，绑定关系由平台数据库及构建产物保存。
6. Worker 检出任务绑定的 commit，使用该提交内的本地 base/overlay 重新渲染并核对摘要，然后执行。重试不切换到分支最新 HEAD。第一版禁止未固定的远端 base、远端资源、外部生成器和执行插件，以免构建期间产生未记录输入。
7. Git 记录期望配置，数据库记录目标修订和最近验证成功修订，集群查询反映实际资源；三个状态不能互相替代。Git 推送成功不表示部署成功，删除 Git 目录不自动删除集群资源，配置回退不等于数据恢复。

## 多人使用与独立安装的存储建议

2026-09-13 用户提出后续给他人使用时的配置存放问题。以下为设计建议；集中托管还是各团队独立安装尚未明确，工作空间、配置偏好、凭据管理和仓库绑定均未实现，不作为当前阶段已完成的能力。

| 配置类型 | 建议存放与归属 |
| --- | --- |
| 通用软件模板 | 可共享的 catalog，由模板维护者发布固定版本 |
| 部署默认值和未发布草稿 | 按 2026-09-14 最新要求保存在 GitLab；默认值放 workspaces，草稿放更新分支，之后修改默认值不改变既有修订 |
| 实例期望配置 | 私有 Git 中的实例 overlay；建议按稳定的工作空间、项目、环境和实例 ID 组织 |
| 成员权限、实例归属、发布记录和实际状态 | 平台数据库；实例属于工作空间，创建人单独记录 |
| Redis 密码、Git token、模型 key 和集群凭据 | 受控凭据存储；业务配置保存带归属的引用，读取与使用引用都要校验权限 |

多人共用一套托管平台时，可以先使用一个仅供平台服务和受信任维护者访问的私有仓库。当前配置存取设计使用 `instances/<workspace_id>/<config_id>/`；项目、环境和后续实例关联作为明确字段，不要求保存草稿时已有真实 Namespace。个人可以拥有个人工作空间，团队成员管理后续扩展。客户端提交的工作空间、配置/实例 ID、集群和 Namespace 都须经过服务端授权，Git 路径由服务端生成。权限检查覆盖配置、修订、差异、日志、导出、凭据引用以及后台执行，不能仅在前端列表过滤。

目录和分支不提供用户间的仓库保密边界。例如 GitHub 的 Read 角色即可拉取所分配仓库，见 [仓库角色说明](https://docs.github.com/en/organizations/managing-user-access-to-your-organizations-repositories/managing-repository-roles/repository-roles-for-an-organization)。普通用户通过平台访问本人有权使用的配置；若客户需要直接读取 Git，建议为对应组织建立独立私有配置仓库和访问身份。

其他团队独立安装平台时，每套安装使用自己的数据库、私有实例仓库及凭据存储；通用模板可以共享或同步，真实实例配置留在各自环境。模板仓库与实例仓库分离后，建议将审核通过的模板按固定版本和来源 commit 同步为实例仓库内的不可变快照，再生成本地引用的 overlay，从而继续遵守同一 checkout 可重现渲染的执行规则；同步流程和校验仍待实现。

集群侧的多人隔离还需要授权的 Namespace 映射、RBAC、网络策略和配额；仅划分目录或 Namespace 不足以完成隔离，见 [Kubernetes 多租户说明](https://kubernetes.io/docs/concepts/security/multi-tenancy/)。如果使用 Kubernetes Secret 保存运行凭据，还需配置静态加密和最小权限；Secret 默认并不保证存储加密，见 [Secret 官方说明](https://kubernetes.io/docs/concepts/configuration/secret/)。

## 按用户分配 Namespace 与外部端口的建议

2026-09-13 用户进一步提出：按用户生成 Namespace，各用户部署到自己的 Namespace；外部端口默认分配，也接受自定义并由后端检查。该方向可沿用当前 Gateway/TCPRoute 路线，以下约定尚未实现或连接真实集群验证。

### Namespace 归属

初版可给每个用户建立个人工作空间，并按工作空间与集群持久保存 Namespace 映射；例如 `olixops-ws-<stable_id>`，不要直接使用可修改的用户名。首次部署时由平台的环境初始化职责幂等创建 Namespace，完成策略检查后才允许发布；已有同名 Namespace 必须核对真实归属，不能直接接管。后端从已认证身份解析目标，用户不能通过提交任意 Namespace 切换到别人的环境。

每个 Namespace 配套最小权限 RBAC、ResourceQuota/LimitRange、默认拒绝跨空间通信的 NetworkPolicy，并显式放行 DNS、网关到实例及需要的业务流量；网络策略效果取决于实际 CNI 支持。平台控制 Namespace 标签和策略，集群范围的初始化权限与实例部署权限分开。每个用户的多个实例可共用该 Namespace；未来按项目/环境进一步划分时使用显式映射。删除一个实例不删除其 Namespace，PVC 保留按实例策略处理。

### 内部端口与外部端口

不同用户的 Redis Service 可以都使用内部端口 `6379`。选择外部访问时，通过共享 Gateway 的 TCP Listener 和实例 Namespace 内的 TCPRoute 转发，例如 `入口地址:20001 → ws-a/redis:6379`、`入口地址:20002 → ws-b/redis:6379`。此处端口仅作示例；真实端口池需核实 Gateway 控制器、Listener 数量限制、负载均衡器及防火墙等入口条件。只创建 TCPRoute 不保证入口已经监听或对客户端可达。

默认不填写外部端口，由后端从管理员配置的可用端口池分配；自定义端口必须是有效整数且处于允许范围，排除保留和已占用端口，并校验用户的入口使用权限。自定义冲突返回明确错误，可给出可选端口；不能静默改成其他端口。仅内部访问的实例不占用外部端口。

分配的唯一性范围是实际共享入口的 `(入口冲突域, 协议, 端口)`，不按用户或 Namespace 分开计算；多个 Gateway 共享相同对外入口时，也要映射到同一个冲突域。普通 Redis TCP 不能仅凭不同域名区分同一入口端口上的实例。平台数据库分配记录须与已存在的网关 Listener 和实际入口配置核对，外部手工变更产生的冲突要阻止继续发布。

### 预留、执行与释放

1. 后端校验身份、Namespace 和端口策略，再通过数据库唯一约束与短事务原子预留端口。自动分配发生冲突时尝试其他候选，自定义端口冲突时直接返回错误；不能仅先查询空闲再执行。预留绑定实例、修订意图和幂等请求，重试复用原端口。
2. 将确定的 Namespace、端口和 Listener 引用固化到实例 Git 修订；数据库保存预留状态及归属。实例 overlay 只包含本实例资源和引用，不管理整座共享 Gateway。
3. 平台集中协调共享 Listener 的启用和变更，避免并发覆盖其他实例的配置；实例 TCPRoute 通过 `parentRefs.namespace` 和 `sectionName` 指向被分配的 Listener。Listener 的 `allowedRoutes` 应限定受控的所属 Namespace 和 TCPRoute 类型，相关 Namespace 标签仅平台可改。Route 与后端 Service 保持同 Namespace；此类 Route 到 Gateway 的跨 Namespace 挂接使用 allowedRoutes，不用 ReferenceGrant 代替。若以后跨 Namespace 引用后端 Service，再按相应引用规则单独授权。
4. Worker 使用确定的修订应用资源，分别检查 Listener 生效、TCPRoute 接纳及引用解析、Redis 健康和真实外部访问，最后标记发布成功。用户只能操作平台分配给自己的路由和端口；如将来开放直接写 Kubernetes Route，还需要额外的准入约束，避免绕过平台分配。
5. Git 发布失败、部署失败或执行回执丢失时，保留可追踪的预留及待核对状态；不能只因超时自动回收可能已生效的端口。确认未曾应用，或确认旧路由与入口关联已解除后才释放。修改端口产生新修订，先预留新端口，旧端口在切换与解除确认后释放；失败时保留实际状态供核对。

实施对应现有阶段：阶段 1 核实 Namespace 初始化身份、隔离策略和真实入口端口池；阶段 2 验证不同 Namespace 的 Redis 与跨 Namespace Gateway 挂接；阶段 3 建立归属映射和持久预留；阶段 4 实现共享 Listener 协调、发布及恢复；阶段 5–6 复用自动/自定义端口参数。新增验收覆盖跨用户拒绝、并发抢同一端口、重复请求、网关冲突、失败不误释放和删除后安全复用。当前仍从阶段 0 推进。

依据：[Kubernetes 多租户](https://kubernetes.io/docs/concepts/security/multi-tenancy/)、[Gateway TCP 路由](https://gateway-api.sigs.k8s.io/guides/user-guides/tcp/)、[跨 Namespace 挂接](https://gateway-api.sigs.k8s.io/guides/user-guides/multiple-ns/)。API 版本及支持程度以目标集群实际安装为准；上述端口分配和恢复规则是平台的设计约定。

## 调整后的起点

阶段 0A 确定 GitLab 仓库位置及目录规范，建立 Redis 软件包骨架、参数契约、非敏感示例和检查入口；阶段 0B 的配置存取与 MR 流程按最新设计草案审阅后实施。此时模板为草案，不标记为可部署版本。缺少远端地址时可在明确标注的本地草案中完成独立工作，远端创建/发布验收保持待办。

阶段 1 核实真实集群、存储、镜像可达性和 TCP 入口；阶段 2 完成模板并进行真实 Redis 验证；阶段 3 复用配置存取能力，建立实际实例、环境解析、端口预留及可部署修订的关联。配置保存和读取可以独立验收，稳定配置不代表清单已可用于真实部署。

Kustomize 的 base/overlay 机制参考 [Kubernetes 官方文档](https://kubernetes.io/docs/tasks/manage-kubernetes-objects/kustomization/)。仓库目录、包元数据及版本发布规则是本平台的设计约定。
