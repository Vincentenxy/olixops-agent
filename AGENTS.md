# 开发入口

- 继续业务开发、设计部署接口或评审相关变更前，必须先读 [Redis 一句话部署开发计划](design/redis-development-plan.md)。这是用户确认的当前计划，完整阶段与验收条件以该文档为准。
- 按软件清单 Git 仓库 → 集群接入 → Redis 模板验证 → 实例与 Git 修订 → 部署 Worker → 前端发布 → 自然语言接入的顺序，从 [todo.md](todo.md) 中最早未验收阶段推进。仓库结构先读 [软件清单仓库设计](design/software-manifest-repository.md)。已授权范围内，验收通过后继续下一阶段；缺环境时记录阻塞并推进独立工作，保留真实验收待办。
- 当前路线为 Git + Kustomize + 独立部署 Worker。Pulumi 暂不参与业务部署，已引入的代码、依赖与诊断保持原样；历史 Pulumi 规划不作为本轮接入前提。
- 配置存取功能先读最新推荐讨论 [GitLab 稳定模板 + PostgreSQL 用户配置](design/gitlab-templates-postgresql-configs.md)，再核对用户最新决定；此前全 Git 和个人分支方案仅为评审对照。阶段 0B 仍为设计审阅/待实现，实施前统一读写源和发布修订约定，不把草案当成已完成接口或真实部署能力。
- 修改后端代码、接口、数据库、日志或运行配置前，阅读 [README.md](README.md) 中对应规范；它是后端约定的唯一来源。
- 规划功能或处理未接入组件时，阅读 [todo.md](todo.md)，完成后同步实际状态和验证结果。
