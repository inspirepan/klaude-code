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
- TUI 在状态机内将该事件映射为错误命令输出（不再由 Executor 双发事件）

并且本次追加了第七个增量：

- 移除 `Submission` 包装对象，RuntimeHub/SessionRuntime/Executor 统一直接处理 `Operation`
- completion 映射改为 `operation_id -> runtime_id`

并且本次追加了第八个增量：

- `UserInteractionManager` 从全局单 pending 改为多 pending 管理（按 `request_id`）
- 仍保持侧通道形态，作为并轨前的中间态

并且本次追加了第九个增量：

- `UserInteractionManager` 增加 request state 回调（pending/resolved）
- `RuntimeHub/SessionRuntime` 记录会话维度 pending request 集合（仅状态跟踪）

并且本次追加了第十个增量：

- `SessionRuntime` 增加 `is_idle()`（active root + pending requests + mailbox）
- `RuntimeHub.idle_runtime_ids()` 可用于后续 session TTL 回收策略

并且本次追加了第十一个增量：

- `SessionRuntime` 增加基础 session-local config 状态（model/thinking/compact/sub-agent model）
- `Executor` 在 operation 成功执行后同步更新该 config 状态

并且本次追加了第十二个增量：

- interaction 请求等待路径从 `UserInteractionManager.wait_next_request()` 切换到 `RuntimeHub.wait_next_request()`
- `RuntimeHub/SessionRuntime` 维护 pending request 对象，并按 pending 状态过滤过期请求

并且本次追加了第十三个增量：

- `SessionRuntime` 提供 `snapshot()`（active root / pending count / idle / config）
- `RuntimeHub` 提供 `snapshot(session_id)` 与 `all_snapshots()`，便于后续 WebUI/TTL 管理读取运行态

并且本次追加了第十四个增量：

- `RuntimeHub` 增加 `close_session()` 与 `reclaim_idle_runtimes()`
- 基于 `SessionRuntime.is_idle()` 支撑后续 TTL 自动回收落地

并且本次追加了第十五个增量：

- 新增 `CloseSessionOperation`（显式 close 协议），由 global runtime 执行并回收目标 session runtime
- `SessionRuntime` 增加 idle 时长跟踪（`idle_for_seconds()`）
- `RuntimeHub.reclaim_idle_runtimes(idle_for_seconds=...)` 支持 TTL 门槛
- `app/runtime.py` 增加后台 idle reclaim loop（默认 TTL=30m，巡检间隔=60s）

并且本次追加了第十六个增量：

- user interaction 的响应 future 从 `UserInteractionManager` 迁移到 `RuntimeHub` 托管
- `AgentRuntime` 通过 `ExecutorContext -> RuntimeHub` 发起 interaction request，并统一由 `RuntimeHub` 维护 pending/resolve/cancel
- `UserInteractionRespondOperation` 与 interrupt 取消路径改为直接操作 `RuntimeHub` pending 状态（去除运行时侧通道）

并且本次追加了第十七个增量：

- 拆分 `operation_id` 与 `task_id` 语义：`TaskManager` 改为 `operation_id -> task_id -> asyncio.Task` 双映射
- root-task 启动时先以 `operation_id` 占位，执行层注册真实 `task_id` 后通过 `RuntimeHub.bind_root_task()` 回填
- busy reject 的 `active_task_id` 优先使用真实 `task_id`（若尚未回填则退回占位 ID）

并且本次追加了第五个增量：

- `Executor.submit()` 直接路由到 `RuntimeHub.submit()`（移除内部 submission queue 转发链路）
- `app/runtime.py` 不再启动独立 executor background task
- `Executor.start()` 已移除，`Executor` 仅保留提交/等待/停止门面职责

---

## 2. 本阶段仍保留的临时实现

> 这些临时项都已在 `migration-gap-register.md` 登记。

- ingress 仍经过 `Executor.submit` 包装层
- SessionRuntime worker 共享全局 execution lock（为兼容当前单 `_agent` 运行态）
- SessionRuntime 已承载 root-task gate + `RootTaskState`
- SessionRuntime 已支持 control/normal 双队列与 8:1 配额
- SessionRuntime 已内聚 pending request 状态与 idle 判定基础能力
- SessionRuntime 已内聚基础 session-local config（仍缺与持久化/重放一致性的完整闭环）
- interaction 响应 future 仍由 `UserInteractionManager` 托管（并轨未完成）

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
