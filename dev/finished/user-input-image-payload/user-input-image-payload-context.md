# User Input 文本+图片载体改造 - 背景与上下文

Last Updated: 2025-11-29 (Phase 1 Completed)

## 1. 目标与问题陈述

- 目标：
  - 将当前的 `user_input` 从单纯 `str` 扩展为包含文本和图片的结构化对象，贯穿 UI -> CLI -> Executor -> Agent -> Task -> 会话历史的整条链路。
  - 消除现有 `clipboard_manifest` + `clipboard_image_reminder` 通过文件系统中转图片的设计，改为在输入提交时直接附带图片。
- 现有问题：
  - 图片输入需要依赖文件 manifest 与提醒机制，链路复杂且不直观。
  - 用户在 UI 上看到的是 `[Image #N]` 文本，而不是明确的"这一轮消息包含哪些图片"。
  - 未来若扩展更多图片来源（拖拽、本地文件、HTTP URL 等），现有方案不易扩展。

## 2. 当前实现状态 (Phase 1 Completed)

### 2.1 已完成的改造

**Phase 1 已完成全部任务：**

1. **`UserInputPayload` 类型** - `src/klaude_code/protocol/model.py`
   - 新增 `UserInputPayload(BaseModel)` 类
   - 字段：`text: str`, `images: list[ImageURLPart] | None = None`
   - 位置：在 `ImageURLPart` 之后，`UserMessageItem` 之前

2. **`UserMessageEvent` 扩展** - `src/klaude_code/protocol/events.py`
   - 新增 `images: list[model.ImageURLPart] | None = None` 字段

3. **`UserInputOperation` 改造** - `src/klaude_code/protocol/op.py`
   - 将 `content: str` 改为 `input: UserInputPayload`
   - 添加了 `from klaude_code.protocol.model import UserInputPayload` 导入

4. **调用点更新** - `src/klaude_code/cli/runtime.py`
   - `run_exec`: 构造 `UserInputPayload(text=input_content)`
   - `run_interactive`: 构造 `UserInputPayload(text=user_input)`

5. **Executor 适配** - `src/klaude_code/core/executor.py`
   - `handle_user_input` 使用 `operation.input` 获取 `UserInputPayload`
   - `UserMessageEvent` 发送时附带 `images`
   - 历史追加时使用 `UserMessageItem(content=..., images=...)`

### 2.2 验证状态
- pyright 类型检查：0 errors, 0 warnings
- pytest 测试：133 passed

## 3. 相关核心文件与职责

### 已修改的文件
- `src/klaude_code/protocol/model.py` - 新增 UserInputPayload
- `src/klaude_code/protocol/events.py` - UserMessageEvent 增加 images
- `src/klaude_code/protocol/op.py` - UserInputOperation 使用 UserInputPayload
- `src/klaude_code/cli/runtime.py` - 调用点更新
- `src/klaude_code/core/executor.py` - handle_user_input 适配

### 待修改的文件 (Phase 2+)
- `src/klaude_code/core/agent.py` - Agent.run_task 签名
- `src/klaude_code/core/task.py` - TaskExecutor.run 签名
- `src/klaude_code/ui/core/input.py` - InputProviderABC.iter_inputs 类型
- `src/klaude_code/ui/modes/repl/input_prompt_toolkit.py` - ClipboardCaptureState 改造
- `src/klaude_code/core/reminders.py` - 删除 clipboard_image_reminder
- `src/klaude_code/core/clipboard_manifest.py` - 待删除

## 4. 关键设计决策

1. **一次性切换**：核心链路统一使用 `UserInputPayload`，不保留 `str` 版本的内部 API
2. **图片透传**：图片从 UI 层直接附带在 payload 中，不再通过 manifest 文件中转
3. **命令系统兼容**：`dispatch_command` 仍只处理文本部分 (`user_input.text`)，命令返回的 `agent_input` 也是 `str`
4. **渐进式改造**：Phase 2 会将 `_run_agent_task` / `Agent.run_task` / `TaskExecutor.run` 全部改为接受 `UserInputPayload`

## 5. 当前已知问题

1. **图片在命令链路中可能丢失**：当前 `dispatch_command` 返回 `agent_input: str`，如果命令修改了输入内容，图片信息需要从原始 `UserInputPayload` 中恢复。这将在 Phase 2 解决。

2. **Sub-agent 任务**：`_run_subagent_task` 中调用 `child_agent.run_task(state.sub_agent_prompt)` 目前传递 `str`，需要在 Phase 2 更新。

## 6. 下一步工作 (Phase 2)

Phase 2 的核心任务是将 `UserInputPayload` 透传到 Agent 和 Task 层：

1. **修改 `_run_agent_task`** 签名，接受 `UserInputPayload` 而非 `str`
2. **修改 `Agent.run_task`** 签名，统一接受 `UserInputPayload`
3. **修改 `TaskExecutor.run`** 签名，写入历史时使用完整的 payload
4. **处理命令链路**：当 `dispatch_command` 返回 `agent_input` 时，需要构造新的 `UserInputPayload`，保留原始图片

## 7. 开发指南

### 验证命令
```bash
cd /Users/bytedance/code/klaude-code
uv run pyright           # 类型检查
uv run pytest -x         # 运行测试
```

### 代码风格
- 使用 `text` 而非 `content` 作为 `UserInputPayload` 的文本字段名（与 `UserMessageItem.content` 区分）
- 图片字段统一使用 `images: list[ImageURLPart] | None`

## 8. 后续文档与任务追踪

- 本文件：记录背景、关键文件与设计约束，供所有参与者快速建立上下文。
- `user-input-image-payload-plan.md`：包含完整的实施方案、阶段划分、风险与度量指标。
- `user-input-image-payload-tasks.md`：以 checklist 形式跟踪每个任务的完成情况，方便日常推进与复盘。
