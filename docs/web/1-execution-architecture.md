# Web Server 模式 -- 执行架构设计

本文记录当前执行架构的分析结论，以及 Web Server 模式如何复用现有核心层的设计方案。

只覆盖**执行架构与通信模型**，不讨论前后端 API 细节和前端组件设计。

---

## 1. 当前执行架构分析

### 1.1 总体分层

```
用户输入 (prompt_toolkit)
    |
    v
runner.py (TUI 交互循环)
    |
    v  submit(Operation)
RuntimeFacade ──────────────> SessionRegistry
    |                              |
    |                         SessionActor (per session)
    |                              |
    v  publish(Event)         OperationDispatcher
EventBus <────────────────         |
    |                         AgentRunner -> TaskExecutor -> TurnExecutor
    |                              |
    v  subscribe()                 v
DisplayABC (TUIDisplay)       LLMClient / ToolExecutor
InteractionHandlerABC
```

### 1.2 关键设计特征

**操作-事件分离**

上行用 `Operation`（用户意图），下行用 `Event`（系统反馈）。两者通过 `EventBus` 完全解耦。

**端口-适配器模式**

UI 层通过三个抽象端口接入核心：

| 端口 | 接口 | TUI 实现 |
|------|------|----------|
| 输出 | `DisplayABC` | `TUIDisplay` (Rich 渲染) |
| 交互 | `InteractionHandlerABC` | `_TUIInteractionHandler` (prompt_toolkit) |
| 输入 | 无正式抽象 | `PromptToolkitInput` |

**EventBus 多播**

`subscribe(session_id)` 按 session 过滤，`subscribe(None)` 接收全部。多个订阅者可同时消费同一 EventBus，互不干扰。慢订阅者超出队列上限 (1024) 会被自动断开。

**SessionRegistry 原生多 session**

`_session_actors: dict[str, SessionActor]` 已是多 session 字典。每个 SessionActor 独立维护操作队列、活跃任务和交互状态。

**全异步单线程**

核心逻辑在单个 `asyncio` 事件循环中运行，无锁竞争。阻塞 IO 通过 `asyncio.to_thread` 外派。

### 1.3 核心组件职责

| 组件 | 路径 | 职责 |
|------|------|------|
| `RuntimeFacade` | `core/control/runtime_facade.py` | 外部入口，封装操作提交和会话生命周期 |
| `SessionRegistry` | `core/control/session_registry.py` | 管理 `session_id -> SessionActor` 映射 |
| `SessionActor` | `core/control/session_actor.py` | 会话内状态边界：操作队列、活跃任务、交互请求 |
| `EventBus` | `core/control/event_bus.py` | 事件发布/订阅中枢 |
| `OperationDispatcher` | `core/agent/runtime.py` | 路由 Operation 到对应处理器 |
| `TaskExecutor` | `core/agent/task.py` | 多轮对话循环（重试、压缩、工具调用） |
| `TurnExecutor` | `core/agent/turn.py` | 单次 LLM 调用 + 流式消费 + 工具执行 |
| `Session` | `session/session.py` | 持久化状态：对话历史、检查点、模型配置 |

### 1.4 应用初始化流程

`app/runtime.py` 中的 `initialize_app_components()` 负责组装完整链路：

```python
# 简化后的初始化流程
config = load_config()
llm_clients = build_llm_clients(config)
event_bus = EventBus()
subscription = event_bus.subscribe(None)            # 全局订阅

runtime = RuntimeFacade(event_bus, llm_clients)

display_task = create_task(consume_display(subscription, display))   # 消费事件 -> 渲染
interaction_task = create_task(consume_interactions(subscription, runtime, handler))  # 处理交互请求
idle_reclaim_task = create_task(reclaim_idle_sessions_loop(runtime))  # 回收空闲 session
```

关键：`EventBus` 和 `RuntimeFacade` 的创建不依赖任何 UI 组件，可以直接复用。

### 1.5 EventEnvelope 结构

所有事件通过 `EventEnvelope` 传递，已经是 Pydantic 模型，天然支持 JSON 序列化：

```python
class EventEnvelope(BaseModel):
    event_id: str
    event_seq: int          # session 内单调递增序号
    session_id: str
    operation_id: str | None
    task_id: str | None
    causation_id: str | None
    event_type: str
    durability: str         # "durable" | "ephemeral"
    timestamp: float
    event: Event            # 具体事件（discriminated union）
```

---

## 2. Web Server 模式设计

### 2.1 核心结论：复用而非重建

当前架构的关注点分离已经足够好。Web server 模式不重写核心执行层，只新增一个 Web 适配层（替代 TUI 的 runner + display + interaction handler），与 `RuntimeFacade` 和 `EventBus` 在同一个 asyncio 事件循环中运行。

### 2.2 通信模型：WebSocket + REST

通信分为两层：

| 层 | 协议 | 用途 |
|------|------|------|
| 实时通道 | WebSocket | 双向：上行发送用户操作，下行接收事件流 |
| 无状态查询 | REST (HTTP) | session 列表、创建、历史加载、文件服务、配置 |

**WebSocket 连接与 session 视图绑定**：打开已有 session 或新 session 发送首条消息时建立 WS 连接，所有实时交互（发消息、中断、交互回复、切模型等）和事件接收都通过同一条 WS 完成。

**选择 WebSocket 的原因：**

1. **交互闭环在单一连接内** -- 发消息、收事件、交互回复都走 WS，不需要协调多个通道。
2. **连接生命周期与 session 视图自然对齐** -- 打开 session 建立连接，离开时断开（或后台保持）。
3. **EventEnvelope 是 Pydantic 模型** -- `model_dump_json()` 直接作为 WS text frame 发送。
4. **上行消息类型简单** -- 用 `{"type": "message" | "interrupt" | "respond" | ...}` discriminated union 即可。
5. **FastAPI 原生支持 WebSocket** -- 与 ASGI 和 asyncio 事件循环无缝集成。

**REST 端点保留用于无状态操作**：session 列表查询、创建新 session、加载历史、文件服务等不需要实时连接的操作仍走 HTTP。

### 2.3 分层架构

```
Browser (N 个 tab)
  |
  |  WebSocket (双向)             fetch (HTTP)
  |  上行操作 + 下行事件流          无状态查询/创建
  v                              v
┌──────────────────────────────────────────────┐
│  Layer 1: Transport                          │
│  ASGI Server (uvicorn) + FastAPI             │
│                                              │
│  WS   /api/sessions/{id}/ws    -> 双向实时通道   │
│  GET  /api/sessions            -> session 列表   │
│  POST /api/sessions            -> 创建 session   │
│  GET  /api/sessions/{id}/history -> 加载历史      │
│  GET  /api/config/models       -> 模型列表       │
│  GET  /api/files               -> 文件服务       │
└──────────────────┬───────────────────────────┘
                   |
┌──────────────────┴───────────────────────────┐
│  Layer 2: Web Adapter                        │
│  WebSessionManager                           │
│    - 管理 WS 连接与 EventBus 订阅的映射         │
│    - 将 WS 上行消息转换为 Operation 提交         │
│  WebInteractionHandler (InteractionHandlerABC)│
│    - 将交互请求推送到 WS，等待 WS 上行响应       │
└──────────────────┬───────────────────────────┘
                   |
┌──────────────────┴───────────────────────────┐
│  Layer 3: Core (完全复用，零改动)               │
│  RuntimeFacade / EventBus / SessionRegistry  │
│  Agent / TaskExecutor / TurnExecutor         │
│  LLM Clients / Tool Executor / Session       │
└──────────────────────────────────────────────┘
```

### 2.4 进程模型（默认前后端同启）

`klaude web` 默认是 **fullstack launcher**：同时准备后端 API 与前端可访问入口，再自动打开浏览器。

#### 模式 A：源码开发环境（双进程）

```
┌────────────────────── klaude web launcher ──────────────────────┐
│                                                                  │
│  Process-1: Python (uvicorn + RuntimeFacade)                    │
│    ├─ /api/* (REST + WebSocket)                                  │
│    └─ EventBus + SessionRegistry + SessionActor                 │
│                                                                  │
│  Process-2: Frontend dev server (Vite)                           │
│    ├─ /                                                          │
│    └─ proxy /api + /api/sessions/*/ws -> Python backend          │
│                                                                  │
│  Browser auto-open -> http://127.0.0.1:<frontend_port>          │
└──────────────────────────────────────────────────────────────────┘
```

#### 模式 B：PyPI / 无 Node 环境（单进程）

```
┌─ asyncio event loop (单进程) ────────────────────────────────────┐
│                                                                  │
│  uvicorn (ASGI)                RuntimeFacade                     │
│    ├─ /api/* (REST + WebSocket)   ├─ SessionRegistry             │
│    └─ StaticFiles(web/dist)      ├─ SessionActor[s1..n]         │
│                                  └─ EventBus                    │
│                                                                  │
│  Browser auto-open -> http://127.0.0.1:<backend_port>/          │
└──────────────────────────────────────────────────────────────────┘
```

两种模式的用户体验保持一致：执行 `klaude web` 后直接进入 Web UI。

### 2.5 WebSocket 消息协议

#### 端点

`WS /api/sessions/{session_id}/ws`

#### 上行消息（client -> server）

所有上行消息为 JSON text frame，通过 `type` 字段区分：

```jsonc
// 发送用户消息
{ "type": "message", "text": "help me refactor...", "images": [] }

// 中断当前执行
{ "type": "interrupt" }

// 回复交互请求（AskUserQuestion / OperationSelect）
{ "type": "respond", "request_id": "req_xxx", "status": "submitted", "payload": {...} }

// 从中断处继续
{ "type": "continue" }

// 切换模型
{ "type": "model", "model_name": "claude-sonnet-4-20250514", "save_as_default": false }

// 切换 thinking level
{ "type": "thinking", "thinking": { "type": "enabled", "budget_tokens": 8192 } }
```

#### 下行消息（server -> client）

下行消息为 `EventEnvelope` 的 JSON 序列化，直接通过 WS text frame 发送：

```jsonc
{
  "event_type": "assistant.text.delta",
  "event_seq": 42,
  "session_id": "abc123",
  "event": { "content": "Hello" },
  ...
}
```

**连接握手序列**：WS 建立后，后端在开始转发 EventBus 事件之前，执行以下握手：

1. **自动 resume**：如果 session 未在 RuntimeFacade 中激活（无 SessionActor），自动提交 `InitAgentOperation` 恢复 session。如果 session 已激活（例如从另一个 tab 或断线前仍在运行），跳过此步骤。
2. **推送 `usage.snapshot`**：发送当前 session 的累加 usage 快照（来自 `MetadataAccumulator.get_partial()`）。前端以此为基准开始累加后续的 `UsageEvent` 增量。
3. **开始转发事件**：`event_bus.subscribe(session_id)` 并进入双向消息循环。

断线重连时新 WS 会重新走握手序列（跳过已激活的 resume + 发送新快照），自然恢复状态。

#### WS 错误帧

后端通过 WS 下行发送结构化错误消息，与 EventEnvelope 共存于同一通道：

```jsonc
{
  "type": "error",
  "code": "invalid_message",    // 错误码
  "message": "Unknown message type: foo",  // 人类可读描述
  "detail": null                // 可选的额外信息
}
```

错误码定义：

| code | 触发条件 | 后续行为 |
|---|---|---|
| `invalid_message` | 上行 JSON 格式错误或缺少 `type` 字段 | 忽略该消息，WS 保持连接 |
| `unknown_type` | 上行 `type` 值不在支持列表中 | 忽略该消息，WS 保持连接 |
| `session_not_found` | `session_id` 不存在或无法加载 | 发送错误后关闭 WS（close code 4004） |
| `session_init_failed` | 自动 resume 失败（磁盘损坏等） | 发送错误后关闭 WS（close code 4005） |
| `invalid_payload` | 上行消息 `type` 正确但 payload 验证失败 | 忽略该消息，WS 保持连接 |

非致命错误（`invalid_message`、`unknown_type`、`invalid_payload`）不断开连接，前端可显示 toast 提示。致命错误（`session_not_found`、`session_init_failed`）会主动关闭 WS，前端根据 close code 展示对应的错误 UI。

#### 后端实现

```python
@app.websocket("/api/sessions/{session_id}/ws")
async def session_ws(websocket: WebSocket, session_id: str):
    await websocket.accept()

    # 1. auto-resume if session not active
    if not runtime.is_session_active(session_id):
        try:
            await runtime.submit_and_wait(InitAgentOperation(session_id=session_id))
        except SessionNotFoundError:
            await websocket.send_json({"type": "error", "code": "session_not_found", ...})
            await websocket.close(code=4004)
            return
        except Exception:
            await websocket.send_json({"type": "error", "code": "session_init_failed", ...})
            await websocket.close(code=4005)
            return

    # 2. send usage snapshot
    snapshot = runtime.get_usage_snapshot(session_id)
    if snapshot:
        await websocket.send_text(snapshot.model_dump_json())

    # 3. start bidirectional loop
    subscription = event_bus.subscribe(session_id)

    async def send_events():
        async for envelope in subscription:
            await websocket.send_text(envelope.model_dump_json())

    async def recv_commands():
        async for raw in websocket.iter_text():
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "code": "invalid_message", ...})
                continue
            msg_type = data.get("type")
            match msg_type:
                case "message":
                    runtime.submit(RunAgentOperation(...))
                case "interrupt":
                    runtime.submit(InterruptOperation(...))
                case "respond":
                    interaction_handler.resolve(...)
                case None:
                    await websocket.send_json({"type": "error", "code": "invalid_message", ...})
                case _:
                    await websocket.send_json({"type": "error", "code": "unknown_type", ...})

    await gather(send_events(), recv_commands())
```

前端消费：

```typescript
const ws = new WebSocket(`ws://.../api/sessions/${sessionId}/ws`);
ws.onmessage = (e) => {
  const envelope = JSON.parse(e.data);
  dispatch(envelope);  // 按 event_type 分发到 store
};

// 发送消息
ws.send(JSON.stringify({ type: "message", text: "..." }));
```

### 2.6 多标签页与断线重连

**多标签页**：每个浏览器标签页各自建立独立的 WS 连接，各自 `subscribe(session_id)`。EventBus 已支持多订阅者，任一 tab 都可以发送消息或中断。

**断线重连**：EventBus 当前不持久化事件，`subscribe` 只能收到订阅之后的事件。断线重连策略：

1. WS 断开后，前端先 `GET /api/sessions/{id}/history` 重建完整会话状态。
2. 再建立新的 WS 连接接收后续实时事件。

不在服务端维护 per-session 事件 ring buffer，避免额外复杂度。会话历史已通过 `Session.conversation_history` 持久化在磁盘。

**切换 session 时的连接策略**：用户切换到另一个 session 时，旧 WS 连接后台保持约 60s，期间收到的事件仍更新本地状态。超时后断开。切回时若连接仍活着则直接复用，否则走断线重连流程。

### 2.7 用户交互 (Interaction) 流程

Agent 运行中需要用户决策时（如工具审批、参数选择），整个交互闭环都在 WS 内完成：

```
Agent 执行中需要用户输入
    |
    v
RuntimeFacade 发布 UserInteractionRequestEvent
    |
    v (通过 EventBus -> WS 下行)
前端收到交互请求，渲染 UI（选择框/输入框）
    |
    v (用户操作)
前端通过 WS 上行发送 { "type": "respond", "request_id": "...", ... }
    |
    v
Web Adapter 转换为 UserInteractionRespondOperation
    |
    v
RuntimeFacade 将响应传递回 Agent，继续执行
```

`WebInteractionHandler` 实现 `InteractionHandlerABC`，内部用 `asyncio.Future` 桥接：

```python
class WebInteractionHandler(InteractionHandlerABC):
    _pending: dict[str, asyncio.Future[UserInteractionResponse]]

    async def collect_response(self, request_event) -> UserInteractionResponse:
        future = asyncio.get_running_loop().create_future()
        self._pending[request_event.request_id] = future
        # 事件已通过 EventBus -> WS 推送到前端
        # 等待前端通过 WS 上行提交响应
        return await future

    def resolve(self, request_id: str, response: UserInteractionResponse) -> None:
        future = self._pending.pop(request_id)
        future.set_result(response)
```

### 2.8 初始化路径

当前 `initialize_app_components()` 组装了 EventBus + RuntimeFacade + TUI Display。Web 模式需要类似但不同的初始化：

```python
# Web 模式初始化（伪代码）
config = load_config()
llm_clients = build_llm_clients(config)
event_bus = EventBus()

runtime = RuntimeFacade(event_bus, llm_clients)

interaction_handler = WebInteractionHandler()
interaction_subscription = event_bus.subscribe(None)
interaction_task = create_task(
    consume_interactions(interaction_subscription, runtime, interaction_handler)
)

idle_reclaim_task = create_task(reclaim_idle_sessions_loop(runtime))

# WS 订阅在每个 WebSocket 连接中按需创建，不在初始化时统一创建
# Display 不需要 -- Web 模式下服务端不渲染，事件直接通过 WS 推送到前端
```

建议：从 `app/runtime.py` 中抽取 EventBus + RuntimeFacade + InteractionHandler 的初始化为共享函数，TUI 和 Web 各自补充自己的 I/O 层。

### 2.9 启动编排与浏览器打开

`klaude web` 的默认流程：

1. 初始化核心运行时（`EventBus` + `RuntimeFacade` + Web 交互桥接）。
2. 启动后端 API（uvicorn）。
3. 选择前端策略：
   - 检测到开发前端可用时，拉起前端 dev server；
   - 否则使用后端静态托管 `web/dist`。
4. 自动打开浏览器到前端 URL（可通过 `--no-open` 关闭）。
5. 监听退出信号并做统一清理（包含前端子进程与 asyncio 任务）。

说明：源码与 PyPI 的实现路径可不同，但 CLI 默认行为必须相同。

---

## 3. 需要新增的模块

```
src/klaude_code/web/
    __init__.py
    app.py              # FastAPI app 定义、路由注册
    session_manager.py  # WebSessionManager：WS/HTTP -> Operation 转换
    interaction.py      # WebInteractionHandler：InteractionHandlerABC 实现
    startup.py          # Web 模式初始化（复用 app/runtime.py 核心部分）
    frontend_launcher.py # 前端进程探测/启动（dev server 或静态托管策略）
```

CLI 入口新增 `klaude web` 子命令，默认启动前后端并自动打开浏览器。

---

## 4. 核心层改动评估

| 模块 | 是否需要改动 | 说明 |
|------|------------|------|
| `RuntimeFacade` | 否 | `submit()` / `wait_for()` 接口通用 |
| `EventBus` | 否 | `subscribe(session_id)` 已支持多订阅者 |
| `SessionRegistry` | 否 | 原生多 session |
| `Agent / Task / Turn` | 否 | 与 I/O 层完全解耦 |
| `LLM Clients` | 否 | 无 UI 依赖 |
| `Tool Executor` | 否 | 无 UI 依赖 |
| `Session` (持久化) | 否 | `create()` / `load()` / `list_sessions()` 已有 |
| `app/runtime.py` | 小幅重构 | 抽取 EventBus + RuntimeFacade 初始化为共享函数 |
| `protocol/events.py` | 否 | Pydantic 模型，天然支持 JSON 序列化 |

---

## 5. 技术栈

| 组件 | 选择 | 原因 |
|------|------|------|
| ASGI 框架 | FastAPI | 项目已用 Pydantic；WebSocket 原生支持 |
| ASGI Server | uvicorn | 标准选择，可嵌入 asyncio loop |
| 实时通道 | FastAPI WebSocket | 双向通信，与 asyncio 事件循环无缝集成 |
| 序列化 | Pydantic `model_dump_json()` | EventEnvelope 已是 Pydantic 模型 |
| 前端静态文件 | Starlette `StaticFiles` | 开发时 vite dev server，发布时嵌入包 |
| 前端运行策略 | Vite dev server + StaticFiles fallback | 同一 CLI 行为覆盖源码与 PyPI 场景 |

---

## 6. 架构不变量

1. 所有入站请求都通过 `Operation` 进入核心层。
2. 所有出站事件都通过 `EventEnvelope` 经由 `EventBus` 传出。
3. Web 适配层不直接操作 `Session`、`Agent` 或 `TaskExecutor`。
4. WS 连接是可重建的 -- 断线重连通过 history API + 新建 WS 实现。
5. 核心层对 Web/TUI 的存在无感知。
