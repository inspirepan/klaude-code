# Web 服务器 MVP：后端计划（含完整 API 测试）

> **前置:** 无。该计划必须先于前端计划完成。

## 后端目标

1. `klaude web` 默认启动后端 API + 前端入口，并自动打开浏览器。
2. 在源码环境与 PyPI 安装环境都提供同样默认行为（开箱可用 Web UI）。
3. 提供稳定的 `/api` 契约，供前端后续直接接入。
4. 覆盖完整 API 自动化测试。

---

## 任务 1：依赖与打包基线

**文件：**
- 修改: `pyproject.toml`

**步骤：**
1. 保持 `fastapi`/`uvicorn`/`sse-starlette` 归入 `web` extra。
2. 明确前端构建产物（`web/dist`）在打包时被包含到 wheel/sdist。
3. 验证：
   - `uv sync --extra web`
   - `uv build` 后检查产物含静态文件（若有 dist）

**验收标准：**
- 不安装 `web` extra 时不引入 web 依赖。
- 安装 `web` extra 可正常运行 `klaude web`。

---

## 任务 2：Web 适配层与 API 应用

**文件：**
- 创建/修改: `src/klaude_code/web/app.py`
- 创建/修改: `src/klaude_code/web/display.py`
- 创建/修改: `src/klaude_code/web/interaction.py`
- 创建/修改: `src/klaude_code/web/routes/*.py`

**步骤：**
1. 实现 WebDisplay 与 WebInteractionHandler（复用核心端口抽象）。
2. 完成 API 路由：
   - `GET /api/sessions`
   - `POST /api/sessions`
   - `POST /api/sessions/{id}/message`
   - `POST /api/sessions/{id}/interrupt`
   - `POST /api/sessions/{id}/respond`
   - `POST /api/sessions/{id}/model`
   - `GET /api/sessions/{id}/history`
   - `GET /api/sessions/{id}/events` (SSE)
   - `GET /api/files`
3. 明确 `POST /api/sessions` 的语义：用于“新建 Session”按钮，以及默认新会话草稿在发送首条消息时的懒创建。

**验收标准：**
- API 返回码、响应结构与文档一致。
- SSE 能按 `session_id` 正确推流。
- 文件端点具备路径白名单保护。

---

## 任务 3：`klaude web` 启动编排（默认前后端同启 + 自动打开）

**文件：**
- 创建/修改: `src/klaude_code/web/server.py`
- 修改: `src/klaude_code/cli/main.py`

**步骤：**
1. 默认行为：
   - 启动后端 API。
   - 启动前端入口（见“运行模式”）。
   - 自动打开浏览器到前端 URL。
2. 运行模式：
   - **源码开发环境**：优先启动前端 dev server（如 Vite）并代理 `/api`。
   - **PyPI/无 Node 环境**：回退到后端托管内置 `web/dist` 静态资源。
3. CLI 选项至少保留：`--host`、`--port`、`--no-open`、`--debug`（可扩展）。
4. Ctrl+C 时同时清理 API 服务、前端子进程（若有）和 runtime 任务。

**验收标准：**
- `klaude web` 一条命令进入可用页面。
- PyPI 安装后运行体验与源码环境一致（不要求实现方式一致）。

---

## 任务 4：后端集成测试

### 测试基础设施

**文件：**
- 创建: `tests/web/__init__.py`
- 创建: `tests/web/conftest.py` -- 共享 fixtures
- 创建: `tests/web/test_session_lifecycle.py`
- 创建: `tests/web/test_ws_conversation.py`
- 创建: `tests/web/test_ws_interaction.py`
- 创建: `tests/web/test_ws_config.py`
- 创建: `tests/web/test_file_access.py`
- 创建: `tests/web/test_server_startup.py`

**测试架构：**

```
┌─────────────────────────────────────────────┐
│  httpx.AsyncClient / WebSocket              │  <- 测试客户端
├─────────────────────────────────────────────┤
│  FastAPI app (真实路由)                       │  <- 被测对象
├─────────────────────────────────────────────┤
│  RuntimeFacade + EventBus (真实)             │  <- 真实核心层
├─────────────────────────────────────────────┤
│  FakeLLMClient                              │  <- 唯一 mock 层
│    可编程返回：文本流、工具调用、交互请求         │
└─────────────────────────────────────────────┘
```

核心原则：**只 mock LLM 层**，其余全部走真实逻辑（EventBus、SessionRegistry、SessionActor、ToolExecutor）。测试体现端到端的真实流程。

**共享 fixtures（conftest.py）：**

```python
@pytest.fixture
async def app_env(tmp_path, monkeypatch):
    “””隔离环境 + 真实 RuntimeFacade + FastAPI app”””
    # 隔离 HOME，避免污染真实 session 数据
    fake_home = tmp_path / “home”
    fake_home.mkdir()
    monkeypatch.setenv(“HOME”, str(fake_home))

    # 构建真实核心层，注入 FakeLLMClient
    event_bus = EventBus()
    fake_llm = FakeLLMClient()  # 可编程 LLM 响应
    runtime = RuntimeFacade(event_bus, {“default”: fake_llm})
    interaction_handler = WebInteractionHandler()

    # 创建 FastAPI app
    app = create_app(runtime, event_bus, interaction_handler)

    async with AsyncClient(app=app, base_url=”http://test”) as client:
        yield AppEnv(
            client=client,
            app=app,
            runtime=runtime,
            event_bus=event_bus,
            fake_llm=fake_llm,
            interaction_handler=interaction_handler,
            work_dir=tmp_path / “work”,
        )

@pytest.fixture
async def ws(app_env, session_id):
    “””建立 WebSocket 连接的 helper”””
    async with app_env.client.websocket_connect(
        f”/api/sessions/{session_id}/ws”
    ) as websocket:
        yield websocket
```

**FakeLLMClient：**

```python
class FakeLLMClient:
    “””可编程的 LLM 客户端 stub，用于控制 agent 行为。”””
    def __init__(self):
        self._responses: list[list[StreamEvent]] = []

    def enqueue(self, *stream_events: StreamEvent):
        “””预设下一次 LLM 调用的流式输出”””
        self._responses.append(list(stream_events))

    async def stream(self, messages, **kwargs):
        response = self._responses.pop(0)
        for event in response:
            yield event
```

---

### 测试场景

#### 4.1 Session 生命周期 (`test_session_lifecycle.py`)

```python
async def test_create_list_delete_list():
    “””创建 -> 列出 -> 删除 -> 列出，验证完整生命周期”””
    # 1. 列出 session -- 空列表
    resp = await client.get(“/api/sessions”)
    assert resp.json()[“groups”] == []

    # 2. 创建 session
    resp = await client.post(“/api/sessions”, json={“work_dir”: “/tmp/proj”})
    session_id = resp.json()[“session_id”]
    assert resp.status_code == 200

    # 3. 列出 session -- 出现刚创建的
    resp = await client.get(“/api/sessions”)
    sessions = resp.json()[“groups”][0][“sessions”]
    assert len(sessions) == 1
    assert sessions[0][“id”] == session_id

    # 4. 删除 session（软删除）
    resp = await client.delete(f”/api/sessions/{session_id}”)
    assert resp.status_code == 200

    # 5. 列出 session -- 消失
    resp = await client.get(“/api/sessions”)
    # 验证已删除的 session 不在列表中

async def test_create_multiple_sessions_grouped_by_work_dir():
    “””多个 session 按 work_dir 分组”””
    await client.post(“/api/sessions”, json={“work_dir”: “/tmp/proj-a”})
    await client.post(“/api/sessions”, json={“work_dir”: “/tmp/proj-a”})
    await client.post(“/api/sessions”, json={“work_dir”: “/tmp/proj-b”})

    resp = await client.get(“/api/sessions”)
    groups = resp.json()[“groups”]
    assert len(groups) == 2
    # proj-a 有 2 个，proj-b 有 1 个

async def test_create_session_invalid_work_dir():
    “””不存在的 work_dir 应返回错误”””

async def test_sub_agent_sessions_filtered_from_list():
    “””sub-agent 创建的 session 不应出现在列表中”””
```

#### 4.2 WebSocket 对话流 (`test_ws_conversation.py`)

```python
async def test_send_message_receive_events():
    “””发送消息 -> 收到完整事件流 -> session 历史正确”””
    # 预设 LLM 返回
    fake_llm.enqueue(
        TextDelta(“Hello “),
        TextDelta(“world!”),
        EndOfTurn(),
    )

    # 创建 session + 建立 WS
    session_id = (await client.post(“/api/sessions”)).json()[“session_id”]
    async with ws_connect(session_id) as ws:
        # 收到 usage.snapshot 握手事件
        snapshot = await ws.receive_json()
        assert snapshot[“event_type”] == “usage.snapshot”

        # 发送消息
        await ws.send_json({“type”: “message”, “text”: “hi”})

        # 收集事件直到 operation.finished
        events = await collect_events_until(ws, “operation.finished”)

        # 验证事件序列
        types = [e[“event_type”] for e in events]
        assert “assistant.text.start” in types
        assert “assistant.text.delta” in types
        assert “assistant.text.end” in types
        assert “operation.finished” in types

        # 验证文本拼接
        text = “”.join(
            e[“event”][“content”]
            for e in events
            if e[“event_type”] == “assistant.text.delta”
        )
        assert text == “Hello world!”

    # 验证 history API 返回一致
    resp = await client.get(f”/api/sessions/{session_id}/history”)
    history_events = resp.json()[“events”]
    assert any(e[“event_type”] == “user.message” for e in history_events)
    assert any(e[“event_type”] == “assistant.text.end” for e in history_events)

async def test_multi_turn_conversation():
    “””多轮对话：发送 -> 收回复 -> 再发送 -> 收回复”””
    fake_llm.enqueue(TextDelta(“First reply”), EndOfTurn())
    fake_llm.enqueue(TextDelta(“Second reply”), EndOfTurn())

    session_id = create_session()
    async with ws_connect(session_id) as ws:
        await ws.receive_json()  # snapshot

        # Turn 1
        await ws.send_json({“type”: “message”, “text”: “hello”})
        await collect_events_until(ws, “operation.finished”)

        # Turn 2
        await ws.send_json({“type”: “message”, “text”: “again”})
        events = await collect_events_until(ws, “operation.finished”)

        text = extract_text(events)
        assert text == “Second reply”

    # history 包含两轮
    history = get_history(session_id)
    user_msgs = [e for e in history if e[“event_type”] == “user.message”]
    assert len(user_msgs) == 2

async def test_tool_call_and_result():
    “””LLM 发起工具调用 -> 工具执行 -> 返回结果 -> LLM 继续”””
    fake_llm.enqueue(
        ToolCall(name=”Bash”, arguments='{“command”: “echo test”}'),
        EndOfTurn(),
    )
    fake_llm.enqueue(TextDelta(“Done.”), EndOfTurn())

    async with ws_connect(session_id) as ws:
        await ws.send_json({“type”: “message”, “text”: “run echo”})
        events = await collect_events_until(ws, “operation.finished”)

        types = [e[“event_type”] for e in events]
        assert “tool.call” in types
        assert “tool.result” in types
        assert “assistant.text.delta” in types

async def test_send_message_while_busy_rejected():
    “””agent 运行中发送消息 -> 收到 rejected 事件”””
    fake_llm.enqueue(SlowResponse(delay=2.0))  # 模拟长时间运行

    async with ws_connect(session_id) as ws:
        await ws.send_json({“type”: “message”, “text”: “first”})
        await asyncio.sleep(0.1)  # 确保 agent 开始运行

        await ws.send_json({“type”: “message”, “text”: “second”})
        # 收到 rejected
        events = await collect_events(ws, timeout=1.0)
        assert any(e[“event_type”] == “operation.rejected” for e in events)

async def test_event_seq_monotonically_increasing():
    “””同 session 事件 seq 单调递增”””
    async with ws_connect(session_id) as ws:
        await ws.send_json({“type”: “message”, “text”: “hi”})
        events = await collect_events_until(ws, “operation.finished”)
        seqs = [e[“event_seq”] for e in events if “event_seq” in e]
        assert seqs == sorted(seqs)
        assert len(seqs) == len(set(seqs))  # 无重复
```

#### 4.3 中断 (`test_ws_conversation.py`)

```python
async def test_interrupt_stops_execution():
    “””发送消息 -> 中途 interrupt -> agent 停止 -> 可以继续对话”””
    fake_llm.enqueue(SlowTextStream(“word1 word2 word3 word4 word5”, delay_per=0.2))
    fake_llm.enqueue(TextDelta(“After interrupt”), EndOfTurn())

    async with ws_connect(session_id) as ws:
        await ws.send_json({“type”: “message”, “text”: “long task”})

        # 等待收到一些 delta 后中断
        await wait_for_event(ws, “assistant.text.delta”)
        await ws.send_json({“type”: “interrupt”})

        # 收集直到 finished
        events = await collect_events_until(ws, “operation.finished”)
        assert any(e[“event_type”] == “interrupt” for e in events)

        # 中断后可以继续
        await ws.send_json({“type”: “message”, “text”: “continue”})
        events = await collect_events_until(ws, “operation.finished”)
        text = extract_text(events)
        assert text == “After interrupt”
```

#### 4.4 交互请求 (`test_ws_interaction.py`)

```python
async def test_ask_user_question_flow():
    “””LLM 发起 AskUserQuestion -> 前端收到 -> WS 回复 -> agent 继续”””
    fake_llm.enqueue(
        ToolCall(name=”AskUserQuestion”, arguments=json.dumps({
            “questions”: [{“question”: “Which?”, “options”: [{“label”: “A”}, {“label”: “B”}]}]
        })),
        EndOfTurn(),
    )
    fake_llm.enqueue(TextDelta(“You chose A”), EndOfTurn())

    async with ws_connect(session_id) as ws:
        await ws.send_json({“type”: “message”, “text”: “ask me”})

        # 收到交互请求事件
        interaction_evt = await wait_for_event(ws, “user.interaction.request”)
        request_id = interaction_evt[“event”][“request_id”]

        # 通过 WS 回复
        await ws.send_json({
            “type”: “respond”,
            “request_id”: request_id,
            “status”: “submitted”,
            “payload”: {
                “kind”: “ask_user_question”,
                “answers”: [{“question_id”: “q0”, “selected_option_ids”: [“opt_0”]}]
            }
        })

        # agent 继续执行
        events = await collect_events_until(ws, “operation.finished”)
        assert extract_text(events) == “You chose A”

async def test_interaction_cancel():
    “””交互请求 -> 取消 -> agent 收到取消信号”””

async def test_interaction_timeout_on_ws_disconnect():
    “””WS 断开时 pending interaction 应被清理”””
```

#### 4.5 配置变更 (`test_ws_config.py`)

```python
async def test_change_model():
    “””WS 发送 model 切换 -> 收到 model.changed 事件”””
    async with ws_connect(session_id) as ws:
        await ws.send_json({
            “type”: “model”,
            “model_name”: “claude-sonnet-4-20250514”,
            “save_as_default”: False,
        })
        evt = await wait_for_event(ws, “model.changed”)
        assert evt[“event”][“model_name”] == “claude-sonnet-4-20250514”

async def test_change_thinking():
    “””WS 发送 thinking 切换 -> 收到 thinking.changed 事件”””

async def test_get_models():
    “””GET /api/config/models 返回可用模型列表”””
```

#### 4.6 断线重连 (`test_ws_conversation.py`)

```python
async def test_reconnect_via_history():
    “””对话 -> WS 断开 -> GET history -> 新 WS -> 继续对话”””
    fake_llm.enqueue(TextDelta(“First”), EndOfTurn())
    fake_llm.enqueue(TextDelta(“After reconnect”), EndOfTurn())

    # 第一轮对话
    async with ws_connect(session_id) as ws:
        await ws.send_json({“type”: “message”, “text”: “hello”})
        await collect_events_until(ws, “operation.finished”)
    # WS 断开

    # 重连：拉历史
    resp = await client.get(f”/api/sessions/{session_id}/history”)
    assert resp.status_code == 200
    history = resp.json()[“events”]
    assert len(history) > 0

    # 新 WS 继续对话
    async with ws_connect(session_id) as ws:
        snapshot = await ws.receive_json()
        assert snapshot[“event_type”] == “usage.snapshot”

        await ws.send_json({“type”: “message”, “text”: “world”})
        events = await collect_events_until(ws, “operation.finished”)
        assert extract_text(events) == “After reconnect”

async def test_usage_snapshot_on_connect():
    “””WS 连接后第一条消息是 usage.snapshot”””
    fake_llm.enqueue(TextDelta(“hi”), EndOfTurn())

    # 先进行一轮对话，产生 usage
    async with ws_connect(session_id) as ws:
        await ws.receive_json()  # first snapshot (zero)
        await ws.send_json({“type”: “message”, “text”: “hi”})
        await collect_events_until(ws, “operation.finished”)

    # 重新连接，snapshot 包含之前的累计值
    async with ws_connect(session_id) as ws:
        snapshot = await ws.receive_json()
        assert snapshot[“event_type”] == “usage.snapshot”
        usage = snapshot[“event”][“usage”]
        assert usage[“input_tokens”] > 0
        assert usage[“output_tokens”] > 0
```

#### 4.7 多 WS 连接 (`test_ws_conversation.py`)

```python
async def test_multiple_ws_receive_same_events():
    “””同一 session 两个 WS 连接都能收到事件”””
    fake_llm.enqueue(TextDelta(“broadcast”), EndOfTurn())

    async with ws_connect(session_id) as ws1, ws_connect(session_id) as ws2:
        await ws1.receive_json()  # snapshot
        await ws2.receive_json()  # snapshot

        # 从 ws1 发送消息
        await ws1.send_json({“type”: “message”, “text”: “hi”})

        # 两个连接都收到事件
        events1 = await collect_events_until(ws1, “operation.finished”)
        events2 = await collect_events_until(ws2, “operation.finished”)

        assert extract_text(events1) == “broadcast”
        assert extract_text(events2) == “broadcast”
```

#### 4.8 文件访问安全 (`test_file_access.py`)

```python
async def test_file_access_allowed_work_dir():
    “””work_dir 内的文件可访问”””
    (work_dir / “test.txt”).write_text(“hello”)
    resp = await client.get(“/api/files”, params={“path”: str(work_dir / “test.txt”)})
    assert resp.status_code == 200

async def test_file_access_allowed_tmp():
    “””/tmp 下的文件可访问”””

async def test_file_access_allowed_session_images():
    “””session images 目录可访问”””

async def test_file_access_denied_path_traversal():
    “””路径穿越被拒绝”””
    resp = await client.get(“/api/files”, params={“path”: “/etc/passwd”})
    assert resp.status_code == 403

async def test_file_access_denied_dotdot():
    “””.. 穿越被拒绝”””
    resp = await client.get(“/api/files”, params={
        “path”: str(work_dir / “..” / “..” / “etc” / “passwd”)
    })
    assert resp.status_code == 403

async def test_file_not_found():
    “””不存在的文件返回 404”””
    resp = await client.get(“/api/files”, params={“path”: str(work_dir / “nope.txt”)})
    assert resp.status_code == 404
```

#### 4.9 启动行为 (`test_server_startup.py`)

```python
async def test_default_startup_opens_browser():
    “””默认启动会调用浏览器打开”””
    with patch(“webbrowser.open”) as mock_open:
        await start_web_server(no_open=False)
        mock_open.assert_called_once()

async def test_no_open_flag():
    “””--no-open 不打开浏览器”””
    with patch(“webbrowser.open”) as mock_open:
        await start_web_server(no_open=True)
        mock_open.assert_not_called()

async def test_fallback_to_static_when_no_node():
    “””无 Node 环境时回退到静态文件托管”””

async def test_packaged_env_serves_static():
    “””模拟 PyPI 安装环境，/api/sessions 可访问”””
```

---

### 测试辅助函数

```python
async def collect_events_until(ws, target_type, timeout=5.0):
    “””收集 WS 事件直到指定类型出现”””
    events = []
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        data = await asyncio.wait_for(ws.receive_json(), timeout=1.0)
        events.append(data)
        if data.get(“event_type”) == target_type:
            return events
    raise TimeoutError(f”未收到 {target_type}”)

async def wait_for_event(ws, event_type, timeout=5.0):
    “””等待特定类型的事件”””
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        data = await asyncio.wait_for(ws.receive_json(), timeout=1.0)
        if data.get(“event_type”) == event_type:
            return data
    raise TimeoutError(f”未收到 {event_type}”)

def extract_text(events):
    “””从事件列表中提取拼接的 assistant 文本”””
    return “”.join(
        e[“event”][“content”]
        for e in events
        if e.get(“event_type”) == “assistant.text.delta”
    )
```

**验收标准：**
- `pytest tests/web/ -v` 全通过。
- 与 `make test`、`make lint` 不冲突。
- 不依赖真实 LLM API Key（FakeLLMClient 覆盖所有场景）。

---

## 完成定义（DoD）

- 后端 API 文档与实现一致。
- 默认启动与 PyPI 场景行为一致（一键可用）。
- 自动化测试覆盖完整且稳定。
