# Redis standalone v1

本地 fixture 用于模拟 GitLab 公共模板读取。模板只部署一个 Redis Deployment 和一个 ClusterIP Service，默认镜像 `redis:7.2-alpine`，不包含密码和持久化卷，适合先验证配置保存、YAML 渲染和 Kubernetes dry-run。
