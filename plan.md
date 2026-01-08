# 上下文压缩（Compaction）实施计划

本计划用于在 `klaude-code` 仓库实现 Pi 风格的上下文压缩机制：

- 会话历史保持 append-only 持久化（用于 replay/export）。
- 模型上下文（LLM view）在需要时将旧内容压缩为结构化摘要，仅保留摘要 + 最近对话片段。

本文档设计为“可交给完全无上下文的后续 agent 直接执行”的工作说明，包含需求、边界与分阶段交付物。

---

## 需求与约束（必须满足）

### 用户体验（TUI/UI）

- 不清屏；压缩期间在 spinner/status 中显示 `Compacting`（压缩会调用 LLM，可能耗时）。
- 使用新的事件类型驱动 UI 状态（不是复用现有命令输出事件）。

### 自动触发与重试策略

- threshold（接近上下文窗口）
  - 自动执行压缩，不需要用户确认。
  - 压缩完成后继续正常会话流；不进行“自动重试上一条用户输入”的额外二次提交逻辑。
    - 具体落点：pre-prompt 检查在提交 `RunAgentOperation` 之前执行。
- overflow（上下文已溢出导致请求失败）
  - 必须自动执行压缩，并自动重试同一 turn。

### 数据与持久化

- 新增可持久化 `CompactionEntry`（Pi 风格），允许多轮压缩（多条 entry）。
- session 为 append-only 存储，因此 cut point 使用 index（而不是稳定 UUID）。

### 压缩算法与规则

- 支持 split-turn（单轮过长，cut 点落在轮次中间）。
- 禁止 cut 在 `ToolResultMessage` 上（工具结果必须跟随其 tool call 语境）。
- 摘要格式完全复用 Pi（Goal / Constraints & Preferences / Progress / Key Decisions / Next Steps / Critical Context）。
- 摘要必须提炼并保留关键约束（包括 developer/memory 约束），但避免塞入大段原文（例如整份文件全文、超长命令输出）。

### 取消与并发

- 压缩可取消；取消后不写入 `CompactionEntry`。
- 不允许与运行中的 agent task 并发；Pi 风格先 abort 当前 task/turn，再执行压缩。

---

## 参考实现（Pi）

### Prompt 必须原样复用（不改模板文本与标签）

Pi 的 compaction 提示词与拼装方式在以下文件中定义：

- Summarizer system prompt：`badlogic-pi-mono/packages/coding-agent/src/core/compaction/utils.ts` 常量 `SUMMARIZATION_SYSTEM_PROMPT`
- 初次摘要模板：`badlogic-pi-mono/packages/coding-agent/src/core/compaction/compaction.ts` 常量 `SUMMARIZATION_PROMPT`
- 多轮压缩的增量更新模板：`badlogic-pi-mono/packages/coding-agent/src/core/compaction/compaction.ts` 常量 `UPDATE_SUMMARIZATION_PROMPT`
- split-turn 的轮次前缀摘要模板：`badlogic-pi-mono/packages/coding-agent/src/core/compaction/compaction.ts` 常量 `TURN_PREFIX_SUMMARIZATION_PROMPT`

Pi 的 prompt 拼装逻辑（必须复用）：

- `promptText = <conversation>...serialized...</conversation>`
- 可选：`+ <previous-summary>...previous...</previous-summary>`（用于多轮压缩增量更新）
- `+ basePrompt`（二选一：`SUMMARIZATION_PROMPT` / `UPDATE_SUMMARIZATION_PROMPT`）
- 可选：若提供 `/compact <focus>`，在 `basePrompt` 后追加 `Additional focus: ...`

Pi 的 file 标签（必须复用）：

- `<read-files>` / `<modified-files>` 的生成格式复用 `badlogic-pi-mono/packages/coding-agent/src/core/compaction/utils.ts` 的 `formatFileOperations()`。
- 将标签追加在最终 summary 末尾（Pi 在 `compaction.ts` 中 `summary += formatFileOperations(...)`）。

---

## klaude-code 现状与关键坑位（必须在实现中处理）

- `Session` 的持久化是 append-only（`events.jsonl` + `meta.json` 快照），不能通过删除旧 history 实现压缩。
- `DeveloperMessage` 在构建 provider 输入时会被 attach 到最近的 user/tool 消息；如果序列起始没有 anchor，developer 会被跳过。
  - 因此 compaction summary 注入不得用 `DeveloperMessage` 置顶；应使用 `SystemMessage` 注入 summary。
- LLM 输入当前取自 `SessionContext.get_conversation_history()`；需要引入 `LLM view`：
  - 模型看到：`[system prompt + summary(system message)] + [first_kept_index 之后消息]`。
- 自动触发的两类执行点：
  - threshold：TUI pre-prompt（提交 RunAgentOperation 之前）。
  - overflow：TaskExecutor 捕获 TurnError（识别 overflow 后 compaction + retry）。

---

## 关键代码锚点与骨架（锁定实现形状）

本节用于把关键“代码骨架/接口/插入点”锁定下来，降低后续 agent 走偏的概率。

### 1) 数据模型：`CompactionEntry`（HistoryEvent，可持久化）

新增一个 Pydantic model，并加入 `src/klaude_code/protocol/message.py` 的 `HistoryEvent` union。

建议形状（字段名可在实现时微调，但语义必须包含）：

```python
from datetime import datetime
from pydantic import BaseModel, Field


class CompactionDetails(BaseModel):
    read_files: list[str] = Field(default_factory=list)
    modified_files: list[str] = Field(default_factory=list)


class CompactionEntry(BaseModel):
    summary: str
    first_kept_index: int
    tokens_before: int | None = None
    details: CompactionDetails | None = None
    created_at: datetime = Field(default_factory=datetime.now)
```

约束：

- `events.jsonl` append-only；允许多次追加多个 `CompactionEntry`。
- `first_kept_index` 指向 **同一个 session 的** `conversation_history` 列表位置（index）。

### 2) 事件：compaction 状态（用于 spinner）

在 `src/klaude_code/protocol/events.py` 新增事件类型：

```python
class CompactionStartEvent(Event):
    reason: Literal["threshold", "overflow", "manual"]


class CompactionEndEvent(Event):
    reason: Literal["threshold", "overflow", "manual"]
    aborted: bool = False
    will_retry: bool = False
    tokens_before: int | None = None
    kept_from_index: int | None = None
```

在 `src/klaude_code/tui/machine.py`：

- `CompactionStartEvent` → `SpinnerStart` + status 设置为 `Compacting`（作为 reasoning/status 文本的一层）。
- `CompactionEndEvent` → 清除/恢复 status（并保持“不清屏”）。

### 3) Operation：`CompactSessionOperation`（可取消 + 不并发）

在 `src/klaude_code/protocol/op.py`：

```python
class OperationType(Enum):
    COMPACT_SESSION = "compact_session"


class CompactSessionOperation(Operation):
    type: OperationType = OperationType.COMPACT_SESSION
    session_id: str
    reason: Literal["threshold", "overflow", "manual"]
    focus: str | None = None
    will_retry: bool = False
```

在 `src/klaude_code/protocol/op_handler.py`：新增 `handle_compact_session(self, operation: CompactSessionOperation) -> None`。

在 `src/klaude_code/core/executor.py`（ExecutorContext）：

- 实现 `handle_compact_session()`，并 **像 `handle_run_agent()` 一样注册一个 asyncio.Task 到 TaskManager**，这样：
  - `executor.wait_for(submission_id)` 能正确等待
  - `InterruptOperation` 能通过 TaskManager cancel 正在进行的 compaction（满足“可取消”）

并发约束（必须）：

- 若该 session 当前存在运行中的 agent task：先 abort 再 compact（Pi 风格）。

### 4) 命令：`/compact` → 提交 `CompactSessionOperation(reason="manual")`

在 `src/klaude_code/tui/command/compact_cmd.py` 新增命令实现，并在 `src/klaude_code/tui/command/__init__.py` 的 `ensure_commands_loaded()` 注册。

要求：

- 支持 `/compact` 与 `/compact <focus>`
- focus 传递到 compaction prompt（Pi 风格 `Additional focus: ...`）

### 5) LLM view：压缩真正生效的插入点

新增 `Session.get_llm_history()`（建议在 `src/klaude_code/session/session.py`）。核心规则：

```python
def get_llm_history(self) -> list[message.HistoryEvent]:
    # 1) 找到最后一条 CompactionEntry（若无，返回原 history）
    # 2) 生成一个 SystemMessage，内容为 compaction summary（不得用 DeveloperMessage）
    # 3) 返回：[summary_system_message] + history[first_kept_index:]
    # 4) 过滤掉 CompactionEntry 本身（避免把 entry 当普通消息送入 LLM）
```

把 `Agent.run_task()` 的 `SessionContext.get_conversation_history` 从：

- `lambda: self.session.conversation_history`

替换为：

- `lambda: self.session.get_llm_history()`

对应文件：`src/klaude_code/core/agent.py`。

### 6) threshold 自动压缩：TUI pre-prompt 的插入点

插入点在 `src/klaude_code/tui/runner.py` 的 `submit_user_input_payload()` 中：

- 在 submit `RunAgentOperation` 之前执行 `maybe_compact_threshold()`
- 如果需要 compact：先 submit `CompactSessionOperation(reason="threshold")` 并等待完成（期间 UI 显示 `Compacting`）
- 然后再 submit `RunAgentOperation`

注意：因为 compact 在用户输入提交之前，所以不会出现“重复提交同一条输入”的二次重试逻辑。

### 7) overflow 自动压缩 + retry：TaskExecutor 的插入点

插入点在 `src/klaude_code/core/task.py` 捕获 `TurnError` 的分支（turn 失败重试逻辑处）。

要求：

- 实现一个 overflow detector（正则匹配错误文本），参考 Pi：`badlogic-pi-mono/packages/ai/src/utils/overflow.ts`
- 若识别为 overflow：
  1) 发 `CompactionStartEvent(reason="overflow")`
  2) 执行 compaction（写入 CompactionEntry）
  3) 发 `CompactionEndEvent(will_retry=True)`
  4) retry 同一 turn

### 8) Compaction 核心函数的最小 API（建议固定）

建议在 `src/klaude_code/core/compaction/compaction.py` 暴露这些入口，供 Op/Task/TUI 复用：

```python
class CompactionReason(str, Enum):
    THRESHOLD = "threshold"
    OVERFLOW = "overflow"
    MANUAL = "manual"


@dataclass
class CompactionConfig:
    reserve_tokens: int
    keep_recent_tokens: int


@dataclass
class CompactionResult:
    summary: str
    first_kept_index: int
    tokens_before: int | None
    details: CompactionDetails | None


def should_compact_threshold(*, session: Session, config: CompactionConfig, llm_config: llm_param.LLMConfigParameter) -> bool:
    ...


async def run_compaction(*, session: Session, reason: CompactionReason, focus: str | None, llm_client: LLMClientABC, llm_config: llm_param.LLMConfigParameter, cancel: asyncio.Event | None = None) -> CompactionResult:
    ...
```

其中 `run_compaction()` 需要内部调用 summarizer LLM：

- system：Pi 的 `SUMMARIZATION_SYSTEM_PROMPT`
- user：`<conversation>...</conversation>` + 可选 `<previous-summary>...</previous-summary>` + Pi 模板
- summarizer 不需要 tools（避免出现工具调用）

---

---

## Phase 0：设计落地与接口草图（1–2 天）

**交付物**

1) 数据模型与事件/Op 的接口确定（不实现业务逻辑，仅定义“长什么样”）。
2) 文档化：本文件补充更新（或新增 `docs/compaction.md`）。

**关键决策落点**

- `CompactionEntry` 存储在 `events.jsonl`（append-only），可多次追加。
- `first_kept_index: int` 作为 cut point。
- `summary` 以结构化 Markdown 保存（复用 Pi 模板）。
- `details` 存 file tracking（read-files / modified-files）并支持多轮累计。

**涉及文件（预期变更）**

- `src/klaude_code/protocol/message.py`：在 `HistoryEvent` union 中加入 `CompactionEntry`。
- `src/klaude_code/session/codec.py`：无需改（union 自动注册），但需要增加测试覆盖。
- `src/klaude_code/protocol/events.py`：新增事件类型。
- `src/klaude_code/protocol/op.py`：新增 `CompactSessionOperation`。
- `src/klaude_code/protocol/op_handler.py`：新增 `handle_compact_session()`。

**新增事件（必须）**

- `CompactionStartEvent(session_id, reason: "threshold"|"overflow"|"manual")`
- `CompactionEndEvent(session_id, reason, aborted: bool, will_retry: bool, tokens_before?: int, kept_from_index?: int)`
- （可选）`CompactionProgressEvent(session_id, stage: Literal[...])` 用于细粒度状态，但不是必须。

**测试（本阶段）**

- 新增 `tests/test_codec_compaction_entry.py`：确保 `CompactionEntry` 可被 encode/decode 并 round-trip。

---

## Phase 1：Compaction 核心逻辑（纯函数 + 可单测）（2–4 天）

目标：实现类似 Pi 的 compaction 算法，但适配 klaude-code 的消息类型（User/Assistant/ToolResult/Developer/System）。

**交付物**

1) `src/klaude_code/core/compaction/`：
   - token 估算、cut point 查找、消息序列化、文件追踪提取、摘要 prompt 生成。
2) 单元测试覆盖：cut point 规则、split-turn 规则、file list 累计规则。

**实现要点**

### 0) Prompt 复用落地（必须）

落地建议：在本仓库新增 `src/klaude_code/core/compaction/prompts.py`，将 Pi 的四段 prompt 常量原样复制（英文内容不改动）。

### 1) Token 估算（threshold 触发与 cut point）

- 采用 Pi 的保守估算（chars/4），并给图片固定上界（例如 1200 tokens/图）。
- 支持 tool call 参数/工具输出的粗略估算（避免 underestimate 导致继续溢出）。

### 2) Cut point 规则（必须遵守）

- **绝不 cut 在 `ToolResultMessage`**：工具结果必须跟随其 tool call 语境。
- **kept 段的开头不得是 `DeveloperMessage`**：否则会被 `attach_developer_messages()` 吞掉。
  - 若 cut 后第一条是 `DeveloperMessage`，应向前/向后调整到最近的 `UserMessage` 或 `ToolResultMessage` 锚点。
- 支持 split-turn：当 keep_recent_budget 太小导致 cut 落在一轮对话中间时：
  - 生成“历史摘要”（完整轮次）
  - 生成“当前轮前缀摘要”（被切掉的那部分）
  - 合并成最终 summary（Pi 风格）。

### 3) 序列化（给 summarizer LLM 的输入）

- 参考 Pi `serializeConversation()`：把对话“扁平化”成不可继续对话的文本块：
  - `[User]` / `[Assistant]` / `[Assistant thinking]` / `[Assistant tool calls]` / `[Tool result]` / `[Developer]`
- 序列化与 prompt 的结合方式必须复用 Pi：将序列化文本放入 `<conversation>...</conversation>` 标签中，再追加 `SUMMARIZATION_PROMPT` 或 `UPDATE_SUMMARIZATION_PROMPT`。
- 序列化时要**保留**：文件路径、函数名、错误文本。
- 序列化时要**避免**：大段原文（例如整份文件全文、超长命令输出）。

### 4) 文件追踪（用于 `<read-files>` / `<modified-files>`）

- modified-files：优先从 `ToolResultMessage.ui_extra` 的 `DiffUIExtra/MarkdownDocUIExtra/MultiUIExtra` 推断。
- read-files：从 `file_tracker` + `ReadTool` 的访问记录补全。
- 多轮压缩累计：新 summary 生成时要合并上一次 `CompactionEntry.details` 的累积列表（Pi 风格）。

**测试（本阶段）**

- `tests/test_compaction_cut_point.py`
- `tests/test_compaction_split_turn.py`
- `tests/test_compaction_file_lists.py`

---

## Phase 2：手动压缩（/compact）+ 新 Op + UI 事件（2–3 天）

目标：让用户能显式触发压缩，并在 UI 看到 `Compacting` 状态。

**交付物**

1) 新命令：`/compact`（可选接受额外指令：`/compact <focus>`）。
2) 新 Op：`CompactSessionOperation`，通过 `ExecutorContext` 执行。
3) UI：
   - `CompactionStartEvent` → spinner 开始、status 设置为 `Compacting`。
   - `CompactionEndEvent` → spinner 停止、打印一条简短结果（可选）。
4) 取消：压缩过程中收到 interrupt/esc 时可以取消（抛 `CancelledError` 或使用内部 cancel flag）。

**涉及文件（预期变更）**

- `src/klaude_code/protocol/op.py`：新增 `COMPACT_SESSION`。
- `src/klaude_code/core/executor.py`：实现 `handle_compact_session()`。
- `src/klaude_code/tui/command/`：新增 `compact_cmd.py` 并在 `__init__.py` 中注册。
- `src/klaude_code/protocol/events.py`：新增 compaction 事件。
- `src/klaude_code/tui/machine.py`：渲染 compaction 事件，驱动 spinner。

**并发规则（必须实现）**

- 如果当前有运行中的 agent task：
  - 先执行 abort（Pi 风格）
  - 再开始 compaction

**测试（本阶段）**

- `tests/test_tui_machine_compaction_events.py`：验证 CompactionStart/End 事件对 spinner 状态的影响。

---

## Phase 3：LLM 视图接入（压缩真正生效）+ 多轮压缩（2–4 天）

目标：压缩后模型上下文变为：`[system prompt] + [压缩摘要] + [first_kept_index 之后消息]`。

**交付物**

1) `Session.get_llm_history()`（或等价机制）
   - 从 `conversation_history` 中查最后一个 `CompactionEntry`
   - 构造一个 `message.SystemMessage(parts=[TextPart(summary)])` 作为“摘要注入”
   - 拼接 `conversation_history[first_kept_index:]` 并过滤掉 `CompactionEntry` 本身
2) `Agent.run_task()` 使用 `get_llm_history()` 替代直接传 `conversation_history`。
3) 多轮压缩：新压缩应使用 Pi 的 update-summary prompt：
   - `<previous-summary>` + “新增被压缩片段” → 生成更新后的 summary

**跨 provider 兼容性说明（为什么 summary 用 SystemMessage）**

- Anthropic/Gemini：历史里的 `SystemMessage` 会被合并进 system prompt（`llm/anthropic/client.py` 读取 `system_messages`）。
- OpenAI/OpenRouter/Responses：`SystemMessage` 会作为额外 system role message 进入输入。

**测试（本阶段）**

- `tests/test_session_llm_view_compaction.py`：
  - 无 compaction 时等于原 history（过滤非 message 类型不在此测试范围）
  - 有 compaction 时：summary 被注入；first_kept_index 之前的消息不再出现在 llm view
  - 多次 compaction 时：只使用最后一次 compaction 的 summary + kept 段

---

## Phase 4：自动 threshold compaction（pre-prompt，不重试输入）（2–3 天）

目标：用户输入提交前自动检查阈值，必要时先压缩；UI 展示 `Compacting`；压缩完成后再提交用户输入。

**触发位置（按你的决策）**

- TUI 层 pre-prompt：在提交 `RunAgentOperation` 之前执行 `maybe_compact_threshold()`。
  - 依据：优先真实 usage（若可得），否则本地估算（C 策略）。

**交付物**

- `tui/runner.py`：在 `submit_user_input_payload()` 提交 RunAgentOperation 之前插入：
  - `if should_compact_threshold(session): submit CompactSessionOperation; await completion;`
  - 然后再 submit RunAgentOperation

**注意事项**

- threshold compaction 发生在输入提交之前：执行顺序为 `CompactSessionOperation` 完成后，再提交 `RunAgentOperation`。
  - 这满足“无确认但有 UI 状态”的体验，同时避免引入“同一条输入重复提交两次”的额外逻辑。

**测试（本阶段）**

- `tests/test_runner_threshold_compaction.py`（偏集成）：
  - 构造一个 session，使 `should_compact_threshold` 返回 true
  - 验证 op 提交顺序：Compact → RunAgent

---

## Phase 5：自动 overflow compaction + 自动 retry（TaskExecutor 内）（3–5 天）

目标：当 LLM 返回“上下文溢出”错误时，自动压缩并自动重试同一 turn。

**触发位置（按你的决策）**

- `src/klaude_code/core/task.py` 捕获 `TurnError` 时：
  - 用 Pi 风格正则检测是否为 overflow（B 策略）。
  - 如果是 overflow：
    - abort 当前 turn（确保工具不再跑）
    - 执行 compaction（reason=overflow, will_retry=True）
    - retry 同一 turn

**交付物**

1) overflow detector：`core/compaction/overflow.py`（或 `llm/utils/overflow.py`）
   - 正则集合参考 Pi `packages/ai/src/utils/overflow.ts`
2) TaskExecutor retry 流程扩展：
   - 区分普通错误 retry 与 overflow→compact→retry
3) UI：触发 `CompactionStartEvent(reason="overflow")`，EndEvent 标记 will_retry。

**测试（本阶段）**

- `tests/test_overflow_detector.py`
- `tests/test_task_executor_overflow_compact_retry.py`

---

## Phase 6：参数化与打磨（1–3 天）

目标：把 Pi 的 reserve/keep_recent 等参数以配置形式开放，并根据模型 `context_limit` 做自适应。

**交付物**

- 新配置项（建议放在现有 config 结构里）：
  - `compaction.enabled`
  - `compaction.reserve_tokens`（默认可自适应）
  - `compaction.keep_recent_tokens`（默认可自适应）
  - `compaction.max_summary_tokens`（默认 reserve 的 0.8）
- `/compact <focus>`：将 focus 追加进 summary prompt（Pi 的 Additional focus）。

---

## Phase 7：手工验证与回归（持续）

建议回归路径：

1) 手动 `/compact`：确认 UI spinner 显示、可取消、session 不清屏。
2) 多轮压缩：连续触发两次 compaction，确认：
   - LLM view 使用最后一次 summary
   - file lists 累计
3) threshold 自动压缩：构造接近窗口的对话，确认发送后先 Compaction，再开始 agent task。
4) overflow 自动压缩+重试：用小 context_limit 模型/配置复现溢出，确认自动恢复。

（可选）使用 `tmux-test` 验证交互/UI 状态切换。

---

## 风险清单（实现时重点关注）

1) `DeveloperMessage` attach 语义：summary 不应以 DeveloperMessage 置顶，否则会被吞；本计划用 `SystemMessage` 注入 summary。
2) cut point 边界：必须避免 kept 段从 `ToolResultMessage` 或 `DeveloperMessage` 开始。
3) append-only：禁止通过删除旧 history 实现压缩；必须通过“LLM view”生效。
4) summarizer 自身也可能溢出：需要严格的 token budget + update-summary 机制。
5) 并发：compaction 与 agent task 不并发；必须先 abort。
