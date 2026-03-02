# Phase 2 实施计划：输入通道会话化（RuntimeHub + SessionRuntime）

目标：把输入调度从“单 submission loop”逐步迁移到“按 session mailbox 路由”，同时保持每次改动后可运行。

---

## 1. 当前增量（已完成）

本次已落地最小骨架：

- 新增 `RuntimeHub`：`src/klaude_code/core/runtime_hub.py`
- 新增 `SessionRuntime`：`src/klaude_code/core/session_runtime.py`
- `Executor.start()` 中，非 EndOperation 的 submission 改为交由 `RuntimeHub.submit(...)`
- `RuntimeHub` 为每个 session 建立独立 mailbox + worker

这一步完成后，系统仍可运行，且输入路由路径已经具备“按 session 分桶”的结构。

并且本次追加了第二个增量：

- `SessionRuntime` 增加 root-task gate（`run_agent/run_bash/continue/compact`）
- 当 session busy 时，root 操作直接 reject，不进入执行
- `interrupt` 等控制操作不受 busy gate 影响，仍可进入
- `SessionRuntime` 本地维护 active root submission id（通过 completion 回调清理）

并且本次追加了第三个增量：

- `SessionRuntime` 拆分 control/normal 双 mailbox
- control 操作：`interrupt`、`user_interaction_respond`
- 调度策略：control 优先 + `8:1` 配额（连续 8 个 control 后，若有 normal 则强制执行 1 个 normal）

并且本次追加了第四个增量：

- `SessionRuntime` 将 active root 从裸 submission id 升级为显式 `RootTaskState(task_id, kind)`
- completion 回调按 `task_id` 回收 active root 状态

并且本次追加了第六个增量：

- busy reject 事件增加结构化输出：`OperationRejectedEvent`
- 同时保留 `CommandOutputEvent(operation.rejected)` 以兼容当前 TUI 渲染

并且本次追加了第五个增量：

- `Executor.submit()` 直接路由到 `RuntimeHub.submit()`（移除内部 submission queue 转发链路）
- `app/runtime.py` 不再启动独立 executor background task
- `Executor.start()` 已移除，`Executor` 仅保留提交/等待/停止门面职责

---

## 2. 本阶段仍保留的临时实现

> 这些临时项都已在 `migration-gap-register.md` 登记。

- ingress 仍经过 `Executor.submit` 包装层（但已不再经过内部 submission queue）
- SessionRuntime worker 共享全局 execution lock（为兼容当前单 `_agent` 运行态）
- SessionRuntime 已承载 root-task gate + `RootTaskState`
- SessionRuntime 已支持 control/normal 双队列与 8:1 配额
- SessionRuntime 仍未内聚 pending/config 等会话运行态

---

## 3. 后续子步骤（Phase 2 内）

1. 将会话级运行态逐步迁入 SessionRuntime（先 `active_root_task`）
2. 将 active root 从 submission id 过渡为显式 `active_root_task` 实体
3. 逐步降低对全局 execution lock 的依赖
4. 将 control 优先从“队列级”推进到“执行级”可抢占语义（必要时）

---

## 4. 验收要点（当前增量）

- 不破坏现有 CLI/TUI 主流程
- 同一 session 的操作在其 mailbox 内保持顺序
- global interrupt 仍可处理（映射到 global runtime）
- busy session 下 root 操作会被拒绝，且不会触发执行
- control/normal 调度符合优先级与 8:1 公平性

对应测试：`tests/test_runtime_hub.py`
