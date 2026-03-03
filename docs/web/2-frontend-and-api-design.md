# Web UI -- 前端组件与 API 设计

本文定义 Web UI 的前端组件树、后端 API 端点，以及前后端之间的数据映射关系。

标记说明：
- MVP -- 第一期实现
- Later -- 后续迭代
- N/A -- 当前 TUI agent 尚不支持，暂不考虑

---

## 1. 前端组件树

```
App
├── LeftSidebar                                         [MVP]
│   ├── NewSessionButton                                [MVP]
│   └── SessionList                                     [MVP]
│       └── ProjectGroup (按 work_dir 分组)               [MVP]
│           └── SessionCard                             [MVP]
│               ├── 首条 user message 作为标题             [MVP]
│               ├── 时间戳、消息数                         [MVP]
│               └── 模型名                               [MVP]
│
├── SessionDetailContainer                              [MVP]
│   ├── NewSessionDraftView (默认详情页，未持久化)          [MVP]
│   ├── MessageList (主体消息流)                          [MVP]
│   │   ├── UserMessage                                 [MVP]
│   │   ├── DeveloperMessage                            [MVP]
│   │   ├── ThinkingBlock (折叠，流式展开)                 [MVP]
│   │   ├── AssistantText (流式 Markdown 渲染)            [MVP]
│   │   │   └── Mermaid 图渲染                           [MVP]
│   │   ├── ToolCall                                    [MVP]
│   │   │   ├── 工具名 + 参数摘要                         [MVP]
│   │   │   └── AskUserQuestion 交互                     [MVP]
│   │   │       └── Plan 交互                            [N/A]
│   │   ├── ToolResult                                  [MVP]
│   │   │   ├── DiffUIExtra (文件 diff 渲染)              [MVP]
│   │   │   ├── TodoListUIExtra                         [MVP]
│   │   │   ├── ReadPreviewUIExtra                      [MVP]
│   │   │   ├── ImageUIExtra                            [MVP]
│   │   │   ├── AskUserQuestionSummaryUIExtra           [MVP]
│   │   │   ├── SessionIdUIExtra (sub-agent 链接)        [MVP]
│   │   │   ├── MultiUIExtra (组合渲染)                   [MVP]
│   │   │   └── MarkdownDocUIExtra                      [Later]
│   │   ├── SubAgentTrace (嵌套 session 的消息流)          [MVP]
│   │   ├── NoticeEntry                                 [MVP]
│   │   ├── InterruptEntry                              [MVP]
│   │   ├── ErrorEntry                                  [MVP]
│   │   ├── CompactionEntry                             [Later]
│   │   └── RewindEntry                                 [Later]
│   │
│   ├── MessageOutline (左侧消息大纲)                     [Later]
│   │
│   ├── StatusBar                                       [MVP]
│   │   ├── ContextSize (进度条)                         [MVP]
│   │   ├── TokenCount & Cost                           [Later]
│   │   ├── ActiveSubAgents                             [Later]
│   │   └── ExecutionDuration                           [MVP]
│   │
│   └── InputArea                                       [MVP]
│       ├── TextInput (多行输入框)                        [MVP]
│       ├── ModelSelector (下拉)                         [MVP]
│       ├── ThinkingLevelSelector                       [MVP]
│       ├── SendButton / StopButton                     [MVP]
│       ├── CommandPalette                              [Later]
│       ├── FileCompletion                              [Later]
│       └── ImagePaste                                  [Later]
│
├── RightSidebar (工作区文件 diff)                        [Later, 独立设计]
│   ├── FileTree
│   └── FileDiff
│
└── TopBar                                              [Later]
    └── OpenVSCode 按钮
```

默认行为（MVP）：
- 页面首次进入时，默认进入“新 session 草稿页”（无 `session_id`）。
- 详情区默认展示该草稿页（而不是最近历史 session）。
- 左侧 `NewSessionButton` 点击后进入新的草稿页，不立即创建 session。
- 发送首条消息时才触发 `POST /api/sessions` 创建真实 session，并立刻发送该消息。

---

## 2. API 设计

Base path: `/api`

### 2.1 Session 管理

#### `GET /api/sessions`

列出所有 session（跨所有 project），按 `work_dir` 分组返回。

**Response:**
```json
{
  "groups": [
    {
      "work_dir": "/Users/xxx/code/project-a",
      "sessions": [
        {
          "id": "abc123...",
          "created_at": 1709500000.0,
          "updated_at": 1709500100.0,
          "work_dir": "/Users/xxx/code/project-a",
          "user_messages": ["help me refactor...", "now add tests"],
          "messages_count": 42,
          "model_name": "claude-sonnet-4-20250514"
        }
      ]
    }
  ]
}
```

数据来源：`Session.list_sessions()` -> `SessionMetaBrief`，前端按 `work_dir` 分组。

注意：
- 当前 `Session.list_sessions()` 依赖 `project_key_from_cwd()` 只返回当前 project 的 session。Web 模式下需要扫描所有 project（遍历 `~/.klaude/projects/*/sessions/`）。
- **过滤 sub-agent session**：sub-agent 会创建独立的 session 记录，但不应出现在侧边栏列表中。后端在返回列表时需过滤掉 `is_sub_agent=True` 的 session（通过 session 元数据中的 `sub_agent_state` 或 `parent_session_id` 判断）。

---

#### `POST /api/sessions`

创建新 session 并初始化 agent。

该端点有两个直接 UI 用途：
1. 左侧栏“新建 Session”按钮。
2. 新 session 草稿在发送首条消息时的懒创建。

**Request:**
```json
{
  "work_dir": "/Users/xxx/code/project-a"
}
```

`work_dir` 可选。省略时使用 server 启动时的 cwd。

**Response:**
```json
{
  "session_id": "new-uuid-hex"
}
```

后端动作：
1. 生成 `session_id`
2. `runtime.submit_and_wait(InitAgentOperation(session_id=...))`
3. 返回 `session_id`

---

#### `POST /api/sessions/{session_id}/resume`

恢复已有 session（加载历史并重新初始化 agent runtime）。

**Response:**
```json
{
  "session_id": "abc123..."
}
```

后端动作：`runtime.submit_and_wait(InitAgentOperation(session_id=existing_id))`

---

#### `DELETE /api/sessions/{session_id}`

关闭 session runtime（不删除磁盘数据）。

后端动作：`runtime.close_session(session_id, force=True)`

---

### 2.2 Session 数据

#### `GET /api/sessions/{session_id}/history`

获取 session 完整历史，以 replay 事件序列返回。用于首次加载和断线重连。

**Response:**
```json
{
  "session_id": "abc123...",
  "events": [
    {
      "event_type": "task.start",
      "session_id": "abc123...",
      "timestamp": 1709500000.0,
      "sub_agent_state": null,
      "model_id": null
    },
    {
      "event_type": "user.message",
      "session_id": "abc123...",
      "content": "help me refactor the auth module"
    },
    {
      "event_type": "thinking.start",
      "session_id": "abc123...",
      "response_id": "resp_1"
    }
  ]
}
```

数据来源：`Session.load(id)` -> `session.get_history_item()` 产生 `ReplayEventUnion` 序列。每个事件已经是 Pydantic 模型，直接序列化。

Sub-agent 的历史也在此序列中（通过 `_iter_sub_agent_history` 递归展开），前端根据 `session_id` 区分主/子 agent。

---

#### `GET /api/sessions/{session_id}/events`  (SSE)

实时事件流。返回 `text/event-stream`。

**SSE 格式：**
```
event: assistant.text.delta
id: 42
data: {"event_type":"assistant.text.delta","session_id":"abc123","content":"Hello"}

event: tool.call
id: 43
data: {"event_type":"tool.call","session_id":"abc123","tool_call_id":"tc_1","tool_name":"Bash","arguments":"{\"command\":\"ls\"}"}
```

每个 SSE event:
- `event` = `EventEnvelope.event_type` (前端按此分发)
- `id` = `EventEnvelope.event_seq` (断线重连锚点)
- `data` = `EventEnvelope` 的 JSON 序列化

后端动作：`event_bus.subscribe(session_id)` -> 异步迭代 -> yield `ServerSentEvent`

---

### 2.3 Session 交互

#### `POST /api/sessions/{session_id}/message`

发送用户消息。

**Request:**
```json
{
  "text": "help me refactor the auth module",
  "images": []
}
```

对应 `UserInputPayload`。

后端动作：
```python
runtime.submit(RunAgentOperation(
    session_id=session_id,
    input=UserInputPayload(text=..., images=...),
))
```

**Response:**
```json
{
  "operation_id": "op_xxx"
}
```

前端通过 SSE 接收执行过程中的所有事件。不需要轮询。

---

#### `POST /api/sessions/{session_id}/interrupt`

中断当前执行。

后端动作：`runtime.submit(InterruptOperation(session_id=...))`

**Response:** `204 No Content`

---

#### `POST /api/sessions/{session_id}/respond`

回复用户交互请求（AskUserQuestion / OperationSelect）。

**Request (AskUserQuestion):**
```json
{
  "request_id": "req_xxx",
  "status": "submitted",
  "payload": {
    "kind": "ask_user_question",
    "answers": [
      {
        "question_id": "q1",
        "selected_option_ids": ["opt_a"],
        "other_text": null
      }
    ]
  }
}
```

**Request (OperationSelect):**
```json
{
  "request_id": "req_xxx",
  "status": "submitted",
  "payload": {
    "kind": "operation_select",
    "selected_option_id": "opt_a"
  }
}
```

**Request (Cancel):**
```json
{
  "request_id": "req_xxx",
  "status": "cancelled",
  "payload": null
}
```

后端动作：
```python
runtime.submit(UserInteractionRespondOperation(
    session_id=session_id,
    request_id=request_id,
    response=UserInteractionResponse(status=..., payload=...),
))
```

---

#### `POST /api/sessions/{session_id}/continue`

从中断处继续执行（网络错误恢复等）。

后端动作：`runtime.submit(ContinueAgentOperation(session_id=...))`

---

### 2.4 配置

#### `POST /api/sessions/{session_id}/model`

切换模型。

**Request:**
```json
{
  "model_name": "claude-sonnet-4-20250514",
  "save_as_default": false
}
```

后端动作：`runtime.submit(ChangeModelOperation(...))`

---

#### `POST /api/sessions/{session_id}/thinking`

切换 thinking level。

**Request:**
```json
{
  "thinking": {
    "type": "enabled",
    "budget_tokens": 8192
  }
}
```

后端动作：`runtime.submit(ChangeThinkingOperation(...))`

---

#### `GET /api/config/models`

获取可用模型列表（从 config 读取）。

**Response:**
```json
{
  "models": [
    {
      "name": "claude-sonnet-4-20250514",
      "is_default": true
    }
  ]
}
```

---

## 3. 事件到组件的映射

前端根据 SSE event type 分发到对应组件进行渲染。

### 3.1 消息流渲染

| SSE event type | 前端组件 | 行为 |
|---|---|---|
| `user.message` | `UserMessage` | 渲染用户消息文本 + 图片 |
| `developer.message` | `DeveloperMessage` | 渲染系统提醒（根据 `ui_extra` 类型决定样式） |
| `thinking.start` | `ThinkingBlock` | 创建折叠的 thinking 容器 |
| `thinking.delta` | `ThinkingBlock` | 追加 thinking 文本（流式） |
| `thinking.end` | `ThinkingBlock` | 关闭 thinking 容器 |
| `assistant.text.start` | `AssistantText` | 创建 markdown 渲染容器 |
| `assistant.text.delta` | `AssistantText` | 追加文本（流式 markdown 渲染） |
| `assistant.text.end` | `AssistantText` | 完成渲染（触发 mermaid 等后处理） |
| `tool.call` | `ToolCall` | 显示工具名 + 参数（可折叠） |
| `tool.result` | `ToolResult` | 根据 `ui_extra.type` 分发到子组件渲染 |
| `interrupt` | `InterruptEntry` | 显示中断标记 |
| `error` | `ErrorEntry` | 显示错误信息 |
| `notice` | `NoticeEntry` | 显示通知 |
| `compaction.start/end` | `CompactionEntry` | 显示压缩信息 |
| `rewind` | `RewindEntry` | 显示回溯信息 |

### 3.2 内容区通用操作按钮

所有可渲染内容块右上角 hover 时显示操作按钮：

| 组件 | `[Raw]` 切换 | `[Copy]` |
|---|---|---|
| `AssistantText` | 切换 markdown 渲染 / raw markdown 源码 | 复制 markdown 源码 |
| `ThinkingBlock` | -- | 复制 thinking 文本 |
| `ToolCall` | 切换摘要视图 / `@uiw/react-json-view` 渲染 arguments JSON | 复制 arguments JSON |
| `ToolResult` | 切换 ui_extra 渲染 / `@uiw/react-json-view` 渲染 raw result + ui_extra | 复制 result 纯文本 |

按钮仅在 hover（桌面）或 tap 唤出 toolbar（移动端）时显示，不干扰阅读。

Raw JSON 模式使用 `@uiw/react-json-view`（`<JsonView>`）渲染，支持节点折叠/展开，默认展开第一层。

### 3.3 Sub-agent 渲染

Sub-agent 事件和主 agent 事件共享同一个 SSE 流。前端通过 `session_id` 区分归属。

#### 识别

- `task.start` 事件中 `sub_agent_state != null` -> 标记该 session_id 为 sub-agent
- 后续事件的 `session_id` 与主 session 不同 -> 归属该 sub-agent
- `task.finish` -> sub-agent 结束

#### ToolCall 阶段（父 agent 侧）

父 agent 调用 `Agent` 工具时，**不渲染为普通 ToolCall**，而是渲染为 sub-agent 启动卡片：

```
┌─ 🔀 Sub-agent: {type}
│  {description}
│  ─────────────
│  Prompt: {prompt 前 10 行，截断}
│  Output Schema: {output_schema 摘要}     [展开查看完整]
└─
```

#### Sub-agent 卡片

每个 sub-agent 渲染为独立卡片（不与父 agent 消息流交错），左侧带彩色竖线标识：

```
┌ 🔀 Researcher                              [折叠/展开]
│  "Search for the latest React 19 features"
│
│  [thinking] ...                                        <- 正常消息流
│  正在搜索相关文档...
│  $ WebSearch "React 19 features"
│  -> Read docs/react-19.md
│  根据搜索结果，React 19 包含以下特性...
│
│  ✓ 完成  1.2k tokens  3.4s
└
```

- 卡片内部就是一个完整的消息流（thinking、text、tool call/result），复用与主 agent 相同的渲染组件
- 左侧竖线颜色按 sub-agent 序号分配，区分多个并行 sub-agent
- 默认展开；可手动折叠，折叠后显示标题行 + 完成状态摘要
- 卡片底部显示结果：结构化输出用 `@uiw/react-json-view`，纯文本用 markdown，附 token 统计

#### 并行 sub-agent

TUI 中多个 sub-agent 的事件是交错展示的（终端限制）。Web 中每个 sub-agent 各自一个卡片，互不干扰：

- 按启动顺序排列在父 agent 消息流中
- 事件按 `session_id` 路由到对应卡片，各自独立滚动/更新
- 状态栏显示所有活跃 sub-agent 的摘要（类型 + 当前动作）

#### 递归嵌套

sub-agent 的 sub-agent：卡片内再嵌套卡片，递归同一个 `SubAgentCard` 组件。

### 3.4 用户交互

| SSE event type | 前端行为 |
|---|---|
| `user.interaction.request` | 根据 `payload.kind` 渲染交互 UI |
| -- `ask_user_question` | 渲染问题 + 选项列表（单选/多选）+ 自由输入 |
| -- `operation_select` | 渲染选项列表（单选） |
| `user.interaction.resolved` | 移除交互 UI，恢复正常流 |
| `user.interaction.cancelled` | 移除交互 UI，显示已取消 |

### 3.5 状态栏

| SSE event type | 前端组件 | 数据 |
|---|---|---|
| `usage` | `StatusBar` | `usage.context_size`, `usage.context_limit` -> 进度条 |
| `task.metadata` | `StatusBar` | `metadata.main_agent.task_duration_s` -> 执行时间 |
| `task.start` | `StatusBar` | 清空状态，开始计时 |
| `task.finish` | `StatusBar` | 停止计时 |
| `welcome` | `StatusBar` | `llm_config.model_id` -> 当前模型 |
| `model.changed` | `ModelSelector` | 更新当前选中模型 |
| `thinking.changed` | `ThinkingLevelSelector` | 更新当前 thinking 设置 |

---

## 4. ToolCall 渲染规则

`ToolCallEvent` 包含 `tool_name` 和 `arguments` (JSON string)。前端根据 `tool_name` 分发到不同的渲染逻辑。

参考 TUI 实现：`src/klaude_code/tui/components/tools.py`

### 4.1 通用结构

每个 ToolCall 渲染为统一的结构：

```
[mark] ToolName  details                          [Raw JSON] [Copy]
```

- `mark` -- 工具图标/符号
- `ToolName` -- 工具显示名（可能与 `tool_name` 不同）
- `details` -- 从 `arguments` JSON 中提取的摘要信息
- `[Raw JSON]` -- 切换按钮，显示/隐藏原始 `arguments` JSON（格式化缩进）
- `[Copy]` -- 复制原始 `arguments` JSON 到剪贴板

### 4.2 按工具分发

| `tool_name` | 显示名 | mark | details 提取逻辑 |
|---|---|---|---|
| `Bash` | Bash | `$` | `arguments.command` -- 语法高亮显示 |
| `Read` | Read | `->` | `arguments.file_path` + 可选行范围 `offset:limit` |
| `Edit` | Edit | `+-` | `arguments.file_path`；若 `replace_all=true` 则追加 old -> new 摘要 |
| `Write` | Write | `+` | `arguments.file_path` |
| `apply_patch` | Patch | `+-` | 解析 patch 内容统计：Edit x N, Create x N, Delete x N |
| `TodoWrite` | Update To-Dos | plan | (无 details) |
| `update_plan` | Plan | plan | `arguments.explanation` |
| `WebFetch` | Fetch Web | `->` | `arguments.url` (截断显示) |
| `WebSearch` | Search Web | `*` | `arguments.query` (截断显示) + 可选 max_results |
| `AskUserQuestion` | "Agent has N questions" | `?` | 从 `arguments.questions` 数组取 length |
| `report_back` | Report Back | check | (无 details) |
| `Rewind` | Rewind | undo | `Checkpoint {id}` + rationale 摘要 |
| `Agent` (sub-agent) | -- | -- | **不渲染**，sub-agent 工具调用在主流中隐藏 |
| 其他 | 原始 tool_name | generic | `key: value` 拼接所有参数 |

### 4.3 Generic fallback

未识别的工具名走通用渲染：

```
解析 arguments JSON:
- 空对象 -> 不显示 details
- 单个 key -> 显示 value
- 多个 key -> "key1: val1, key2: val2"
- 解析失败 -> 截断显示原始字符串 (max 200 chars)
```

### 4.4 Read 工具 details 示例

```
-> Read  src/main.py                    // 读整个文件
-> Read  src/main.py 10:50              // offset=10, limit=41
-> Read Skill  .claude/skills/.../SKILL.md  // SKILL.md 特殊高亮
```

### 4.5 Patch 工具 details 示例

```
+- Patch  Edit x 3, Create x 1
+- Patch  Edit x 1, Create README.md    // 单个 .md 文件显示文件名
```

---

## 5. ToolResult 渲染规则

`ToolResultEvent` 包含 `tool_name`, `result` (纯文本), `ui_extra` (可选的结构化数据), `status`。

渲染优先级：`ui_extra` > `result` 纯文本。

每个 ToolResult 右上角提供操作按钮：
- `[Raw]` -- 切换显示原始 `result` 纯文本 / `ui_extra` JSON
- `[Copy]` -- 复制 `result` 纯文本到剪贴板

### 5.1 按工具分发

| `tool_name` | 有 `ui_extra` 时的渲染 | 无 `ui_extra` / fallback |
|---|---|---|
| `Read` | `ReadPreviewUIExtra` -> 带行号的代码预览 | **不渲染**（成功时隐藏） |
| `Edit` | `DiffUIExtra` -> diff 视图 | 空内容 |
| `Write` | `DiffUIExtra` -> diff 视图；`MarkdownDocUIExtra` -> markdown 预览 | 空内容 |
| `apply_patch` | `DiffUIExtra` (含文件名)；`MarkdownDocUIExtra`；`MultiUIExtra` 组合 | 截断纯文本 |
| `TodoWrite` / `update_plan` | `TodoListUIExtra` -> checkbox 列表 | -- |
| `Bash` | -- | 截断纯文本（可折叠） |
| `WebFetch` | -- | 提取 `<<<EXTERNAL_UNTRUSTED_CONTENT>>>` 包裹的内容后截断显示 |
| `WebSearch` | -- | 同上 |
| `AskUserQuestion` | `AskUserQuestionSummaryUIExtra` -> Q&A 摘要 | 纯文本（不截断中间） |
| `Agent` (sub-agent) | -- | **不渲染**，sub-agent 结果在嵌套 trace 中显示 |
| 其他 | -- | 截断纯文本 |

### 5.2 错误结果

当 `status` 为 `error` 或 `aborted` 且无 `ui_extra` 时，以错误样式渲染 `result` 纯文本。

### 5.3 UIExtra 类型渲染

`ToolResultEvent.ui_extra` 是 discriminated union，前端根据 `type` 字段分发：

| `ui_extra.type` | 组件 | 渲染方式 |
|---|---|---|
| `diff` | `DiffView` (`@pierre/diffs`) | 文件级 diff：行号 + add/remove/ctx 着色 + 统计 (+N/-M) |
| `todo_list` | `TodoListView` | checkbox 列表，新完成项高亮 |
| `read_preview` | `ReadPreview` | 带行号的代码预览 + "more N lines" 提示 |
| `image` | `ImageView` | `<img>` 展示（需要文件服务端点） |
| `session_id` | `SubAgentLink` | 可点击跳转/展开 sub-agent session |
| `ask_user_question_summary` | `AskUserQuestionSummary` | 逐条 Q -> A 渲染，未回答项标黄 |
| `session_status` | `SessionStatusView` | token 统计表格 |
| `markdown_doc` | `MarkdownView` | markdown 渲染（带边框面板） |
| `multi` | 递归渲染 | 依次渲染 `items` 中的每个子 UIExtra |
| `null` | `PlainText` | 截断纯文本显示 `result` 字段（可折叠） |

### 5.4 DiffUIExtra 结构

```typescript
interface DiffUIExtra {
  type: "diff"
  files: Array<{
    file_path: string
    lines: Array<{
      kind: "ctx" | "add" | "remove" | "gap"
      new_line_no: number | null
      spans: Array<{ op: "equal" | "insert" | "delete", text: string }>
    }>
    stats_add: number
    stats_remove: number
  }>
  raw_unified_diff: string | null  // 可选的原始 diff 文本
}
```

渲染要点：
- 使用 `@pierre/diffs/react` 的 `<PatchDiff>` 或 `<FileDiff>` 组件
- 若 `raw_unified_diff` 存在，直接传入 `<PatchDiff patch={raw_unified_diff}>` 渲染
- 否则从 `files[].lines[]` 重建 unified diff 文本后传入
- 默认 `diffStyle: 'split'`（桌面），移动端切换为 `diffStyle: 'unified'`
- `lineDiffType: 'word-alt'` 启用 inline 字符级变更高亮
- `hunkSeparators: 'line-info'` 显示折叠区域
- `apply_patch` 工具的 diff 需要显示文件名（多文件 patch），使用 `<MultiFileDiff>` 处理

### 5.5 ReadPreviewUIExtra 结构

```typescript
interface ReadPreviewUIExtra {
  type: "read_preview"
  lines: Array<{ line_no: number, content: string }>
  remaining_lines: number  // 未显示的行数
}
```

渲染要点：
- 左侧固定宽度行号列
- 右侧代码内容（等宽字体）
- 底部 "more N lines" 灰色提示

### 5.6 TodoListUIExtra 结构

```typescript
interface TodoListUIExtra {
  type: "todo_list"
  todo_list: {
    todos: Array<{ content: string, status: "pending" | "in_progress" | "completed" }>
    new_completed: string[]  // 本次新完成的 todo content 列表
  }
}
```

渲染要点：
- `pending` -> 空心方框
- `in_progress` -> 实心圆
- `completed` -> 勾号，若 content 在 `new_completed` 中则绿色高亮
- 已完成项灰色删除线（新完成除外）

### 5.7 Generic 纯文本截断

对于无 `ui_extra` 的工具结果，截断规则：
- 显示前后各若干行，中间省略
- 可折叠展开查看完整内容
- 单行不换行，超宽截断显示

---

## 6. 前端状态模型概要

```
AppState
├── sessions: Map<session_id, SessionMeta>     // 侧边栏列表
├── activeSessionId: string | "draft" | null  // 当前查看的 session 或草稿
├── sessionStates: Map<session_id, SessionState>
│   └── SessionState
│       ├── messages: Message[]                // 已渲染的消息列表
│       ├── streamingText: string              // 当前流式文本缓冲
│       ├── streamingThinking: string          // 当前 thinking 缓冲
│       ├── pendingInteraction: InteractionRequest | null
│       ├── status: SessionStatus              // context size, duration, etc.
│       ├── isRunning: boolean
│       └── sseConnection: EventSource | null
├── config
│   ├── availableModels: Model[]
│   └── currentModel: string
└── ui
    ├── sidebarOpen: boolean
    └── thinkingExpanded: Map<response_id, boolean>
```

---

## 7. 数据加载流程

### 7.1 首次打开页面

```
1. GET /api/sessions           -> 填充侧边栏 session 列表
2. GET /api/config/models      -> 填充模型选择器
3. 初始化 active 为 `draft`，展示“新 session 草稿页”
4. 不调用 POST /api/sessions，不建立 SSE
```

### 7.2 发送消息

```
1. 若 active 为 `draft`：
   a. POST /api/sessions -> 获得 session_id
   b. 侧边栏插入新 session 卡片并设为 active
   c. 连接 GET /api/sessions/{id}/events (SSE)
2. POST /api/sessions/{id}/message  -> 获得 operation_id
3. 通过 SSE 接收事件流:
   operation.accepted -> (可选) 显示 loading
   turn.start -> 显示 spinner
   thinking.start/delta/end -> 渲染 thinking
   assistant.text.start/delta/end -> 流式渲染文本
   tool.call -> 显示工具调用
   tool.result -> 显示结果
   ... (多轮)
   operation.finished -> 结束 loading，恢复输入框
```

### 7.3 断线重连

```
1. SSE 断开 (网络抖动)
2. 浏览器 EventSource 自动重连 (带 Last-Event-ID)
3. 如果服务端无法从该 seq 恢复 (EventBus 无持久化):
   a. GET /api/sessions/{id}/history -> 重建完整状态
   b. 重新连接 SSE
```

### 7.4 创建新 session

```
1. 点击 `NewSessionButton`
2. 切换到新的 `draft` 详情态（可清空输入框与临时 UI 状态）
3. 用户发送首条消息时，按 7.2 的 draft 分支懒创建 session
```

---

## 8. 图片与文件服务

### 8.1 需要加载图片的场景

| 场景 | 数据来源 | 路径示例 |
|---|---|---|
| 工具生成的图片 | `ToolResultEvent.ui_extra` (`ImageUIExtra`) | `/tmp/generated.png` 或 session images 目录 |
| 用户消息中的图片 | `UserMessageEvent.images` (`ImageFilePart`) | `~/.klaude/projects/.../sessions/{id}/images/xxx.png` |
| Markdown 中的图片 | assistant text 中的 `![](path)` | 任意本地路径 |
| MarkdownDocUIExtra | `ui_extra.content` 中的 `![](path)` | 相对或绝对路径 |

### 8.2 API

#### `GET /api/files`

通用文件读取端点，返回文件内容（图片为 binary，带正确的 Content-Type）。

**Query Parameters:**
- `path` (required) -- 文件的绝对路径

**Response:**
- `200` -- 文件内容，Content-Type 根据扩展名推断（`image/png`, `image/jpeg`, `image/webp`, `image/svg+xml` 等）
- `403` -- 路径不在允许范围内
- `404` -- 文件不存在

**安全限制：**

只允许访问以下目录下的文件：
- `~/.klaude/projects/*/sessions/*/images/` -- session 图片存储
- server 启动时的 `work_dir` 及其子目录 -- 工作区内的文件
- `/tmp/` -- 临时文件（部分工具会写到这里）

拒绝所有其他路径。不允许 `..` 穿越。

### 8.3 前端使用

前端在渲染时将 `file_path` 转换为 API URL：

```typescript
function fileUrl(path: string): string {
  return `/api/files?path=${encodeURIComponent(path)}`
}
```

在以下组件中使用：
- `ImageView` (ToolResult): `<img src={fileUrl(ui_extra.file_path)} />`
- `UserMessage` (ImageFilePart): `<img src={fileUrl(part.file_path)} />`
- `AssistantText` (Markdown): streamdown 的 img 标签需要自定义 renderer，将 src 重写为 `fileUrl(src)`

---

## 9. Steer / Followup 输入队列 [Later]

MVP 中与 TUI 一致：agent 执行中不接受新输入，`POST /message` 在 session busy 时返回 `OperationRejectedEvent`。

后续迭代需要支持两种高级输入模式：

### 9.1 概念

**Steer 模式**：agent 执行过程中，用户消息立即插入当前对话上下文，干预 agent 行为方向。

**Followup 模式**：用户消息排队，等待当前 agent task 完成后自动作为下一条输入执行。

两种模式共享同一个 **Pending Input Queue**，区别在于消费时机：
- Steer -> 立即消费，中断当前 turn 并注入用户消息
- Followup -> 等待 `task.finish` 后按 FIFO 消费

### 9.2 前端组件

```
InputArea
├── PendingInputQueue                    [Later]
│   ├── PendingInputItem                 // 显示排队中的消息摘要
│   │   ├── 消息预览文本
│   │   └── 删除按钮 (x)                 // 用户可取消排队
│   └── ...
├── InputModeToggle                      [Later]
│   ├── Steer 模式 (闪电图标)
│   └── Followup 模式 (队列图标)
├── TextInput
└── SendButton / StopButton
```

- 输入框上方显示 pending 列表，每条可单独删除
- 模式切换影响新消息的提交行为，不影响已排队的消息
- 切换模式时不清空队列

### 9.3 API 预留

| 端点 | 说明 |
|---|---|
| `POST /api/sessions/{id}/message` | 扩展 request body 增加 `mode: "steer" \| "followup" \| "default"` |
| `DELETE /api/sessions/{id}/pending/{index}` | 取消排队中的某条消息 |
| `GET /api/sessions/{id}/pending` | 查询当前排队消息列表 |

### 9.4 核心层影响

当前 `SessionActor` 在 root-task 活跃时会 reject 新的 `RunAgentOperation`。Steer/Followup 需要：

- **Steer**: 新增 `SteerOperation` 类型，走 control preempt 路径（类似 `InterruptOperation`），将用户消息注入当前 task 上下文
- **Followup**: pending queue 可以纯前端实现（前端监听 `operation.finished` 后自动提交下一条），也可以在 `SessionActor` 中实现 operation queuing（已有 mailbox 机制）

前端 pending queue 方案更简单，且不需要核心层改动。

---

## 10. 前端技术栈

| 类别 | 选择 | 说明 |
|---|---|---|
| 框架 | **React** + TypeScript | 生态最大，LLM 生成代码最可靠 |
| 构建 | **Vite** | 快速 HMR，dev server 支持 proxy |
| 包管理 | **pnpm** | 快、磁盘高效、严格依赖解析 |
| 样式 | **Tailwind CSS** | utility-first，与 shadcn/ui 搭配 |
| 组件库 | **shadcn/ui** | copy-paste 组件，完全可定制（Sidebar, Dialog, ScrollArea 等） |
| Markdown 渲染 | **streamdown** (`streamdown`) | Vercel 出品，专为 AI 流式 markdown 设计。内置流式解析、unterminated block 处理 |
| 语法高亮 | **Shiki** (通过 `@streamdown/code`) | VS Code 引擎，streamdown 插件集成 |
| Mermaid | `@streamdown/mermaid` | streamdown 插件，代码块内渲染 |
| 状态管理 | **Zustand** | 极简 store，适合 SSE 事件流驱动 |
| JSON 查看 | **@uiw/react-json-view** | 可折叠 JSON 视图，用于 Raw JSON 模式 |
| Diff 渲染 | **@pierre/diffs** (`@pierre/diffs/react`) | 基于 Shiki 的 diff 组件，split/unified 视图、inline 变更高亮、patch 解析 |

### 目录结构

```
web/                          # 前端 SPA (Vite + React)
├── package.json
├── pnpm-lock.yaml
├── vite.config.ts            # dev proxy -> localhost:8765
├── tsconfig.json
├── tailwind.config.ts
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── api/                  # HTTP + SSE 客户端
│   ├── stores/               # Zustand stores
│   ├── components/
│   │   ├── sidebar/          # SessionList, ProjectGroup, SessionCard
│   │   ├── messages/         # MessageList, UserMessage, AssistantText, ToolCall, ToolResult, ...
│   │   ├── input/            # InputArea, ModelSelector, ThinkingSelector
│   │   ├── status/           # StatusBar, ContextSize
│   │   └── ui/               # shadcn/ui 组件
│   ├── lib/
│   │   └── event-handler.ts  # SSE 事件分发逻辑
│   └── types/                # TypeScript 类型 (从 Pydantic 模型对应)
└── public/
```

### 开发流程

```
# 默认（推荐）
klaude web                      # 自动拉起前后端并打开浏览器

# 分离调试（仅开发时可选）
cd web && pnpm dev              # Vite dev server :5173, proxy /api -> :8765
cd .. && klaude web --dev --no-open   # 仅启动后端 API，不接管前端 dev server

# 构建发布
cd web && pnpm build           # 输出到 web/dist/
# Python 包发布时将 web/dist/ 嵌入，由 Starlette StaticFiles 托管
```

---

## 11. 移动端适配

目标：同一套代码适配桌面和移动端，不做独立移动端设计。

### 布局断点

| 断点 | 宽度 | 布局 |
|---|---|---|
| mobile | `< 768px` | 侧边栏为抽屉（shadcn/ui Sidebar mobile 模式），消息流全宽 |
| desktop | `>= 768px` | 左侧边栏固定，消息流占剩余宽度 |

右侧文件 diff 工作区（Later）仅在 `>= 1280px` 时显示。

### 组件级适配要点

| 组件 | 桌面 | 移动 |
|---|---|---|
| `LeftSidebar` | 固定侧边栏 | Sheet 抽屉，点击汉堡按钮或左滑打开 |
| `MessageList` | 正常宽度 | 全宽，代码块水平滚动 |
| `ToolCall` | 单行 `[mark] Name details` | 同上，长 details 截断 |
| `ToolResult (diff)` | 并排行号 + 代码 | 行号窄化，代码水平滚动 |
| `ThinkingBlock` | 点击展开/折叠 | 同上（tap） |
| `InputArea` | 底部固定 | 底部固定，虚拟键盘弹起时跟随上移 |
| `StatusBar` | 信息完整显示 | 精简显示（仅 context % + 时间） |

### 实现策略

- **不需要两套组件**，全部用 Tailwind 响应式 class（`md:flex`, `hidden md:block` 等）
- **shadcn/ui Sidebar 已内置移动模式**，设置 `collapsible="offcanvas"` 即可
- **触摸交互**：展开/折叠用 tap，不依赖 hover 状态。所有 hover 样式加 `@media (hover: hover)` 限定
- **虚拟键盘**：InputArea 用 `position: sticky; bottom: 0` 或 `dvh` 单位处理键盘弹起

不需要额外的 API 或后端改动。

---

## 12. 暂不考虑的模块

以下模块在 MVP 阶段不实现，API 预留空间即可：

| 模块 | 原因 |
|---|---|
| Steer / Followup 输入队列 | 需要核心层支持 SteerOperation，见第 9 节 |
| 右侧文件 diff 工作区 | 独立且复杂，需要 git diff 集成 |
| 消息大纲 | 依赖折叠 steps，需要先实现 step 分组 |
| 导出 HTML | TUI 已有 `ExportSessionOperation`，可后续直接复用 |
| CommandPalette / Skills | 需要先设计 slash command 协议 |
| 文件补全 | 需要 server 端文件系统搜索 |
| 图片粘贴/拖入 | 需要上传 API |
| Token & Cost 详情 | `UsageEvent` 数据已有，仅需前端渲染 |
| 多 session tab | 前端路由调整 |
