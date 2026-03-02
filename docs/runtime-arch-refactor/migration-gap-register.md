# Runtime 重构迁移差距台账（临时项登记）

用途：记录“当前可运行实现”与“最终目标架构”之间的差距，防止临时方案长期固化。

状态定义：

- `open`：临时项仍存在
- `closed`：已按目标架构清理完成

---

## 差距台账

| ID | 当前临时实现 | 目标形态 | 引入阶段 | 计划清理阶段 | 状态 |
|---|---|---|---|---|---|
| G-001 | 保留 `event_queue` 作为 display 主通道 | TUI/Web 都直接订阅 EventBus（或统一 adapter） | Phase 1 | Phase 4 | open |
| G-002 | ingress 仍经过 `Executor.submit` 包装层（已不经过 submission queue） | `RuntimeHub -> SessionRuntime.mailbox` 成为唯一输入调度入口（或 `Executor` 仅作薄门面） | 现状 | Phase 2/4 | open |
| G-003 | `UserInteractionManager` 独立侧通道 | interaction 进入 `SessionRuntime.pending_requests` 闭环 | 现状 | Phase 3 | open |
| G-004 | `Operation.id` 兼做任务跟踪 key（submission 语义混用） | `operation_id` / `task_id` 语义拆分 | 现状 | Phase 3 | open |
| G-005 | `TaskManager` 按 submission 维度管理任务 | 会话内 `active_root_task + child_tasks` | 现状 | Phase 2/4 | open |
| G-006 | `events.Event` 直出，无统一 envelope | `EventEnvelope(event_id, event_seq, ...)` | 现状 | Phase 3 | open |
| G-007 | `AgentRuntime._agent` 单活跃实例 | 每 session 独立 runtime 与 agent state | 现状 | Phase 2 | open |
| G-008 | durable/ephemeral 边界未代码级白名单化 | durable 白名单常量 + 强制落库策略 | 现状 | Phase 3 | open |
| G-009 | SessionRuntime worker 共享全局 execution lock（兼容 legacy 单 `_agent`） | 去除全局锁，按 session 独立并发执行 | Phase 2 | Phase 2/3 | open |
| G-010 | SessionRuntime 已有 root-task gate + `RootTaskState(task_id, kind)`，但仍未形成完整运行态对象 | SessionRuntime 内聚 `active_root_task/pending_requests/config` 完整运行态 | Phase 2 | Phase 2/3 | open |
| G-011 | busy reject 当前双轨：`OperationRejectedEvent`（结构化）+ `CommandOutputEvent`（兼容显示） | 统一到标准运行时事件（后续 `operation.rejected` / EventEnvelope）并移除兼容双轨 | Phase 2 | Phase 3 | open |
| G-012 | control 优先目前是队列调度级（8:1），未形成“执行中任务”级别抢占 | 达到完整 interrupt 抢占语义（含执行中上下文的及时让渡/取消） | Phase 2 | Phase 3 | open |

---

## 更新规则

1. 每个阶段结束必须更新本文件：
   - 新增临时项
   - 调整“计划清理阶段”
   - 将已完成项改为 `closed`
2. PR 描述必须引用本台账受影响条目（如 `G-001, G-006`）。
3. 若临时项跨阶段延期，必须写明原因与新截止阶段。
