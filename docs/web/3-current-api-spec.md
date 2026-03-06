# Web API Spec（当前实现）

> 状态：implementation-driven（以代码实现为准）  
> 范围：`src/klaude_code/web/` 当前后端实现  
> 更新时间：2026-03

---

## 1. 总览

- 协议：
  - REST：`/api/*`
  - WebSocket：`/api/sessions/{session_id}/ws`
- 编码：JSON（UTF-8）
- 认证：当前实现无鉴权
- CORS：允许所有 origin/method/header（`allow_origins=["*"]`）

---

## 2. REST API

## `GET /api/sessions`

列出可见会话，按 `work_dir` 分组。

- 过滤规则：
  - 过滤子代理会话（`sub_agent_state != null`）
  - 过滤软删除会话（`deleted_at != null`）
- 返回结构：

```json
{
  "groups": [
    {
      "work_dir": "/path/to/project",
      "sessions": [
        {
          "id": "session_id",
          "created_at": 1772611275.0,
          "updated_at": 1772611276.0,
          "work_dir": "/path/to/project",
          "user_messages": ["hello"],
          "messages_count": 3,
          "model_name": "claude-sonnet-4-20250514",
          "session_state": "running"
        }
      ]
    }
  ]
}
```

- `session_state` 取值：
  - `idle`
  - `running`
  - `waiting_user_input`

---

## `POST /api/sessions`

创建会话并初始化 runtime actor。

- 请求体：

```json
{
  "work_dir": "/abs/or/relative/path"
}
```

`work_dir` 可选；省略时使用 server 启动时工作目录。

- 成功响应：

```json
{
  "session_id": "hex_id"
}
```

- 状态码：
  - `200` 成功
  - `400` `work_dir` 不存在或不是目录
  - `500` 初始化失败

---

## `DELETE /api/sessions/{session_id}`

软删除会话（写入 `deleted_at`），并尝试关闭内存中的 session actor。

- 成功响应：

```json
{
  "ok": true
}
```

- 状态码：
  - `200` 成功
  - `404` 会话不存在

---

## `GET /api/sessions/{session_id}/history`

读取会话历史并转换为回放事件。

- 成功响应：

```json
{
  "session_id": "session_id",
  "events": [
    {
      "event_type": "task.start",
      "event": {
        "session_id": "session_id",
        "timestamp": 1772611275.0
      }
    }
  ]
}
```

- 状态码：
  - `200` 成功
  - `404` 会话不存在
  - `500` 会话加载失败

---

## `POST /api/sessions/{session_id}/message`

提交消息操作（异步），返回 `operation_id`。

- 请求体：

```json
{
  "text": "hello",
  "images": [
    { "type": "image_url", "url": "https://example.com/a.png" },
    { "type": "image_file", "file_path": "/tmp/a.png" }
  ]
}
```

- 成功响应：

```json
{ "operation_id": "op_id" }
```

- 状态码：
  - `200` 成功
  - `404` 会话不存在

---

## `POST /api/sessions/{session_id}/interrupt`

提交中断操作（异步）。

- 成功响应：

```json
{ "operation_id": "op_id" }
```

---

## `POST /api/sessions/{session_id}/respond`

提交交互响应（异步）。

- 请求体：

```json
{
  "request_id": "req_id",
  "status": "submitted",
  "payload": {
    "kind": "ask_user_question",
    "answers": [
      {
        "question_id": "q1",
        "selected_option_ids": ["q1_o1"]
      }
    ]
  }
}
```

`status` 可选值：`submitted` / `cancelled`。

- 成功响应：

```json
{ "ok": true }
```

---

## `POST /api/sessions/{session_id}/model`

提交模型切换操作（异步）。

- 请求体：

```json
{
  "model_name": "sonnet@anthropic",
  "save_as_default": false
}
```

- 成功响应：

```json
{ "operation_id": "op_id" }
```

---

## `GET /api/config/models`

返回模型列表（当前实现会过滤 disabled 项）。

- 成功响应：

```json
{
  "models": [
    {
      "name": "sonnet@anthropic",
      "is_default": true
    }
  ]
}
```

---

## `GET /api/files?path=...`

读取本地文件内容（`FileResponse`）。

- 访问白名单：
  - `work_dir` 内
  - `/tmp` 内
  - `~/.klaude/projects/*/sessions/*/images` 内
- 拒绝规则：
  - 路径非绝对：`400`
  - 路径包含 `..` 或越权：`403`
  - 文件不存在或非文件：`404`

---

## 3. WebSocket API

## `WS /api/sessions/{session_id}/ws`

会话级实时双向通道。

### 连接握手

成功连接后，服务端第一条消息为：

```json
{
  "event_type": "usage.snapshot",
  "session_id": "session_id",
  "event": {
    "usage": {
      "input_tokens": 0,
      "output_tokens": 0
    }
  },
  "timestamp": 1772611275.0
}
```

### 客户端 -> 服务端消息

#### 1) 发送消息

```json
{
  "type": "message",
  "text": "hello",
  "images": [{ "type": "image_url", "url": "https://example.com/a.png" }]
}
```

#### 2) 中断

```json
{ "type": "interrupt" }
```

#### 3) 交互回复

```json
{
  "type": "respond",
  "request_id": "req_id",
  "status": "submitted",
  "payload": { "kind": "operation_select", "selected_option_id": "opt1" }
}
```

#### 4) 继续执行

```json
{ "type": "continue" }
```

#### 5) 切模型

```json
{
  "type": "model",
  "model_name": "sonnet@anthropic",
  "save_as_default": false
}
```

#### 6) 切 thinking

```json
{
  "type": "thinking",
  "thinking": {
    "type": "enabled",
    "budget_tokens": 2048
  }
}
```

---

### 服务端 -> 客户端消息

#### A. `usage.snapshot`（握手）

见上。

#### B. EventEnvelope（事件流）

服务端会持续推送 runtime 事件 envelope：

```json
{
  "event_id": "evt_id",
  "event_seq": 10,
  "session_id": "session_id",
  "operation_id": "op_id",
  "task_id": "task_id",
  "causation_id": null,
  "event_type": "assistant.text.delta",
  "durability": "ephemeral",
  "timestamp": 1772611276.0,
  "event": {
    "session_id": "session_id",
    "timestamp": 1772611276.0,
    "content": "hello"
  }
}
```

`durability` 取值：`durable` / `ephemeral`。

#### C. 错误帧

```json
{
  "type": "error",
  "code": "invalid_payload",
  "message": "Invalid payload",
  "detail": []
}
```

---

### WebSocket 错误码与关闭行为

- `session_not_found`：会话不存在（随后关闭，code `4004`）
- `session_init_failed`：初始化失败（随后关闭，code `4005`）
- `invalid_message`：消息不是合法 JSON / 结构错误（不断开）
- `unknown_type`：`type` 不支持（不断开）
- `invalid_payload`：字段校验或操作执行失败（不断开）

---

## 4. 与历史设计稿差异（当前实现）

- 当前实现 **不提供** `GET /api/sessions/{id}/events`（SSE）。
- 实时通道统一为 `WS /api/sessions/{id}/ws`。
- 历史回放接口 `GET /api/sessions/{id}/history` 返回 `{event_type, event}` 列表，而非 EventEnvelope。
