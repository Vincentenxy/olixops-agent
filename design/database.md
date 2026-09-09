# 数据库设计

当前版本 `20260909_0001` 仅包含本地用户、认证会话和登录限流三张表；对应 [模型](../app/models/auth.py) 与 [初始迁移](../migrations/versions/20260909_0001_local_auth.py)。后续表结构变更同时更新本文、模型和 Alembic 迁移，不在应用启动时自动建表。

## 存储与连接

PostgreSQL 是身份、会话撤销和限流状态的持久来源。后端使用 SQLAlchemy 异步会话与 `psycopg`，连接由 `OLIXOPS_DATABASE_URL` 注入；密码不进入仓库或日志。连接池开启 `pool_pre_ping`，SQL 参数隐藏，迁移进程使用 `NullPool`。依赖检查验证三张认证表可查询，因此未执行迁移也会报告数据库未就绪。

本地 Compose 使用 `postgres:15-alpine`，库名/用户名均为 `olixops`，默认仅绑定 `127.0.0.1:15432`；密码由 `scripts/init_local.py` 生成并保存在被 Git 忽略的 `.env`。容器之间连接 `postgres:5432`。Redis 使用 `redis:7-alpine`，默认仅绑定 `127.0.0.1:16379`，容器之间连接 `redis:6379`；当前用于缓存基础设施及连通性检查，不承担认证会话或登录限流的唯一存储。

SQLite/`aiosqlite` 仅供测试。它不提供等同 PostgreSQL 的行锁语义；并发验证需要实际 PostgreSQL，不能由 SQLite 测试替代。

## 公共字段

三张表均包含以下字段；时间使用 PostgreSQL `TIMESTAMP WITH TIME ZONE`，应用统一写 UTC。UUID 标识在当前模型中实际使用 `VARCHAR(36)`，不是数据库原生 UUID 类型。

| 字段 | 类型 | 规则 |
|---|---|---|
| `create_at` | `TIMESTAMP WITH TIME ZONE NOT NULL` | 应用写入创建时间 |
| `update_at` | `TIMESTAMP WITH TIME ZONE NOT NULL` | 应用写入更新时间，SQLAlchemy 更新时同步 |
| `create_by` | `VARCHAR(64) NOT NULL` | 操作者 ID 或约定的系统主体 |
| `update_by` | `VARCHAR(64) NOT NULL` | 最近一次操作者 ID 或系统主体 |

命令行创建用户使用 `bootstrap`；未认证的限流记录使用 `system`；创建/刷新/撤销会话及修改密码使用对应用户 ID。审计主体没有外键，因为需要表示系统操作并保留记录语义。

这些默认值由 SQLAlchemy 提供，初始迁移没有数据库端 `DEFAULT` 或更新时间触发器。绕过应用直接写 SQL 时必须显式提供非空字段，不能假设数据库自动填充。

## local_users：本地身份

`username` 经应用规范化为小写后查询/创建，数据库唯一约束本身仍按普通字符串比较。`password_hash` 保存 Argon2 哈希；`is_active=false` 时登录及已有会话认证均拒绝，`is_admin` 表示当前基础管理权限。密码明文和签名私钥不存入此表。

```sql
CREATE TABLE local_users (
    user_id VARCHAR(36) NOT NULL PRIMARY KEY,
    username VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    password_hash VARCHAR(512) NOT NULL,
    is_admin BOOLEAN NOT NULL,
    is_active BOOLEAN NOT NULL,
    create_at TIMESTAMP WITH TIME ZONE NOT NULL,
    update_at TIMESTAMP WITH TIME ZONE NOT NULL,
    create_by VARCHAR(64) NOT NULL,
    update_by VARCHAR(64) NOT NULL
);
```

主键和 `username` 唯一约束由 PostgreSQL 自动建立索引；当前没有额外普通索引。应用创建用户时默认启用，管理员标记由显式的 `--admin` 参数决定；重复创建同名用户不会修改已有密码或角色。

## auth_sessions：可撤销会话

每次成功登录创建新的 `session_id`。`refresh_hash` 是随机 refresh token 的 SHA-256 十六进制摘要且唯一；数据库不保存明文 refresh token 或 access JWT。JWT 包含会话 ID，认证时还会检查关联用户及数据库会话，因而登出和改密可以立即撤销尚未过期的 access JWT。

```sql
CREATE TABLE auth_sessions (
    session_id VARCHAR(36) NOT NULL PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL
        REFERENCES local_users (user_id) ON DELETE CASCADE,
    refresh_hash VARCHAR(64) NOT NULL UNIQUE,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    revoked_at TIMESTAMP WITH TIME ZONE,
    create_at TIMESTAMP WITH TIME ZONE NOT NULL,
    update_at TIMESTAMP WITH TIME ZONE NOT NULL,
    create_by VARCHAR(64) NOT NULL,
    update_by VARCHAR(64) NOT NULL
);

CREATE INDEX ix_auth_sessions_user_id ON auth_sessions (user_id);
CREATE INDEX ix_auth_sessions_expires_at ON auth_sessions (expires_at);
```

除主键和 refresh 摘要唯一索引外，用户索引用于批量撤销，过期时间索引用于按时间查找记录。删除用户会级联删除会话。会话有效条件为 `revoked_at IS NULL AND expires_at > 当前 UTC 时间`；有效期默认从登录开始计算 604800 秒（7 天），刷新不会延长这个绝对期限。

刷新在同一事务内锁定用户，并以旧摘要进行 compare-and-swap：

```sql
UPDATE auth_sessions
SET refresh_hash = :new_hash,
    update_by = :user_id,
    update_at = :now
WHERE session_id = :session_id
  AND refresh_hash = :old_hash
  AND revoked_at IS NULL
  AND expires_at > :now
RETURNING session_id;
```

仅更新到记录的请求成功；并发使用同一旧 token 时最多一个请求成功，旧摘要随轮换失效。轮换失败返回认证失败，不回退到旧 token，也不创建新会话。当前没有保存 token 家族历史或实现完整的 refresh 重放调查机制。

## login_throttles：持久登录退避

每次登录同时读取两个维度：`SHA256("user:" + 小写用户名)` 与 `SHA256("ip:" + 客户端 IP)`。摘要只用于稳定键及减少原值直接存储，不应视作对用户名/IP 的不可逆匿名化。

```sql
CREATE TABLE login_throttles (
    throttle_key VARCHAR(64) NOT NULL PRIMARY KEY,
    failed_count INTEGER NOT NULL,
    locked_until TIMESTAMP WITH TIME ZONE,
    create_at TIMESTAMP WITH TIME ZONE NOT NULL,
    update_at TIMESTAMP WITH TIME ZONE NOT NULL,
    create_by VARCHAR(64) NOT NULL,
    update_by VARCHAR(64) NOT NULL
);
```

当前仅主键索引，没有账号外键：未知账号同样需要限流。应用先使用 `INSERT ... ON CONFLICT DO NOTHING` 确保记录存在，再按排序后的键顺序 `SELECT ... FOR UPDATE`，保证并发计数与一致的锁顺序。

任一维度仍在锁定期则拒绝登录；锁定期间不继续累计失败次数或延长锁定。验证失败/账号不存在/账号禁用都会在事务中累计两个维度的次数。默认第 5 次失败起锁定 30 秒，此后每次解锁后的失败按以下规则退避：

```text
lock_seconds = min(600, configured_seconds * 2^min(5, failed_count - failure_limit))
```

成功登录把本次用户名和 IP 两个维度的计数及锁定清零，并在同一事务中创建会话；同 IP 下另一用户成功登录也会清零该 IP 维度计数。锁定过期本身不会把累计次数清零。目前没有过期会话/限流记录定期清理任务，保留策略需后续补充。

## 事务与撤销

事务边界在 `AuthService`，Repository 只执行参数化查询。登录失败先提交计数/锁定，再对外返回 401，避免异常回滚导致限流失效。密码校验与哈希在工作线程执行；数据库锁仍保留到当前事务结束。

登录、刷新、登出和改密通过用户行锁协调。登出撤销目标会话，优先使用请求认证身份绑定的会话，避免其他标签页替换共享 Cookie 后误撤销另一会话。修改密码在用户锁内再次验证当前会话及旧密码，更新哈希并撤销该用户全部未撤销会话，作为一个事务提交。JWT 签名校验通过仍须查询用户状态和会话有效性。

## 迁移操作

在仓库根目录执行，连接从 `.env` / 环境变量中的 `OLIXOPS_DATABASE_URL` 加载：

```bash
uv run python scripts/init_local.py
docker compose up -d postgres redis
uv run alembic upgrade head
uv run alembic current
uv run alembic check
```

离线审查生成的 PostgreSQL DDL，不连接数据库：

```bash
uv run alembic upgrade head --sql
```

初始迁移的回退命令如下，会删除三张认证表及全部用户、会话和限流数据；仅在确认可丢弃的验证库或已有可恢复备份的变更流程中使用：

```bash
uv run alembic downgrade base
```

后续新增迁移使用 `uv run alembic revision --autogenerate -m "describe change"`，人工审查类型、数据兼容及 `downgrade` 后再提交。`alembic_version` 由 Alembic 自管，不套用业务表审计字段。本文 SQL 已与 `20260909_0001` 的离线迁移输出核对。
