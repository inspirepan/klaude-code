# Web 服务器 MVP 实现计划

> **针对 Claude:** 使用 executing-plans 技能逐任务实现此计划。

**目标:** 添加一个 `klaude web` 命令，启动一个 FastAPI 服务器，通过 REST + SSE 公开核心运行时，并为多会话聊天提供 React 前端。

**架构:** 重用现有的端口适配器架构。创建 `WebDisplay(DisplayABC)` 和 `WebInteractionHandler(InteractionHandlerABC)` 适配器，将事件桥接到 SSE 流和 HTTP 响应。前端是位于 `web/` 中的 Vite + React SPA，在开发期间代理，在生产中通过 StaticFiles 嵌入。

**技术栈:** Python: FastAPI、uvicorn、sse-starlette。前端: React、TypeScript、Vite、Tailwind CSS、shadcn/ui、Zustand、streamdown、@pierre/diffs、@uiw/react-json-view。字体: Inter、TX-02。

**设计文档:**
- `docs/web/1-execution-architecture.md`
- `docs/web/2-frontend-and-api-design.md`
- `docs/web/3-style-guide.md`

---

## 阶段 1: 后端基础

### 任务 1: 添加 Web 依赖到 pyproject.toml

**文件:**
- 修改: `pyproject.toml`

**意图:** 将 FastAPI、uvicorn 和 sse-starlette 作为可选依赖添加到 `[project.optional-dependencies] web` 组下，以避免加重基础 CLI 安装。

**步骤:**
1. 添加 `[project.optional-dependencies]` 部分，包含 `web = ["fastapi>=0.115", "uvicorn[standard]>=0.34", "sse-starlette>=2.0"]`
2. 验证: `uv sync --extra web`
3. 提交: `feat(web): add optional web dependencies`

**验收标准:**
- `uv sync --extra web` 无错误安装 fastapi、uvicorn、sse-starlette
- `uv sync` (不带 extra) 不安装它们
- 现有 `klaude` 命令仍然有效

---

### 任务 2: 使用 WebDisplay 和 WebInteractionHandler 创建 Web 模块骨架

**文件:**
- 创建: `src/klaude_code/web/__init__.py`
- 创建: `src/klaude_code/web/display.py`
- 创建: `src/klaude_code/web/interaction.py`
- 测试: `tests/test_web_display.py`

**意图:** 实现两个端口适配器，将核心运行时桥接到 Web 层。`WebDisplay` 收集事件包信封并向 SSE 订阅者分发。`WebInteractionHandler` 使用 asyncio Futures 桥接核心交互请求到 HTTP POST 响应。

**步骤:**
1. 为 `WebDisplay` 编写测试: 构造它，用几个事件调用 `consume_envelope`，验证它们出现在订阅者队列中。
2. 实现 `WebDisplay(DisplayABC)`:
   - `start()` / `stop()`: 无操作（Web 服务器生命周期由外部管理）
   - `consume_envelope()`: 将事件包信封序列化为 JSON 并推送到所有注册的 SSE 订阅者队列
   - `subscribe(session_id) -> AsyncIterator`: 创建每个客户端的 asyncio.Queue，产生序列化事件，按 session_id 筛选
   - 追踪单调递增的 `event_seq` 计数器用于 SSE `id` 字段
3. 为 `WebInteractionHandler` 编写测试: 发布请求事件，验证它保存在待处理字典中，通过 `resolve_interaction()` 解决，验证 `collect_response` 返回。
4. 实现 `WebInteractionHandler(InteractionHandlerABC)`:
   - `collect_response(event)`: 存储以 `request_id` 为键的 `asyncio.Future`，await 它
   - `resolve_interaction(request_id, response)`: 解决对应的 Future
   - `get_pending_interactions()`: 返回待处理 request_ids 列表（用于 REST 端点）
5. 验证: `pytest tests/test_web_display.py tests/test_web_interaction.py -v`
6. 提交: `feat(web): add WebDisplay and WebInteractionHandler adapters`

**验收标准:**
- WebDisplay 并发向多个订阅者分发事件
- WebDisplay 在需要时按 session_id 筛选事件
- WebInteractionHandler 正确地跨协程桥接异步请求/响应
- 断开连接时清理订阅者（从集合中移除队列）

**注意:**
- 参考 `src/klaude_code/app/ports/display.py` 了解 `DisplayABC` 接口
- 参考 `src/klaude_code/app/ports/interaction.py` 了解 `InteractionHandlerABC` 接口
- 事件序列化: 在事件上使用 Pydantic 的 `.model_dump(mode="json")`，包装在 `{"type": event.type, "session_id": envelope.session_id, "seq": N, "data": ...}`

---

### 任务 3: 使用核心端点创建 FastAPI 应用程序

**文件:**
- 创建: `src/klaude_code/web/app.py`
- 创建: `src/klaude_code/web/routes/__init__.py`
- 创建: `src/klaude_code/web/routes/sessions.py`
- 创建: `src/klaude_code/web/routes/events.py`
- 创建: `src/klaude_code/web/routes/files.py`
- 测试: `tests/test_web_app.py`

**意图:** 使用设计文档（第 2 节）中定义的 MVP API 端点连接 FastAPI 应用。该应用保持对 `RuntimeFacade`、`WebDisplay` 和 `WebInteractionHandler` 的引用。

**步骤:**
1. 使用 `httpx.AsyncClient` + FastAPI 的 `TestClient` 编写集成测试:
   - `GET /api/sessions` 返回会话列表
   - `POST /api/sessions` 创建会话
   - `POST /api/sessions/{id}/message` 提交消息
   - `POST /api/sessions/{id}/interrupt` 提交中断
   - `GET /api/files?path=...` 返回文件内容，正确的 Content-Type，拒绝白名单外的路径
2. 实现 `app.py`:
   - 创建 FastAPI 应用实例
   - 在工厂函数 `create_app(runtime, display, interaction_handler, work_dir) -> FastAPI` 中接受 `RuntimeFacade`、`WebDisplay`、`WebInteractionHandler`
   - 挂载路由模块
3. 实现 `routes/sessions.py`:
   - `GET /api/sessions` — 调用 `Session.list_sessions()`，按 work_dir 分组，筛选子代理
   - `POST /api/sessions` — 使用运行时调用 `initialize_session()`
   - `POST /api/sessions/{id}/message` — 构建 `RunAgentOperation`，提交到运行时
   - `POST /api/sessions/{id}/interrupt` — 提交 `InterruptOperation`
   - `POST /api/sessions/{id}/respond` — 调用 `WebInteractionHandler.resolve_interaction()`
   - `POST /api/sessions/{id}/model` — 提交 `ChangeModelOperation`
   - `GET /api/sessions/{id}/history` — 调用 `Session.get_history_item()`，序列化为 JSON 数组
4. 实现 `routes/events.py`:
   - `GET /api/sessions/{id}/events` — 使用 `sse-starlette` 的 `EventSourceResponse` 的 SSE 端点，从 `WebDisplay.subscribe(session_id)` 消费
5. 实现 `routes/files.py`:
   - `GET /api/files` — 验证路径是否在白名单内（会话目录、work_dir、/tmp），返回带有推断 Content-Type 的 `FileResponse`
6. 验证: `pytest tests/test_web_app.py -v`
7. 提交: `feat(web): add FastAPI app with MVP API endpoints`

**验收标准:**
- 所有 MVP 端点以正确的状态码和形状响应
- SSE 端点流式传输按 session_id 筛选的事件
- 文件端点阻止路径遍历和白名单外的路径
- 测试模拟 RuntimeFacade/Session 以避免需要真实 LLM 客户端

**注意:**
- `Session.list_sessions()` 已筛选子代理。对于跨项目列表，需要迭代 `~/.klaude/projects/*/sessions/` — 可以延迟到助手。
- `GET /api/sessions/{id}/history` 返回 `ReplayEventUnion` 序列 — 与 SSE 事件形状相同，所以前端使用相同的渲染代码。

---

### 任务 4: 创建 `klaude web` CLI 命令和服务器启动

**文件:**
- 创建: `src/klaude_code/web/server.py`
- 修改: `src/klaude_code/cli/main.py`
- 测试: `tests/test_web_server_startup.py`

**意图:** 将 Web 服务器连接到 CLI。`klaude web` 使用 FastAPI 应用启动 uvicorn，使用 WebDisplay/WebInteractionHandler 初始化核心运行时。服务器在与运行时相同的 asyncio 事件循环中运行。

**步骤:**
1. 实现 `server.py`:
   - `async def run_web_server(host, port, init_config)` — 使用 WebDisplay + WebInteractionHandler 初始化应用组件，创建 FastAPI 应用，通过 `uvicorn.Server(config).serve()` 以编程方式运行 uvicorn
   - 处理优雅关闭（SIGINT/SIGTERM → cleanup_app_components）
2. 在 CLI 中注册 `web` 命令:
   - 在 `main.py` 中添加 `@app.command("web")`（或创建 `web_cmd.py` 并 `register_web_commands(app)`）
   - 选项: `--host`（默认 `127.0.0.1`）、`--port`（默认 `8765`）、`--dev`（跳过静态文件服务）、`--debug`
3. 编写基本测试，服务器启动并响应 `GET /api/sessions`
4. 验证: `klaude web --help` 显示命令。手动测试: `klaude web` 启动，`curl http://localhost:8765/api/sessions` 返回 JSON。
5. 提交: `feat(web): add klaude web CLI command`

**验收标准:**
- `klaude web` 在 localhost:8765 上启动服务器
- `GET /api/sessions` 返回有效的 JSON
- Ctrl+C 优雅关闭运行时和服务器
- `--dev` 标志跳过静态文件挂载（用于 vite dev 代理）

**注意:**
- 遵循 `main.py` 中的模式，其中命令通过 `register_*_commands(app)` 注册。
- `typer.Exit(2)` 来自 `initialize_app_components` 的缺失模型配置模式应优雅处理（返回 HTTP 错误，不崩溃服务器）。
- 考虑在 fastapi/uvicorn 导入后面加一个 try/except，如果未安装 `web` extra，给出有用的错误消息。

---

## 阶段 2: 前端基础

### 任务 5: 构建前端项目

**文件:**
- 创建: `web/` 目录（Vite + React + TypeScript + Tailwind + shadcn/ui）
- 创建: `web/public/fonts/tx-02.woff2`（从 `~/Downloads/TX-02-OpenCode/` 复制）
- 创建: `web/public/fonts/tx-02-bold.otf`、`tx-02-italic.otf`、`tx-02-bold-italic.otf`

**意图:** 使用所有工具配置设置前端项目: Vite dev 服务器（带 API 代理）、带有 Claude 灵感色板的 Tailwind、TX-02 字体、已初始化的 shadcn/ui。

**步骤:**
1. 从项目根目录运行 `pnpm create vite web --template react-ts`
2. `cd web && pnpm install`
3. 初始化 Tailwind: `pnpm add -D tailwindcss @tailwindcss/vite` 并配置
4. 初始化 shadcn/ui: `pnpm dlx shadcn@latest init`
5. 配置 `vite.config.ts` 代理: `/api` → `http://localhost:8765`
6. 将 TX-02 字体文件复制到 `web/public/fonts/`
7. 从 `docs/web/3-style-guide.md` 在全局 CSS 中设置 `@font-face` 声明和 CSS 变量
8. 配置 Tailwind 主题扩展（颜色、字体）以匹配样式指南
9. 安装核心依赖: `pnpm add zustand streamdown @streamdown/code @streamdown/mermaid @uiw/react-json-view @pierre/diffs`
10. 验证: `cd web && pnpm dev` 无错误启动，使用正确的字体显示默认 Vite 页面
11. 提交: `feat(web): scaffold frontend with Vite, React, Tailwind, shadcn/ui`

**验收标准:**
- `pnpm dev` 在 :5173 上启动
- 代理到 :8765 有效（当后端运行时，`/api/sessions` 正确代理）
- TX-02 字体在测试 `<code>` 块中呈现
- 使用自定义颜色的 Tailwind 类起作用（`bg-background`、`text-primary` 等）

**注意:**
- 将 `web/node_modules/` 和 `web/dist/` 添加到项目 `.gitignore`
- 不添加 `@fontsource/inter` — 使用 `index.html` 中的 Google Fonts CDN 链接以简化操作

---

### 任务 6: 实现基础布局（侧边栏 + 主区域）

**文件:**
- 创建: `web/src/App.tsx`
- 创建: `web/src/components/sidebar/Sidebar.tsx`
- 创建: `web/src/components/sidebar/SessionCard.tsx`
- 创建: `web/src/components/layout/MainPanel.tsx`
- 添加 shadcn/ui 组件: Sidebar、ScrollArea、Sheet（用于移动设备）

**意图:** 构建两列布局: 左侧边栏带会话列表，右侧主区域。移动设备: 侧边栏作为 Sheet 抽屉。这是所有其他组件将放入的外壳。

**步骤:**
1. 添加 shadcn/ui Sidebar 组件: `pnpm dlx shadcn@latest add sidebar scroll-area sheet`
2. 使用 SidebarProvider + Sidebar + 主内容区域构建 `App.tsx`
3. 构建 `Sidebar.tsx`: 项目组 → 会话卡，顶部搜索输入
4. 构建 `SessionCard.tsx`: 显示第一条用户消息作为标题、时间前推、消息计数
5. 构建 `MainPanel.tsx`: 空状态（"选择或创建会话"），将托管 MessageList 和 InputArea
6. 连接移动响应式行为（md 断点下作为 Sheet 的侧边栏）
7. 验证: `pnpm dev` 显示两列布局，带占位符内容
8. 提交: `feat(web): add base layout with sidebar and main panel`

**验收标准:**
- 桌面: 固定侧边栏（260px）+ 可滚动主区域
- 移动设备（<768px）: 汉堡按钮 → 侧边栏的 Sheet 抽屉
- 会话卡显示占位符数据（现在硬编码）
- 未选择会话时显示空状态

---

### 任务 7: 实现 Zustand 存储和 API 客户端

**文件:**
- 创建: `web/src/stores/app-store.ts`
- 创建: `web/src/stores/session-store.ts`
- 创建: `web/src/api/client.ts`
- 创建: `web/src/api/sse.ts`
- 创建: `web/src/types/events.ts`
- 创建: `web/src/types/session.ts`

**意图:** 设置状态管理层和 API 客户端。应用存储保存会话列表和当前选择。会话存储保存活跃会话的消息/事件。SSE 客户端连接到事件流并将事件分派到存储。

**步骤:**
1. 为会话元数据、事件包信封和 API 响应定义 TypeScript 类型（匹配 Pydantic 模型）
2. 实现 `client.ts`: 围绕 `fetch()` 的瘦包装器，用于每个 REST 端点（`listSessions`、`createSession`、`sendMessage`、`interrupt`、`respond`、`getHistory`）
3. 实现 `sse.ts`: `connectSSE(sessionId) -> EventSource` 包装器，解析 SSE 事件并调用分派回调。处理重新连接。
4. 实现 `app-store.ts`（Zustand）:
   - 状态: `sessions`、`currentSessionId`、`loading`
   - 操作: `fetchSessions`、`selectSession`、`createSession`
5. 实现 `session-store.ts`（Zustand）:
   - 状态: `events[]`（当前会话的消息/事件列表）、`isStreaming`、`pendingInteraction`
   - 操作: `loadHistory`、`appendEvent`、`sendMessage`、`interrupt`
   - SSE 连接管理: 选择会话时连接，取消选择时断开连接
6. 验证: 将存储连接到侧边栏，选择会话触发历史获取（在 devtools/console 中可见）
7. 提交: `feat(web): add Zustand stores, API client, and SSE connection`

**验收标准:**
- 侧边栏从 `GET /api/sessions` 加载真实会话列表（需要后端运行）
- 选择会话获取历史并连接 SSE
- 控制台日志显示事件从 SSE 流到达
- SSE 在断开连接时重新连接

---

## 阶段 3: 消息渲染

### 任务 8: 实现 MessageList 和核心消息组件

**文件:**
- 创建: `web/src/components/messages/MessageList.tsx`
- 创建: `web/src/components/messages/UserMessage.tsx`
- 创建: `web/src/components/messages/AssistantText.tsx`
- 创建: `web/src/components/messages/ThinkingBlock.tsx`

**意图:** 渲染核心消息类型: 用户消息、助手流式 markdown 文本和思考块。这是最重要的视觉组件 — 对话流。

**步骤:**
1. 构建 `MessageList.tsx`: 从会话存储读取，按事件类型映射事件到组件，新事件时自动滚动到底部
2. 构建 `UserMessage.tsx`: 在带有 `--user-bubble` 背景的气泡中渲染用户文本
3. 构建 `AssistantText.tsx`: 使用 `<Streamdown>` 与 `@streamdown/code` 和 `@streamdown/mermaid` 插件用于流式 markdown 渲染。包括 [Raw] 切换（显示原始 markdown 源）和 [Copy] 按钮。
4. 构建 `ThinkingBlock.tsx`: 可折叠块，汇总思考增量，流式传输时显示"Thinking..."标签。[Copy] 按钮。
5. 验证: 启动后端，创建会话，发送消息，看到助手响应使用 markdown 格式和语法高亮进行渲染
6. 提交: `feat(web): add message rendering with streaming markdown`

**验收标准:**
- 用户消息使用温暖的气泡背景渲染
- 助手文本实时流式传输，正确的 markdown 格式
- 代码块通过 streamdown 具有 Shiki 语法高亮
- 思考块可折叠，完成后默认折叠
- [Raw] 和 [Copy] 按钮在 AssistantText 上起作用

---

### 任务 9: 实现 ToolCall 和 ToolResult 组件

**文件:**
- 创建: `web/src/components/messages/ToolCall.tsx`
- 创建: `web/src/components/messages/ToolResult.tsx`
- 创建: `web/src/components/messages/tool-renderers/DiffView.tsx`
- 创建: `web/src/components/messages/tool-renderers/ReadPreview.tsx`
- 创建: `web/src/components/messages/tool-renderers/TodoListView.tsx`
- 创建: `web/src/components/messages/tool-renderers/ImageView.tsx`
- 创建: `web/src/components/messages/tool-renderers/PlainText.tsx`

**意图:** 根据设计文档（第 4 和 5 节）中的渲染规则渲染工具调用和工具结果。每个工具调用显示 `[mark] Name details`，带有 [Raw JSON] 和 [Copy] 按钮。工具结果根据 `ui_extra.type` 分派到专门的渲染器。

**步骤:**
1. 构建 `ToolCall.tsx`: 按 `tool_name` 分派以提取每个设计文档第 4.2 节的 mark/name/details。原始模式显示 `@uiw/react-json-view` 中的 `<JsonView>`。
2. 构建 `ToolResult.tsx`: 按 `ui_extra.type` 分派到子组件。错误结果使用错误样式渲染。原始模式显示 `<JsonView>`。
3. 构建 `DiffView.tsx`: 当可用 `raw_unified_diff` 时使用 `@pierre/diffs/react` 中的 `<PatchDiff>`，否则从 `files[].lines[]` 重新构建。移动设备: `diffStyle: 'unified'`。
4. 构建 `ReadPreview.tsx`: 带行号的代码块，"more N lines"截断指示符
5. 构建 `TodoListView.tsx`: 复选框列表，完成的项目带有复选标记样式
6. 构建 `ImageView.tsx`: `<img src={/api/files?path=...}>` 加载状态
7. 构建 `PlainText.tsx`: 截断文本，长输出扩展/折叠（例如 Bash）
8. 验证: 触发各种工具（Read、Edit、Bash、WebSearch、TodoWrite）并验证渲染
9. 提交: `feat(web): add ToolCall and ToolResult rendering`

**验收标准:**
- 每个工具类型使用正确的 mark 图标和 details 提取进行渲染
- Diff 视图显示语法高亮的分割视图（桌面）/ 统一（移动设备）
- [Raw JSON] 切换适用于所有工具调用和结果
- [Copy] 适用于所有组件
- 错误工具结果显示红色错误样式

**注意:**
- 参考设计文档第 4.2 节了解完整的工具名称到渲染器映射
- 参考设计文档第 5.3 节了解 UIExtra 类型分派表

---

### 任务 10: 实现 SubAgentCard

**文件:**
- 创建: `web/src/components/messages/SubAgentCard.tsx`

**意图:** 将子代理执行渲染为带彩色左边框的独立可折叠卡。每个卡包含完整消息流（重用相同的渲染组件）。参见设计文档第 3.3 节。

**步骤:**
1. 构建 `SubAgentCard.tsx`:
   - 彩色左边框（按子代理索引轮换预设颜色）
   - 标题: 代理类型 + 描述
   - 主体: 为子代理的事件重用类似 MessageList 的渲染（按 session_id 筛选）
   - 页脚: 完成状态 + token 统计
   - 折叠/展开切换
2. 更新 `MessageList.tsx` 以检测子代理事件（通过 `session_id` 与主不同）并将其路由到 SubAgentCard 实例中
3. 处理递归嵌套（子代理的子代理 → 嵌套的 SubAgentCard）
4. 验证: 触发子代理工具调用，看到它渲染为独立卡
5. 提交: `feat(web): add sub-agent card rendering`

**验收标准:**
- 子代理呈现为独立卡，不与父消息交错
- 左边框颜色区分并行子代理
- 卡可折叠；折叠时显示标题 + 状态摘要
- 内部工具调用/结果在卡内正确渲染
- 递归嵌套起作用（至少 2 级）

---

## 阶段 4: 输入和交互

### 任务 11: 使用发送/停止/模型选择器实现 InputArea

**文件:**
- 创建: `web/src/components/input/InputArea.tsx`
- 创建: `web/src/components/input/ModelSelector.tsx`
- 添加 shadcn/ui 组件: Textarea、Button、DropdownMenu

**意图:** 构建底部输入区域: 带有发送按钮（流式传输时为停止按钮）的文本输入、模型选择器下拉菜单。

**步骤:**
1. 添加 shadcn/ui: `pnpm dlx shadcn@latest add textarea button dropdown-menu`
2. 构建 `InputArea.tsx`:
   - 自动调整大小的 textarea（shift+enter 换行，enter 发送）
   - 发送按钮: 调用 `sendMessage` 存储操作 → `POST /api/sessions/{id}/message`
   - 停止按钮（流式传输时显示）: 调用 `interrupt` → `POST /api/sessions/{id}/interrupt`
   - 粘性底部定位
3. 构建 `ModelSelector.tsx`: 显示可用模型的下拉菜单，调用 `POST /api/sessions/{id}/model`
4. 处理禁用状态（无会话选择或会话繁忙时）（MVP: 在代理执行期间拒绝）
5. 验证: 发送消息并看到它们出现在对话中，停止按钮中断生成
6. 提交: `feat(web): add input area with send, stop, and model selector`

**验收标准:**
- Enter 发送消息，shift+enter 插入换行符
- 代理执行时输入禁用（MVP 行为）
- 停止按钮在流式传输期间显示并中断执行
- 模型选择器为当前会话切换模型

---

### 任务 12: 实现用户交互 UI（AskUserQuestion、工具批准）

**文件:**
- 创建: `web/src/components/messages/InteractionRequest.tsx`

**意图:** 当代理询问用户问题（AskUserQuestion 工具）或请求批准危险操作时，在消息流中内联渲染交互式 UI。用户的响应通过 `POST /api/sessions/{id}/respond` 发布回去。

**步骤:**
1. 构建 `InteractionRequest.tsx`:
   - 对于 `ask_user_question` 类型: 渲染问题文本 + 选项按钮（单/多选）+ 自由文本输入
   - 对于 `operation_select` 类型: 渲染选项列表
   - 提交按钮调用存储操作 → `POST /respond`
   - 如果交互被系统取消，显示"已取消"状态
2. 连接到 `MessageList.tsx`: 当 `user.interaction.request` 事件到达时渲染 `InteractionRequest`
3. 处理交互解决: `user.interaction.resolved` 事件移除交互式 UI
4. 验证: 触发 AskUserQuestion 工具（例如，通过使用它的技能），通过 Web UI 响应
5. 提交: `feat(web): add user interaction request handling`

**验收标准:**
- 带选项的问题渲染可选择的按钮
- 自定义响应可用自由文本输入
- 响应被发送到后端，代理继续
- 已解决/已取消状态正确显示

---

## 阶段 5: 状态栏和打磨

### 任务 13: 实现状态栏

**文件:**
- 创建: `web/src/components/status/StatusBar.tsx`

**意图:** 底部状态栏显示上下文使用、token 计数、模型名称和当前操作的经过时间。

**步骤:**
1. 构建 `StatusBar.tsx`:
   - 上下文使用: 来自 `UsageEvent` 数据的百分比栏
   - 来自会话元数据的模型名称
   - 可用时的成本/token 摘要
   - 活跃操作期间经过的时间
2. 连接到布局（固定底部，在 InputArea 下方）
3. 响应式: 桌面上的完整信息，移动设备上的缩写
4. 验证: 运行会话，看到状态栏实时更新
5. 提交: `feat(web): add status bar`

**验收标准:**
- 随着对话增长，上下文百分比更新
- 模型名称显示
- 移动设备显示缩写版本

---

### 任务 14: 生产构建的静态文件服务

**文件:**
- 修改: `src/klaude_code/web/app.py`
- 修改: `web/package.json`（添加构建脚本）

**意图:** 在非开发模式下，FastAPI 应用通过 Starlette 的 StaticFiles 从 `web/dist/` 提供前端构建输出。SPA 回退为所有非 API 路由返回 `index.html`。

**步骤:**
1. 在 `web/package.json` 中添加 `pnpm build` 脚本（已从 Vite 默认）
2. 在 `app.py` 中，当未设置 `--dev` 时，在 API 路由后作为全局挂载 `StaticFiles(directory=web_dist_path, html=True)`
3. 确定 `web_dist_path` 相对于包安装位置（使用 `importlib.resources` 或 `Path(__file__).parent`）
4. 验证: `cd web && pnpm build`，然后 `klaude web`（不带 `--dev`）在 `http://localhost:8765/` 提供构建的前端
5. 提交: `feat(web): serve frontend build in production mode`

**验收标准:**
- `klaude web` 在根 `/` 提供 SPA
- `/api/*` 路由仍然有效
- SPA 客户端路由有效（任何非 API 路径返回 index.html）
- `klaude web --dev` 不挂载静态文件

---

### 任务 15: 端到端烟雾测试

**文件:**
- 修改: （没有新文件，手动验证）

**意图:** 完整的端到端验证完整流程。

**步骤:**
1. `klaude web` — 服务器启动
2. 在浏览器中打开 `http://localhost:8765`
3. 验证侧边栏加载现有会话
4. 创建新会话
5. 发送消息，验证流式响应渲染
6. 验证工具调用呈现（Read、Edit、Bash）
7. 验证思考块折叠
8. 验证 [Raw] 和 [Copy] 按钮起作用
9. 验证移动布局（响应式开发工具）
10. 验证停止按钮中断
11. 验证页面重新加载重新连接 SSE
12. 提交: `feat(web): web server MVP complete`

**验收标准:**
- 以上所有手动检查都通过
- 浏览器中没有控制台错误
- 服务器日志中没有 Python 回溯
