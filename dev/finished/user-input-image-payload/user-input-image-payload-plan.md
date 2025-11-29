# User Input 文本+图片载体改造计划

Last Updated: 2025-11-29

## 1. Executive Summary

- 目标：将当前从 UI → CLI → Executor → Agent → Task 的 `user_input` 类型，从单一 `str` 升级为“文本+图片”的结构化对象（下文暂命名为 `UserInputPayload`），从而支持多模输入，并消除通过 `clipboard_manifest`+提醒链路绕文件系统中转图片的机制。
- 核心思路：
  - 在协议层（`protocol/model.py`、`protocol/events.py`）引入统一的 user input 载体类型，包含 `text: str` 与 `images: list[ImageURLPart] | None`。
  - 在执行链路（`op.UserInputOperation` → `ExecutorContext.handle_user_input` → `Agent.run_task` → `TaskExecutor.run`）中全程传递 `UserInputPayload`，会话历史中用已有的 `UserMessageItem(content, images)` 持久化文本+图片。
  - 在 UI 输入层（`InputProviderABC` 和 REPL 实现）将当前“剪贴板图片 → 文件 → manifest → reminder → DeveloperMessageItem.images”改为“剪贴板图片在提交时直接转为 `ImageURLPart`，随 `UserInputPayload` 一并送入 Executor”。
  - 一次性在核心链路中切换到 `UserInputPayload`（不再保留 `str` 版本的内部 API），REPL 和 CLI 统一依赖该抽象，并在改造完成后彻底移除 `clipboard_manifest` 和 `clipboard_image_reminder`。
- 业务/产品收益：
  - 降低图片输入路径的复杂度与脆弱性（不再依赖磁盘 manifest 与进程 token 对齐）。
  - 更接近上游多模 LLM API 的数据模型，便于未来扩展（拖拽图片、内嵌截图、文件上传等）。
  - 提高可测试性（`UserInputPayload` 可在单元测试中直接构造，无需依赖系统剪贴板与文件系统）。

## 2. Current State Analysis

### 2.1 用户输入链路（文本）

- UI 抽象：
  - `src/klaude_code/ui/core/input.py`
    - `InputProviderABC.iter_inputs(self) -> AsyncIterator[str]`
    - 当前约定 user input 为纯文本 `str`。
- CLI 入口：
  - `src/klaude_code/cli/runtime.py`
    - 非交互模式：
      - `run_exec(init_config, input_content: str)` 直接构造 `op.UserInputOperation(content=input_content, session_id=...)` 提交给 `Executor`。
    - 交互 REPL：
      - 通过 `ui.PromptToolkitInput` 实现 `InputProviderABC`，`async for user_input in input_provider.iter_inputs():`，user_input 为 `str`。
      - 每次输入：
        - 处理 `exit` / `:q` / 空行等特殊指令。
        - 调用 `executor.submit(op.UserInputOperation(content=user_input, session_id=session_id))`。
- Executor 层：
  - `src/klaude_code/core/executor.py`
    - `UserInputOperation` 在 `protocol/op.py` 中定义，字段：`content: str`、`session_id: str | None`。
    - `ExecutorContext.handle_user_input(operation: op.UserInputOperation)`：
      - 校验 `session_id`，必要时调用 `handle_init_agent` 创建 `Agent`。
      - 发出 `events.UserMessageEvent(content=operation.content, session_id=...)`。
      - `dispatch_command(operation.content, agent)` 处理斜杠命令等：
        - 若 `result.agent_input` 为空：认为是纯命令，直接 `agent.session.append_history([UserMessageItem(content=operation.content)])`。
        - 若 `result.agent_input` 非空：启动 `_run_agent_task(agent, result.agent_input, ...)` 异步任务。
    - `_run_agent_task(agent, user_input: str, ...)`：
      - `async for event in agent.run_task(user_input): await emit_event(event)`。
- Agent / Task 层：
  - `src/klaude_code/core/agent.py`
    - `Agent.run_task(self, user_input: str)`：
      - 构造 `TaskExecutionContext`（包含 session、profile、tool registry、reminders 等）。
      - 创建 `TaskExecutor(context)` 并调用 `task.run(user_input)`，将事件流转发给 UI。
  - `src/klaude_code/core/task.py`
    - `TaskExecutor.run(self, user_input: str)`：
      - 先发 `TaskStartEvent`。
      - `ctx.append_history([UserMessageItem(content=user_input)])` 将用户输入加入会话历史（目前只存文本）。
      - 循环处理多个 Turn：
        - 每个 Turn 前遍历 `profile.reminders`，调用 `process_reminder`，将 `DeveloperMessageEvent` 注入 UI 与历史。
        - 调用 `TurnExecutor.run()`，处理 LLM / tools 调用，累积 `ResponseMetadata`。
      - 结束时写入 `ResponseMetadataItem` 到会话，并发出 `TaskFinishEvent(task_result=最后一条 Assistant 消息内容)`。

### 2.2 图片输入当前链路（clipboard_manifest + reminder）

- REPL UI 捕获剪贴板图片：
  - `src/klaude_code/ui/modes/repl/input_prompt_toolkit.py`
    - `ClipboardCaptureState`：
      - `capture_from_clipboard()`：
        - 调用 `ImageGrab.grabclipboard()` 拿到图片。
        - 将图片保存为 `~/.klaude/clipboard/images/clipboard_xxxxx.png`。
        - 生成 tag：`"[Image #N]"`，记入 `_pending: list[ClipboardManifestEntry]`。
      - `flush_manifest()`：将 `_pending` 转为 `ClipboardManifest(entries, created_at_ts, source_id)` 并清空缓存。
    - 键位：
      - `Ctrl+V`：调用 `_clipboard_state.capture_from_clipboard()`，在输入框插入 tag，例如 `[Image #1]`。
      - `Enter`：
        - 若输入非空，调用 `_clipboard_state.flush_manifest()`；若返回非 None，调用 `persist_clipboard_manifest(manifest)` 存到 `~/.klaude/clipboard/manifests/manifest-*.json`。
        - 然后 `buf.validate_and_handle()` 提交文本到 `InputProvider`，作为纯 `str`。
- Reminders 侧利用 manifest：
  - `src/klaude_code/core/clipboard_manifest.py`：
    - `persist_clipboard_manifest` / `load_latest_clipboard_manifest` 基于文件系统读写 manifest。
  - `src/klaude_code/core/reminders.py`：
    - `clipboard_image_reminder(session)`：
      - `get_last_new_user_input(session)` 获取最近一条 `UserMessageItem`+`DeveloperMessageItem` 文本，若包含 `[Image #N]` 才继续。
      - `load_latest_clipboard_manifest()` 读最新 manifest，并检查 `source_id == next_session_token()`（当前进程 token），否则忽略，防止跨进程污染。
      - 根据 manifest 的 `tag_map()`（tag → path），使用 `ReadTool` 读取图片路径，得到 `tool_result.images: list[ImageURLPart]`。
      - 汇总所有图片为 `collected_images`，返回 `DeveloperMessageItem(content="", images=collected_images, clipboard_images=[tags...])`。
    - 在 `ALL_REMINDERS` 中注册，且在 `load_agent_reminders` 中默认开启。
- 整体行为：
  - 用户在 REPL 输入框中看到 tag 文本 `[Image #1]` 等，但真正的图片对象通过 reminder 延迟注入为 developer message，并不直接挂在该轮 `UserMessageItem` 上；模型侧仍能接受图片（通过 `DeveloperMessageItem.images`）。
  - 存在跨组件复杂耦合：REPL → clipboard_manifest 文件 → reminder → ReadTool → DeveloperMessageItem.images → 会话历史。

### 2.3 现状问题

- 技术复杂度：图片输入依赖磁盘 manifest 文件、进程 token、正则解析 tag、多次 IO 与工具调用，链路长且容易出错。
- 语义割裂：图片并不直接附着在该轮 `UserMessageItem` 上，而是以 `DeveloperMessageItem(images=...)` 的形式出现，与“用户发了一条文本+图片消息”的自然语义不一致。
- 自动化测试难：需要构造 manifest 文件、伪造 clipboard 状态以及工具结果，才能验证逻辑。
- 扩展受限：若未来支持非 clipboard 图片（例如命令行传入文件 path、UI 拖拽图片），现有链路会变得更难维护。

## 3. Proposed Future State

### 3.1 新的 user_input 抽象：UserInputPayload

- 引入统一的数据结构 `UserInputPayload`（命名暂定，即为最终实现）：
  - 位置已确定：`src/klaude_code/protocol/model.py`，紧邻 `UserMessageItem` / `ImageURLPart`。
  - 字段示例：
    - `text: str`：用户可见文本内容（包括命令、普通对话文本等）。
    - `images: list[ImageURLPart] | None = None`：当前轮附带的图片列表。
    - （可选）`source: Literal["repl", "exec", "api"] | None`：来源标记，仅用于调试或统计。
- 语义：
  - 表示“某一轮用户输入”的完整载体，而不是仅仅视为字符串。
  - 在整个 executor → agent → task 链路中保持一致传递，直到被转换为会话历史中的 `UserMessageItem`，并交给 LLM 客户端进行多模请求构造。

### 3.2 协议与操作层改造

- `protocol/op.py` 中的 `UserInputOperation`：
  - 现状：`content: str`。
  - 未来：
    - 将 `content: str` 改为 `input: model.UserInputPayload`，由调用方统一构造 payload 后提交。
- `protocol/events.py` 中的 `UserMessageEvent`：
  - 现状：`session_id: str`, `content: str`。
  - 未来：
    - 增加 `images: list[model.ImageURLPart] | None = None` 字段，使 UI 层可以感知并渲染用户发送的图片。
    - 根据 UI 实现情况，可以先仅存储、不渲染。

### 3.3 Executor / Agent / Task 链路改造

- Executor：
  - `ExecutorContext.handle_user_input`：
    - 从 `operation.input` 直接获取 `input_payload: UserInputPayload`。
    - 发出 `UserMessageEvent(session_id, content=input_payload.text, images=input_payload.images)` 到 UI。
    - `dispatch_command(input_payload.text, agent)`：命令系统只处理文本部分。
    - 若 `result.agent_input` 为假：直接 `UserMessageItem(content=input_payload.text, images=input_payload.images)` 写入会话（保证图片也进入历史）。
    - 若 `result.agent_input` 为真：
      - 将 `input_payload` 传递给 `_run_agent_task(agent, input_payload, ...)`。
  - `_run_agent_task`：
    - 函数签名改为 `async def _run_agent_task(self, agent: Agent, user_input: UserInputPayload, ...)`。
    - 调用 `agent.run_task(user_input)`，内部逻辑只处理 `UserInputPayload`。
- Agent：
  - `Agent.run_task(self, user_input: UserInputPayload)`：
    - 始终接收 payload，不再支持 `str` 版本。
    - 将 `UserInputPayload` 放入 `TaskExecutionContext`（新增字段或透传），由 `TaskExecutor.run` 使用。
- Task：
  - `TaskExecutor.run(self, user_input: UserInputPayload)`：
    - 写入历史时：
      - `ctx.append_history([UserMessageItem(content=user_input.text, images=user_input.images)])`。
    - 其他逻辑保持不变（reminders、turn 重试、metadata 累积）。
  - Reminders：
    - 不再需要从 `session.conversation_history` 的最近文本中解析 `[Image #N]`；未来可以根据 `UserMessageItem.images` 判断是否已有图片，来决定是否追加额外提示。

### 3.4 UI 输入层改造（REPL 为重点）

- 修改 `InputProviderABC`：
  - 从 `iter_inputs(self) -> AsyncIterator[str]` 调整为 `iter_inputs(self) -> AsyncIterator[UserInputPayload]`，所有上游逻辑统一使用 payload，不再支持 `str` 版本。
- REPL 实现（`PromptToolkitInput`）改造：
  - 当前：
    - `ClipboardCaptureState` 持有 `ClipboardManifestEntry` 列表；`Enter` 时 `flush_manifest()` + `persist_clipboard_manifest`；`iter_inputs` 只返回文本。
  - 未来：
    - 将 `ClipboardCaptureState` 的内部状态改为只存“当前 session 的图片文件路径列表 + 对应 tag”，不再写入 manifest。
    - 在用户按下 `Enter` 且输入非空时：
      - 从 `ClipboardCaptureState` 提取当前待提交的图片路径列表，以及与 `[Image #N]` tag 的映射关系。
      - 解析当前 buffer 文本中的 `[Image #N]` 提示，确定本轮要附带的图片集合。
      - 直接构造 `ImageURLPart` 列表（与 `ReadTool` 里处理图片的逻辑复用或共用 helper）。
      - 将文本内容与图片列表打包成 `UserInputPayload`，从 `iter_inputs` 中 yield。
      - 之后清空本次输入已使用的图片状态。
    - 键位行为保持不变：`Ctrl+V` 继续插入 `[Image #N]` 文本到输入框，用于终端环境中的视觉提示；UI 不直接展示图片内容。
  - 这样 REPL → Executor 的输入从一开始就是“文本+图片”的结构化对象。

### 3.5 reminders / clipboard_manifest 清理

- 目标状态：
  - 在新的 `UserInputPayload` 链路生效后，完全删除 `clipboard_image_reminder` 以及 `clipboard_manifest.py`（连同相关 tests），不再保留任何基于 manifest 的图片注入路径。
  - 旧会话中依赖 manifest 的行为将不再被支持，统一迁移到“图片随 user message 透传”的模型。

### 3.6 对现有行为的兼容策略

- CLI 非交互模式：
  - `run_exec` 仍然只接受 `input_content: str`。
  - 实现上统一在 CLI 层构造 `UserInputPayload(text=input_content, images=None)`，提交给 executor。
- 图片提醒链路：
  - 新链路中不再依赖 `clipboard_image_reminder` 提供图片，所有图片都通过 `UserInputPayload.images` 透传到会话历史和 LLM 输入。

## 4. Implementation Phases

### Phase 0：设计与对齐

- 目标：冻结 `UserInputPayload` 的结构（位于 `protocol/model.py`）以及一次性切换方案；达成对链路改造范围的共识。

### Phase 1：协议与核心模型改造

- 在 `protocol/model.py` 中新增 `UserInputPayload` 类型。
- 在 `protocol/events.py` 中扩展 `UserMessageEvent` 支持 `images`。
- 在 `protocol/op.py` 中扩展 `UserInputOperation` 支持图片字段（或整个 payload）。

### Phase 2：Executor / Agent / Task 链路适配

- 调整 `ExecutorContext.handle_user_input`、`_run_agent_task`、`Agent.run_task`、`TaskExecutor.run`，统一改为接受与传递 `UserInputPayload`。
- 确保会话历史中的 `UserMessageItem` 能正确挂载图片。

### Phase 3：UI 输入层（REPL）改造

- 调整 `InputProviderABC` 接口类型。
- 更新 `PromptToolkitInput` 实现：取消 manifest 写入，改为直接构造 `UserInputPayload`。
- 确认 CLI `run_interactive` 与其他 UI 模式适配新的 interface。

### Phase 4：reminders 与 clipboard_manifest 清理

- 在新链路稳定后，删除 `clipboard_image_reminder`、`clipboard_manifest.py` 及其相关测试和引用，确保代码库中不再存在基于 manifest 的图片注入逻辑。

### Phase 5：回归测试与优化

- 完整覆盖：
  - REPL 文本输入。
  - REPL 剪贴板图片输入（多张、重复粘贴、未引用等）。
  - 非交互 exec 模式。
  - 带图片的上下文回放和多轮对话。
- 观察日志与 trace，确保无新的异常和性能退化。

## 5. Detailed Tasks

以下任务按阶段划分，每个任务包含：描述、依赖、验收标准、估算（S/M/L/XL）。

### Phase 0：设计与对齐

1. 明确 UserInputPayload 的字段
   - 描述：确认 `UserInputPayload` 在 `protocol/model.py` 中的字段设计（至少包含 `text` 与 `images`），评估是否需要额外字段（如 `source`）。
   - 依赖：现有多模消息模型（`ImageURLPart`、`UserMessageItem.images`）。
   - 验收标准：
     - 有简短设计文档（本 plan 即基础）+ 统一命名约定。
     - 获得主要维护者确认。
   - 估算：S。

### Phase 1：协议与核心模型改造

2. 新增 UserInputPayload 类型
   - 描述：在 `protocol/model.py` 中添加 `class UserInputPayload(BaseModel)`，包含 `text` 与 `images`。
   - 依赖：任务 1。
   - 验收标准：
     - `UserInputPayload` 被成功 import 到预期模块，无循环依赖。
     - Pyright 通过；基础单元测试可构造该类型实例。
   - 估算：S。

3. 扩展 UserMessageEvent 支持 images
   - 描述：在 `protocol/events.py` 中为 `UserMessageEvent` 增加 `images` 字段，默认 None。
   - 依赖：任务 2。
   - 验收标准：
     - 所有创建 `UserMessageEvent` 的调用点更新完毕。
     - UI 显示层（如 REPL display）在未处理 `images` 时仍能正常工作。
   - 估算：S。

4. 更新 UserInputOperation 使用 UserInputPayload
   - 描述：在 `protocol/op.py` 中将 `UserInputOperation` 的字段从 `content: str` 改为 `input: UserInputPayload`，由调用方统一构造 payload。
   - 依赖：任务 2。
   - 验收标准：
     - 所有构造 `UserInputOperation` 的位置（`run_exec`、`run_interactive` 等）编译通过。
     - 未提供图片时行为与现有完全一致（`images=None`）。
   - 估算：S。

### Phase 2：Executor / Agent / Task 链路适配

5. ExecutorContext.handle_user_input 适配 UserInputPayload
   - 描述：
     - 在 `handle_user_input` 中使用 `operation.input: UserInputPayload` 作为唯一来源。
     - 发出 `UserMessageEvent` 时同时传递 `images`。
     - 记录历史时使用 `UserMessageItem(content=text, images=images)`。
   - 依赖：任务 2、3、4。
   - 验收标准：
     - 纯文本输入行为无变化。
     - 带图片的 `UserInputOperation` 能正确把图片进入会话历史（通过单元测试或集成测试验证）。
   - 估算：M。

6. 调整 _run_agent_task 与 Agent.run_task 签名
   - 描述：
     - `_run_agent_task` 改为接收 `UserInputPayload`。
     - `Agent.run_task(self, user_input: UserInputPayload)`，仅支持 payload 版本。
   - 依赖：任务 2、5。
   - 验收标准：
     - 所有调用 `Agent.run_task` 的地方已适配。
     - Pyright 通过，无类型报错。
   - 估算：M。

7. TaskExecutor.run 使用 UserInputPayload 写入历史
   - 描述：
     - `TaskExecutor.run` 接收 `UserInputPayload`。
     - 使用 `UserMessageItem(content=user_input.text, images=user_input.images)` 追加历史。
   - 依赖：任务 2、6。
   - 验收标准：
     - 纯文本任务与带图片任务都能正常执行、结束，并产生正确的 `TaskFinishEvent`。
   - 估算：M。

### Phase 3：UI 输入层（REPL）改造

8. 修改 InputProviderABC 的 iter_inputs 类型
   - 描述：
     - 将 `InputProviderABC.iter_inputs` 的返回类型改为 `AsyncIterator[UserInputPayload]`（或新定义的等价类型）。
     - 检查所有 InputProvider 实现（目前主要是 `PromptToolkitInput`）。
   - 依赖：任务 2、6、7。
   - 验收标准：
     - 所有实现类在类型检查与运行时都正常。
     - CLI `run_interactive` 等使用处已更新为 `async for user_input in iter_inputs():` 且 user_input 为 payload。
   - 估算：M。

9. PromptToolkitInput 改造为直接输出 UserInputPayload
   - 描述：
     - 调整 `ClipboardCaptureState`，不再依赖 `ClipboardManifestEntry` 与 `persist_clipboard_manifest`。
     - 在 `Enter` 处理逻辑中：
       - 读取当前缓冲区文本。
       - 从 `ClipboardCaptureState` 取出待提交的图片路径列表，转换为 `ImageURLPart` 列表。
       - 构造 `UserInputPayload(text=text, images=images)` 并从 `iter_inputs` yield。
     - 清理对 `persist_clipboard_manifest` 的调用，保留 `Ctrl+V` 插入 tag 的 UX（可将 tag 仅作为可视提示）。
   - 依赖：任务 8。
   - 验收标准：
     - REPL 中 `Ctrl+V` + `Enter` 能立即在首轮请求中带上图片，无需 reminder 介入。
     - 不再写入 `~/.klaude/clipboard/manifests` 文件（可通过手工验证或测试）。
   - 估算：L。

10. CLI run_interactive / run_exec 适配新接口
    - 描述：
      - `run_interactive`：
        - 将 `input_provider: InputProviderABC` 的 `iter_inputs` 结果类型更新为 `UserInputPayload`。
        - 在提交 `UserInputOperation` 时，填充 `content=payload.text` 与 `images=payload.images`。
      - `run_exec`：
        - 仍接收 `input_content: str`，在内部构造 `UserInputPayload(text=input_content, images=None)`。
    - 依赖：任务 4、8、9。
    - 验收标准：
      - CLI 非交互及交互模式均可正常运行，无回归错误。
    - 估算：M。

### Phase 4：reminders 与 clipboard_manifest 迁移/清理

11. 更新 clipboard_image_reminder 的行为
    - 描述：
      - 若最近一条 `UserMessageItem` 已有 `images`：直接返回 None，不再尝试读取 manifest。
      - 保持对旧历史的兼容（例如已有 manifest / `[Image #N]` 的会话）。
    - 依赖：任务 5–10。
    - 验收标准：
      - 在新链路下不会重复附加图片（避免同一张图既挂在 user message 又挂在 developer message）。
    - 估算：S。

12. 评估并可能删除 clipboard_manifest.py
    - 描述：
      - 搜索整个代码库，确认除 tests 外已无对 `persist_clipboard_manifest` / `load_latest_clipboard_manifest` 的调用。
      - 如无其他用途，删除该模块与相关测试；如仍需保留，则在文档中标注为 legacy，仅用于兼容。
    - 依赖：任务 9、11。
    - 验收标准：
      - 若删除：测试全部通过，无运行时引用错误。
      - 若保留：有清晰注释说明用途与未来退场计划。
    - 估算：M。

### Phase 5：测试与回归

13. 增加单元测试覆盖 UserInputPayload 流转
    - 描述：
      - 针对 `ExecutorContext.handle_user_input`、`Agent.run_task`、`TaskExecutor.run` 编写测试，验证图片从 `UserInputOperation` 一直流到 `UserMessageItem.images`。
    - 依赖：任务 2–7。
    - 验收标准：
      - 测试能覆盖文本-only、图片-only、文本+图片三种情况。
    - 估算：M。

14. REPL 集成测试（手动或自动）
    - 描述：
      - 手动或通过端到端测试框架验证：
        - 常规文本对话。
        - 多张图片粘贴 + 提交。
        - 重复粘贴但不引用 tag 的图是否被正确忽略或处理（视 UX 设计）。
      - 检查 `.klaude/clipboard` 目录不再增长 manifest 文件。
    - 依赖：任务 9–11。
    - 验收标准：
      - 所有主要交互路径表现符合预期，无崩溃或明显 UX 退化。
    - 估算：L。

## 6. Risk Assessment and Mitigation

1. 类型变化带来的连锁回归风险
   - 风险：`user_input` 从 `str` 变为 `UserInputPayload`，影响范围大（executor、agent、task、UI、protocol）。
   - 缓解：
     - 一次性更新所有核心链路 API 的签名，避免双轨制导致混乱。
     - 配合 Pyright 严格类型检查和完整测试，尽早发现遗漏调用点。

2. UI 与协议层的耦合
   - 风险：UI 若直接依赖 `protocol.model.UserInputPayload`，会增加跨层依赖。
   - 缓解：
     - 在设计阶段确认是否需要一个 `core/user_input.py`，作为 UI 与 protocol 的中间层。
     - 保持 `UserInputPayload` 结构稳定，避免频繁变更。

3. 图片重复附加或遗漏
   - 风险：
     - 在重构期间，如旧 reminder 尚未移除，可能导致同一张图片在 LLM 输入中出现两次或完全缺失。
   - 缓解：
     - 在开发阶段尽早完成 `clipboard_image_reminder` 的删除，并通过端到端测试验证图片只通过 `UserInputPayload.images` 这一路进入模型。

4. 文件系统与权限问题
   - 风险：即使不再依赖 manifest，REPL 仍可能需要临时文件来存储图片（视 LLM 客户端实现而定）。
   - 缓解：
     - 尽量复用现有的 `ImageURLPart`/ReadTool 处理图片路径逻辑。
     - 对异常路径/权限问题增加防御式处理与日志。

5. 性能与内存占用
   - 风险：若将图片完全加载到内存并在多处复制，可能增加内存占用。
   - 缓解：
     - 保持 `ImageURLPart` 仅存路径/URL，由 LLM 客户端按需加载。
     - 避免在 Python 层复制大对象。

## 7. Success Metrics

- 功能正确性：
  - REPL 中通过 `Ctrl+V` 粘贴图片并发送时，该轮会话历史中的 `UserMessageItem.images` 必须包含对应图片；LLM 端可正常处理多模输入。
- 稳定性：
  - 改动后运行常规工作流（无图片、多图片）不会比现状出现更多错误或异常日志。
- 简化度：
  - 代码层面不再有新的对 `clipboard_manifest` 的生产使用；`clipboard_image_reminder` 降为兼容逻辑或完全移除。
- 可测试性：
  - 单元测试可通过直接构造 `UserInputPayload` 验证图片流转，无需操作系统剪贴板或磁盘 manifest。

## 8. Required Resources and Dependencies

- 人力：
  - 熟悉本项目核心链路的 Python 工程师 1–2 名。
  - 对 prompt-toolkit 与终端 UI 有经验的开发者 1 名（负责 REPL 部分）。
- 技术依赖：
  - 现有 LLM 客户端对 `ImageURLPart` 的支持。
  - Pyright 严格类型检查与 pytest 测试框架。
  - 手动验证需要具备图形环境与系统剪贴板访问能力的终端环境。

## 9. Timeline Estimates（粗略）

- Phase 0：设计与对齐 —— 0.5–1 天。
- Phase 1：协议与核心模型改造 —— 0.5 天。
- Phase 2：Executor / Agent / Task 链路适配 —— 1–1.5 天。
- Phase 3：UI 输入层（REPL）改造 —— 1.5–2 天。
- Phase 4：reminders / clipboard_manifest 清理 —— 0.5–1 天。
- Phase 5：测试与回归 —— 1–2 天（取决于自动化程度）。

整体估算：约 4–7 个工作日，可根据实际迭代节奏与代码评审情况调整。
