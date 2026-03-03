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

### 2.2 通信模型：SSE + HTTP POST

当前通信模式本质上不对称：

| 方向 | 特征 | 频率 |
|------|------|------|
| 下行 (server -> client) | 持续事件流：text delta、tool call、thinking 等 | 极高 |
| 上行 (client -> server) | 离散动作：发消息、中断、切模型 | 极低 |

选择 **SSE（Server-Sent Events）** 处理下行，**HTTP POST** 处理上行。

**SSE 优于 WebSocket 的原因：**

1. **EventBus 的 `event_seq` 与 SSE 的 `id` 天然对齐** -- 浏览器断线重连时自动携带 `Last-Event-ID`，可从该序号之后恢复事件流。
2. **EventEnvelope 是 Pydantic 模型** -- FastAPI SSE 原生支持 yield Pydantic 对象，自动 JSON 序列化。
3. **不需要管理双向连接状态** -- 无需心跳/ping-pong 逻辑，FastAPI 内置 15s keep-alive。
4. **更易调试** -- 浏览器 DevTools EventStream 面板可直接查看。
5. **上行天然是 REST** -- 创建 session、发消息、中断，本质上都是离散的 HTTP 请求。

### 2.3 分层架构

```
Browser (N 个)
  |
  |  EventSource (SSE)          fetch (HTTP POST)
  |  下行事件流                   上行离散动作
  v                              v
┌──────────────────────────────────────────────┐
│  Layer 1: Transport                          │
│  ASGI Server (uvicorn) + FastAPI             │
│                                              │
│  GET  /api/sessions/{id}/events  -> SSE 事件流    │
│  POST /api/sessions              -> 创建 session │
│  POST /api/sessions/{id}/message -> 发消息        │
│  POST /api/sessions/{id}/interrupt -> 中断        │
│  POST /api/sessions/{id}/respond -> 用户交互响应   │
│  GET  /api/sessions/{id}/history -> 加载历史       │
│  GET  /api/sessions              -> session 列表   │
└──────────────────┬───────────────────────────┘
                   |
┌──────────────────┴───────────────────────────┐
│  Layer 2: Web Adapter                        │
│  WebSessionManager                           │
│    - 管理 SSE 连接与 EventBus 订阅的映射       │
│    - 将 HTTP 请求转换为 Operation 提交          │
│  WebInteractionHandler (InteractionHandlerABC)│
│    - 将交互请求推送到 SSE，等待 HTTP 响应        │
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
│    ├─ /api/*                                                     │
│    ├─ SSE                                                        │
│    └─ EventBus + SessionRegistry + SessionActor                 │
│                                                                  │
│  Process-2: Frontend dev server (Vite)                           │
│    ├─ /                                                          │
│    └─ proxy /api -> Python backend                               │
│                                                                  │
│  Browser auto-open -> http://127.0.0.1:<frontend_port>          │
└──────────────────────────────────────────────────────────────────┘
```

#### 模式 B：PyPI / 无 Node 环境（单进程）

```
┌─ asyncio event loop (单进程) ────────────────────────────────────┐
│                                                                  │
│  uvicorn (ASGI)                RuntimeFacade                     │
│    ├─ /api/* routes              ├─ SessionRegistry             │
│    ├─ /api/sessions/{id}/events  ├─ SessionActor[s1..n]         │
│    └─ StaticFiles(web/dist)      └─ EventBus                    │
│                                                                  │
│  Browser auto-open -> http://127.0.0.1:<backend_port>/          │
└──────────────────────────────────────────────────────────────────┘
```

两种模式的用户体验保持一致：执行 `klaude web` 后直接进入 Web UI。

### 2.5 SSE 事件流设计

```python
@app.get("/api/sessions/{session_id}/events", response_class=EventSourceResponse)
async def stream_events(session_id: str) -> AsyncIterable[ServerSentEvent]:
    subscription = event_bus.subscribe(session_id)
    async for envelope in subscription:
        yield ServerSentEvent(
            data=envelope,              # Pydantic model -> JSON
            event=envelope.event_type,  # 前端可按 event type 分发
            id=str(envelope.event_seq), # 断线重连锚点
        )
```

前端用 `EventSource` 消费：

```javascript
const es = new EventSource(`/api/sessions/${sessionId}/events`);
es.addEventListener("assistant_text_delta", (e) => { /* 渲染增量文本 */ });
es.addEventListener("tool_call_start", (e) => { /* 渲染工具调用 */ });
// ...
```

### 2.6 多标签页与断线重连

**多标签页共享 session**：每个浏览器标签页各自建立 SSE 连接，各自 `subscribe(session_id)`。EventBus 已支持多订阅者。

**断线重连**：EventBus 当前不持久化事件，`subscribe` 只能收到订阅之后的事件。断线重连策略：

1. 前端重连时先 `GET /api/sessions/{id}/history` 获取完整会话状态。
2. 再建立 SSE 连接接收后续实时事件。

不在服务端维护 per-session 事件 ring buffer，避免额外复杂度。会话历史已通过 `Session.conversation_history` 持久化在磁盘。

### 2.7 用户交互 (Interaction) 流程

Agent 运行中需要用户决策时（如工具审批、参数选择），走以下流程：

```
Agent 执行中需要用户输入
    |
    v
RuntimeFacade 发布 UserInteractionRequestEvent
    |
    v (通过 EventBus -> SSE)
前端收到交互请求，渲染 UI（选择框/输入框）
    |
    v (用户操作)
前端 POST /api/sessions/{id}/respond  {request_id, response}
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
        # 事件已通过 EventBus -> SSE 推送到前端
        # 等待前端通过 HTTP POST 提交响应
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

# SSE 订阅在每个 HTTP 请求中按需创建，不在初始化时统一创建
# Display 不需要 -- Web 模式下服务端不渲染，事件直接通过 SSE 推送到前端
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
    session_manager.py  # WebSessionManager：HTTP -> Operation 转换
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
| ASGI 框架 | FastAPI | 项目已用 Pydantic；SSE 原生支持 (`fastapi.sse`) |
| ASGI Server | uvicorn | 标准选择，可嵌入 asyncio loop |
| SSE | FastAPI `EventSourceResponse` | 内置 keep-alive、Cache-Control、代理穿透 |
| 序列化 | Pydantic `model_dump_json()` | EventEnvelope 已是 Pydantic 模型 |
| 前端静态文件 | Starlette `StaticFiles` | 开发时 vite dev server，发布时嵌入包 |
| 前端运行策略 | Vite dev server + StaticFiles fallback | 同一 CLI 行为覆盖源码与 PyPI 场景 |

---

## 6. 架构不变量

1. 所有入站请求都通过 `Operation` 进入核心层。
2. 所有出站事件都通过 `EventEnvelope` 经由 `EventBus` 传出。
3. Web 适配层不直接操作 `Session`、`Agent` 或 `TaskExecutor`。
4. SSE 连接是无状态的 -- 断线重连通过 history API + 重新订阅实现。
5. 核心层对 Web/TUI 的存在无感知。
