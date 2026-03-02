# Klaude WebUI Runtime 重构落地分阶段（草案）

## 1. 总体策略

不建议一次性重写。建议分 4 个阶段推进，每阶段可运行、可验证。

原因：

- 一次性改完会把「架构变化」和「行为回归」耦合，问题定位成本高。
- 你当前已经有可用 TUI 运行链路，分阶段可以持续复用现有能力。

---

## 2. 阶段总览

1. **Phase 1：输出通道抽象（EventBus）**
2. **Phase 2：输入通道会话化（SessionRuntime + RuntimeHub）**
3. **Phase 3：协议并轨（Operation 协议重整，Interaction 侧通道移除）**
4. **Phase 4：清理旧骨架（去 submission loop 心智模型）**

---

## 3. Phase 1：输出通道抽象（EventBus）

### 3.1 当前职责

- `src/klaude_code/core/executor.py`
  - `ExecutorContext.emit_event()` 直接写 `event_queue`
- `src/klaude_code/app/runtime.py`
  - 创建 `event_queue`
  - `display.consume_event_loop(event_queue)`

### 3.2 目标职责

新增统一输出总线：

- `src/klaude_code/core/event_bus.py`
  - `publish(event)`
  - `subscribe(session_id: str | None)`

保留 TUI 适配层：

- 订阅 EventBus，再转发到原 `event_queue`（过渡期不改 display）

### 3.3 伪代码

```python
# app/runtime.py
event_bus = EventBus()
event_queue = asyncio.Queue()
display_bridge_task = asyncio.create_task(pipe_event_bus_to_queue(event_bus.subscribe(None), event_queue))

# core/executor.py
class ExecutorContext:
    async def emit_event(self, event: Event) -> None:
        await self.event_bus.publish(event)
```

### 3.4 验证点

- TUI 行为与现状一致。
- 多个订阅者可同时消费事件（例如日志订阅 + TUI）。

---

## 4. Phase 2：输入通道会话化（SessionRuntime + RuntimeHub）

### 4.1 当前职责

- `Executor.submission_queue` 统一接收所有 operation。
- `AgentRuntime._agent` 只维护单个 active agent。
- `TaskManager` 以 `submission_id` 跟踪任务。

### 4.2 目标职责

新增会话级运行时容器：

- `src/klaude_code/core/runtime_hub.py`
  - 管理 `session_id -> SessionRuntime`
  - 统一接收 Operation 并路由到对应 session mailbox

- `src/klaude_code/core/session_runtime.py`
  - `mailbox: Queue[Operation]`
  - `agent`
  - `active_task`
  - `pending_requests`
  - `session_local_config`

### 4.3 伪代码

```python
class RuntimeHub:
    def __init__(self, event_bus):
        self._runtimes: dict[str, SessionRuntime] = {}
        self._event_bus = event_bus

    async def submit(self, op: Operation) -> None:
        rt = self._runtimes.get(op.session_id)
        if rt is None:
            rt = await SessionRuntime.create(op.session_id, self._event_bus)
            self._runtimes[op.session_id] = rt
            asyncio.create_task(rt.run_loop())
        await rt.enqueue(op)


class SessionRuntime:
    def __init__(...):
        self.mailbox: asyncio.Queue[Operation] = asyncio.Queue()
        self.root_agent_runtime: AgentRuntime
        self.child_agent_runtimes: dict[str, AgentRuntime] = {}
        self.active_root_task: asyncio.Task[None] | None = None
        self.pending_requests: dict[str, asyncio.Future[Any]] = {}
        self.config: SessionRuntimeConfig

    async def run_loop(self) -> None:
        while True:
            op = await self.mailbox.get()
            await self.handle_operation(op)
```

### 4.4 验证点

- 两个 session 同时运行互不影响。
- 同 session 保持单 root-task 约束（子 agent 可并发）。

---

## 5. Phase 3：协议并轨（Operation 协议重整，Interaction 侧通道移除）

### 5.1 当前职责

- `src/klaude_code/protocol/op.py`：Operation 协议
- `src/klaude_code/core/user_interaction/manager.py`：interaction 侧通道
- `src/klaude_code/tui/runner.py`：专门等待 interaction request 再回填 response

### 5.2 目标职责

统一协议分两类：

- `src/klaude_code/protocol/operation.py`（入站）
  - `PromptOperation`
  - `SteerOperation`
  - `InterruptOperation`
  - `RespondRequestOperation`
  - `ChangeModelOperation`
  - ...

- `src/klaude_code/protocol/runtime_event.py`（出站）
  - `InteractionRequestedEvent`
  - `InteractionResolvedEvent`
  - `TaskStartedEvent`
  - `AssistantDeltaEvent`
  - `TaskFinishedEvent`
  - ...

### 5.3 伪代码

```python
class SessionRuntime:
    async def request_interaction(self, payload: InteractionPayload) -> InteractionResponse:
        req_id = new_id()
        fut = asyncio.get_running_loop().create_future()
        self.pending_requests[req_id] = fut
        await self.publish(InteractionRequestedEvent(session_id=self.id, request_id=req_id, payload=payload))
        try:
            return await fut
        finally:
            self.pending_requests.pop(req_id, None)

    async def handle_operation(self, op: Operation) -> None:
        match op:
            case RespondRequestOperation(session_id=sid, request_id=req_id, response=resp):
                fut = self.pending_requests.get(req_id)
                if fut is not None and not fut.done():
                    fut.set_result(resp)
                    await self.publish(InteractionResolvedEvent(session_id=sid, request_id=req_id))
```

### 5.4 验证点

- 不再依赖独立的 interaction manager 轮询循环。
- interaction 全部通过 Operation/Event 闭环完成。

---

## 6. Phase 4：清理旧骨架

### 6.1 待退役职责

- `Executor.submit/submission_queue/wait_for/_completion_events`
- `OperationHandler` 协议
- `TaskManager`（submission 维度）
- `UserInteractionManager` 侧通道

### 6.2 新职责稳态

- `RuntimeHub`：全局 Operation 入口
- `SessionRuntime`：会话执行边界
- `EventBus`：统一输出发布订阅
- `Operation/Event`：统一协议

### 6.3 伪代码

```python
# TUI/Web/RPC 统一入口
await runtime_hub.submit(PromptOperation(session_id=sid, input=user_input))

# 统一输出订阅
async for event in event_bus.subscribe(session_id=sid):
    render(event)
```

### 6.4 验证点

- 代码中不存在 operation + interaction 双体系并行。
- 核心运行路径仅剩 Operation -> SessionRuntime -> EventBus。

---

## 7. 当前类与替代职责映射（简表）

| 当前类/模块 | 现职责 | 新职责归属 |
|---|---|---|
| `Executor` (`core/executor.py`) | 全局 submission 队列 + 执行调度 | `RuntimeHub` + `SessionRuntime` |
| `AgentRuntime` | 单 `_agent` 生命周期 | `SessionRuntime.root_agent_runtime + child_agent_runtimes` |
| `TaskManager` | submission 任务跟踪 | `SessionRuntime.active_root_task`（会话内） |
| `UserInteractionManager` | interaction pending/request queue | `SessionRuntime.pending_requests` |
| `event_queue` | 事件输出主通道 | `EventBus`（`event_queue`仅作 TUI adapter） |
| `op.py` + `OperationHandler` | 输入协议 | `operation.py` |
| `events.py`（现有） | 输出协议（可逐步迁移） | `runtime_event.py`（或在原文件内重构） |

---

## 8. 一次性重写 vs 分阶段

### 不建议一次性重写

- 回归风险大，问题定位困难。
- 难以确认是哪层（协议/并发/渲染）导致异常。

### 建议分阶段

- 每阶段都可运行。
- 每阶段都可测试并回滚。
- 最终达到同一目标架构。
