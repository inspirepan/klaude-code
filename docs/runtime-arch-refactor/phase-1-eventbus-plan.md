# Phase 1 实施计划：输出通道抽象（EventBus）

目标：在**不改变现有 TUI 可运行性**的前提下，把事件输出从 `event_queue` 直写改为 `EventBus` 发布订阅。

---

## 1. 范围与非目标

### 1.1 本阶段范围

- 新增 `EventBus`（发布/订阅/退订）
- Executor 侧改为向 `EventBus` 发布事件
- 保留 TUI 现有 `event_queue` 消费方式，通过 bridge 转发
- 引入背压策略：有界队列 + 溢出断开慢订阅者（按 ADR）

### 1.2 非目标

- 不改 `Operation` 协议（仍使用 `protocol/op.py`）
- 不引入 `RuntimeHub/SessionRuntime`
- 不改 interaction 侧通道（`UserInteractionManager` 暂保留）
- 不做事件模型大迁移（仍使用 `protocol/events.py`）

---

## 2. 拟修改文件

1. `src/klaude_code/core/event_bus.py`（新增）
   - `publish(event: events.Event) -> None`
   - `subscribe(session_id: str | None) -> AsyncIterator[events.Event]`
   - `unsubscribe(...) -> None`
   - 每订阅者独立 bounded queue（默认 1024）
   - overflow 触发断开

2. `src/klaude_code/core/executor.py`
   - `ExecutorContext.emit_event()` 从 `event_queue.put()` 改为 `event_bus.publish()`
   - `SubAgentManager` 的输出也统一走 `emit_event`（避免绕过 EventBus）

3. `src/klaude_code/app/runtime.py`
   - 初始化 `event_bus`
   - 保留 `event_queue`
   - 新增 bridge task：`event_bus.subscribe(None) -> event_queue.put(...)`
   - 清理时先停 executor，再停 bridge，再投递 `EndEvent` 给 display

4. `tests/`（新增）
   - `test_event_bus_backpressure_disconnect.py`
   - `test_event_bus_session_filter.py`
   - `test_runtime_event_bridge_smoke.py`

---

## 3. 运行语义（Phase 1）

### 3.1 发布路径

`ExecutorContext.emit_event -> EventBus.publish -> (N subscribers)`

### 3.2 TUI 路径（兼容）

`EventBus.subscribe(None) -> bridge -> legacy event_queue -> display.consume_event_loop`

### 3.3 背压

- 任一订阅者队列满：断开该订阅者
- 不阻塞 publish 主链路

---

## 4. 验收标准

1. CLI/TUI 主流程可运行（与当前交互行为等价）
2. 同时挂两个订阅者时，均可收到事件
3. 慢订阅者溢出后被断开，runtime 不阻塞
4. 现有测试不出现系统性回归

---

## 5. 本阶段临时实现（必须记录）

详见：`migration-gap-register.md`。

本阶段至少存在以下临时项：

- 仍存在 `event_queue`（仅作为 TUI adapter）
- 仍是单 `Executor + submission_queue`
- 仍有 `UserInteractionManager` 侧通道
- 仍是旧事件模型（非 `EventEnvelope`）

---

## 6. 风险与缓解

### 风险 A：bridge 任务异常导致 TUI 无事件

- 缓解：bridge task done callback 统一上报错误并触发退出路径

### 风险 B：订阅者断开后缺失流式细节

- 缓解：明确这是预期；主状态依赖 durable 历史恢复

### 风险 C：SubAgentManager 与 EventBus 双通路并存

- 缓解：Phase 1 内就把 SubAgentManager 输出并到 `emit_event`，禁止直写 `event_queue`
