# Runtime 重构关键决策记录（ADR）

本文记录 runtime-arch-refactor 当前已拍板的关键策略，作为后续实现与测试的统一依据。

---

## 1. 决策摘要

| 主题 | 决策 |
|---|---|
| EventBus 背压 | 有界队列 + 溢出断开慢订阅者 |
| control/normal 公平性 | Interrupt 抢占 + control:normal = 8:1 配额 |
| Busy 语义 | 同 session 有 active root-task 时，拒绝新的 `prompt/run_bash/compact` |
| Session 生命周期 | 显式 close + 空闲 TTL 自动回收 |
| durable vs ephemeral | durable 白名单；非白名单默认 ephemeral |

---

## 2. 详细决策

### 2.1 EventBus 背压策略

**决策**

- 每个订阅者独立有界队列（bounded per-subscriber queue）。
- 当订阅者队列满时，断开该订阅者（unsubscribe/disconnect）。

**原因**

- runtime 主链路不被慢订阅者反向阻塞。
- 内存上限可控，避免无界增长。

**代价/后果**

- 慢客户端会丢失该连接期间的 ephemeral 事件（如流式 chunk）。
- 客户端需要重连，并通过 durable 数据恢复主状态。

---

### 2.2 control/normal 队列公平性

**决策**

- `interrupt` 保持抢占优先。
- worker loop 采用配额调度：`control:normal = 8:1`。
  - 即连续处理最多 8 个 control 后，若 normal 非空，强制处理 1 个 normal。

**原因**

- 保证中断低延迟。
- 避免 normal queue 在高压下长期饥饿。

**代价/后果**

- 相比“永远 control 优先”，实现稍复杂（需要计数器）。

---

### 2.3 Busy / Reject 协议

**决策**

- 每个 session 同时最多一个 active root-task。
- 当 root-task 运行中，拒绝新的 root 类操作：
  - `prompt`
  - `run_bash`
  - `compact`
- control 类操作（如 `interrupt`, `respond_request`）仍可进入。

**原因**

- 语义确定，避免排队造成陈旧执行。
- 保持交互系统可预测。

**建议事件**

- 统一发 `operation.rejected`，至少携带：
  - `reason = "session_busy"`
  - `operation_id`
  - `session_id`
  - `active_task_id`

---

### 2.4 Session 生命周期回收

**决策**

- 支持显式 close。
- 同时启用空闲 TTL 自动回收。

**建议空闲判定**

仅当以下条件全部满足，才允许 TTL 回收：

- 无 active root-task
- 无 pending requests
- 无必须保留的活动订阅（按实现策略可选）

**原因**

- 显式 close 提供强可控释放。
- TTL 防止忘记关闭导致会话堆积。

---

### 2.5 durable vs ephemeral 边界

**决策**

- 采用 durable 白名单策略。
- 白名单外事件默认 ephemeral。

**durable（建议范围）**

- 最终对话消息（用户/助手）
- `tool.result`
- rewind / compaction 关键记录
- 重放必需元数据

**ephemeral（示例）**

- `stream.chunk`
- 调度中间态（如 accepted/排队提示）
- UI 辅助类提示

**原因**

- 保证 replay 一致性，同时控制存储体积与噪声。

---

## 3. 默认参数（建议初始值）

以下为实现建议默认值，可在代码中集中配置：

- `subscriber_queue_maxsize = 1024`
- `control_burst_quota = 8`
- `session_idle_ttl = 30m`

---

## 4. 测试与验收要点

### 4.1 背压

- 构造慢订阅者，验证其被断开且不影响 runtime publish 延迟。

### 4.2 公平性

- 在 control 持续输入下，验证 normal 操作仍能按配额被处理。

### 4.3 Busy

- root-task 运行中提交 `prompt/run_bash/compact`，验证收到 `operation.rejected(session_busy)`。

### 4.4 回收

- 显式 close 立即释放。
- 空闲超过 TTL 后自动回收。

### 4.5 持久化边界

- 回放仅依赖 durable 数据仍可恢复关键会话状态。
- ephemeral 事件不会污染 durable history。

---

## 5. 变更约束

后续若需调整以上策略（例如从 8:1 改为 4:1，或 TTL 变更），应更新本文并在 PR 中标注“Runtime ADR 变更”。