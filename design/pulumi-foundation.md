# Pulumi 基础集成

> 当前状态（2026-09-10）：Pulumi 业务接入暂停，本文记录的代码、依赖和基础自测保留原样。Redis 部署按 [开发计划](redis-development-plan.md) 实施，以下 Provider/Stack/backend 接入事项不作为当前阶段前提。

本轮实现运行时诊断、受控程序适配与独立 Worker 自测。生产部署任务、Provider 组件、远程状态和凭据由后续业务设计接入；本模块没有面向 HTTP 的 `up` / `destroy` 接口。

## 模块边界

- `app/integrations/pulumi/diagnostics.py`：有界执行 `pulumi version`，核对 CLI 与 SDK 均为 `3.261.0`，返回固定的状态及提示。该检查不验证目标 backend、Provider 或云权限；异步路由通过线程调用。
- `app/integrations/pulumi/adapter.py`：`TrustedProgram` 仅接受仓库中经过评审的 Python 回调；`IsolatedProgramSession` 管理一个独占临时 backend/stack 的 Automation API 生命周期，各操作串行执行。它供受控组件验证复用，不能作为持久业务 stack 的替代。
- `app/workers/pulumi.py`：独立进程入口，只注册固定的 `self-test` 程序。Python SDK 与 CLI/gRPC 在子进程中协作，API 请求不会执行 Pulumi 程序。
- `app/integrations/pulumi/models.py`：平台结果模型只保留操作类型、数量、严重级别和校验状态。SDK 返回值不是对外契约。

## 本机运行

需要先安装锁定的 Python 依赖和官方 Pulumi CLI 3.261.0。CLI 所在目录应同时包含官方发行包附带的运行时程序。

```bash
uv sync --locked
uv run python -m app.workers.pulumi self-test --timeout 120
```

CLI 未在 PATH 时：

```bash
uv run python -m app.workers.pulumi self-test --cli /path/to/pulumi --timeout 120
```

命令最终输出一个脱敏 JSON，成功退出码为 `0`，失败/超时为 `1`，捕获到中断时为 `130`。`--timeout` 限制范围为大于 0、最多 600 秒；到期先终止子进程组，再强制结束残留子进程。Windows 使用 `taskkill /T /F`，该分支需在 Windows CI 中补充验证。

自测执行固定常量程序的 `preview → up → outputs 核对 → refresh → preview(expect_no_changes=True) → destroy → remove_stack`。程序仅声明 Pulumi 根 stack 并导出常量及 secret 测试值，不加载目标 Provider、不创建云资源。`destroy` 仅是该临时验证 stack 正常成功路径的显式清理；失败不自动重试 `up`、解锁或执行 `destroy`，也不宣称回滚完成。

每次运行创建独立工作目录、`PULUMI_HOME`、文件 backend 和随机测试 passphrase；命令结束后删除临时产物。子进程不继承云凭据、Pulumi token、应用配置或带凭据代理环境变量。为 CLI 系统用户查询保留原有 HOME/USER，Pulumi 配置仍由独立的 `PULUMI_HOME` 管理；不调用全局 `login`。隔离工作目录与超时不构成任意代码沙箱。

## 输出与日志

Automation API 的 `up`、`refresh` 和 `destroy` 均显式使用 `show_secrets=False`。`preview` 和 `outputs()` 在当前 SDK 没有该参数；其中 `outputs()` 可能在内存中解密，因此仅内部比较已注册的非 secret 常量，绝不序列化原始输出。

适配层只返回受控程序声明的输出名称和 secret 标记，所有值（含未标记 secret 的值）都替换为 `[REDACTED]`。引擎事件不保留原始 stdout、diagnostic 文本、URN、资源属性、配置或 Provider 信息；未知操作/严重级别被舍弃。事件数量最多 4096，超出时标记 `events_truncated`；`sequence` 在该次自测内递增。引擎 `cancelEvent` 在正常结束时也出现，映射为 `stream_end`，不作为任务取消证据。

Worker 屏蔽底层 stdout/stderr，异常映射为固定提示；结果中的 `cleanup=temporary_files_removed` 仅说明临时文件清理，`stack_removed=true` 才表示成功执行了引擎删除 stack。超时或失败不会返回资源已回滚的结论。

## 验证与后续接入

常规测试覆盖缺少 CLI、版本不匹配、诊断超时、输出/事件敏感值过滤、受限环境、异常脱敏，以及 POSIX 下父进程和后代进程的超时终止。真实引擎测试显式开启：

```bash
OLIXOPS_RUN_PULUMI_TEST=1 OLIXOPS_PULUMI_CLI=pulumi uv run pytest tests/test_pulumi.py
```

2026-09-09 已在 macOS / CPython 3.14.7 / CLI 与 SDK 3.261.0 完成上述真实常量程序闭环。容器组合的结果记录在根目录 `todo.md`；本验证不代表真实云环境部署成功。

持久业务 Worker 接入时，需要另行定义稳定 stack 身份、远程 backend、secrets provider、Provider/组件版本、配置/审核绑定、持久任务与事件、按 stack 的跨进程串行调度、取消/恢复策略及执行网络/文件权限；不得把临时自测目录用于生产资源状态。

当前 SDK 参数和边界依据：[Pulumi Python Automation API](https://www.pulumi.com/docs/reference/pkg/python/pulumi/#module-pulumi.automation)、[Automation API 使用说明](https://www.pulumi.com/docs/iac/guides/building-extending/automation-api/)。
