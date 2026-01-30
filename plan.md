# Backtrack 功能实现计划

实现一个 Backtrack 工具，参考 kimi-cli 的 Dmail 设计，允许 Agent 回退对话历史到之前的检查点，同时给未来的自己传递一条备注。这可以优化上下文使用，丢弃无效探索同时保留关键信息。

## Scope
- In: Backtrack 工具、检查点管理、历史回退、BacktrackEntry 存储、UI 渲染
- Out: 文件系统回滚、子 Agent 的 Backtrack、与 Compaction 的合并

---

## 一、参考: kimi-cli Dmail 实现分析

### 1.1 核心组件

| 文件路径 | 作用 |
|---------|------|
| `src/kimi_cli/tools/dmail/__init__.py` | SendDMail 工具定义 |
| `src/kimi_cli/tools/dmail/dmail.md` | 工具说明文档 |
| `src/kimi_cli/soul/denwarenji.py` | DenwaRenji 状态管理器 |
| `src/kimi_cli/soul/context.py` | 检查点管理和 revert_to() 回退 |
| `src/kimi_cli/soul/kimisoul.py` | Agent 主循环，集成 Dmail 逻辑 |

### 1.2 数据模型

```python
# kimi-cli: src/kimi_cli/tools/dmail/__init__.py
class DMail(BaseModel):
    message: str = Field(description="The message to send.")
    checkpoint_id: int = Field(description="The checkpoint to send the message back to.", ge=0)
```

### 1.3 状态管理器 (DenwaRenji)

```python
# kimi-cli: src/kimi_cli/soul/denwarenji.py
class DenwaRenji:
    def __init__(self):
        self._pending_dmail: DMail | None = None
        self._n_checkpoints: int = 0
    
    def send_dmail(self, dmail: DMail):
        if self._pending_dmail is not None:
            raise DenwaRenjiError("Only one D-Mail can be sent at a time")
        if dmail.checkpoint_id >= self._n_checkpoints:
            raise DenwaRenjiError("There is no checkpoint with the given ID")
        self._pending_dmail = dmail
    
    def fetch_pending_dmail(self) -> DMail | None:
        pending_dmail = self._pending_dmail
        self._pending_dmail = None
        return pending_dmail
    
    def set_n_checkpoints(self, n: int) -> None:
        self._n_checkpoints = n
```

### 1.4 检查点与回退机制

```python
# kimi-cli: src/kimi_cli/soul/context.py
async def checkpoint(self, add_user_message: bool):
    checkpoint_id = self._next_checkpoint_id
    self._next_checkpoint_id += 1
    # 写入检查点标记到 JSONL
    await f.write(json.dumps({"role": "_checkpoint", "id": checkpoint_id}) + "\n")
    # 可选: 添加用户可见消息
    if add_user_message:
        await self.append_message(Message(role="user", content=[system(f"CHECKPOINT {checkpoint_id}")]))

async def revert_to(self, checkpoint_id: int):
    # 1. 旋转当前上下文文件（备份）
    rotated_file_path = await next_available_rotation(self._file_backend)
    await aiofiles.os.replace(self._file_backend, rotated_file_path)
    # 2. 从备份读取并重建到指定检查点
    async with aiofiles.open(rotated_file_path) as old_file:
        async for line in old_file:
            line_json = json.loads(line)
            if line_json["role"] == "_checkpoint" and line_json["id"] == checkpoint_id:
                break
            await new_file.write(line)
```

### 1.5 Agent Loop 集成

```python
# kimi-cli: src/kimi_cli/soul/kimisoul.py
async def _agent_loop(self) -> TurnOutcome:
    while True:
        await self._checkpoint()  # 每个 turn 前创建检查点
        self._denwa_renji.set_n_checkpoints(self._context.n_checkpoints)
        
        try:
            step_outcome = await self._step()
        except BackToTheFuture as e:
            # 捕获时间旅行异常
            await self._context.revert_to(e.checkpoint_id)
            await self._context.append_message(e.messages)  # 注入 Dmail 消息
            continue

# 在 _step() 中检查 pending dmail
if dmail := self._denwa_renji.fetch_pending_dmail():
    raise BackToTheFuture(
        dmail.checkpoint_id,
        [Message(role="user", content=[system(
            f"You just got a D-Mail from your future self...\n{dmail.message}"
        )])]
    )
```

### 1.6 关键设计特点

1. **单例限制**: 同时只能有一个待处理的 Dmail
2. **异常驱动**: 使用 `BackToTheFuture` 异常中断执行流
3. **文件系统不回退**: 只回退对话上下文，文件操作保持不变
4. **透明化处理**: AI 被告知"不要向用户提及"，保持用户体验流畅

---

## 二、klaude-code 现有架构参考

### 2.1 Compaction 模式 (参考实现)

我们已经有 CompactionEntry 作为 HistoryEvent 存储在 Session 中，Backtrack 应遵循相同模式。

| 文件路径 | 作用 |
|---------|------|
| `src/klaude_code/protocol/message.py` | CompactionEntry 定义 |
| `src/klaude_code/core/compaction/compaction.py` | 压缩逻辑 |
| `src/klaude_code/core/task.py` | TaskExecutor 集成 |
| `src/klaude_code/session/session.py` | Session 存储和 get_llm_history() |
| `src/klaude_code/protocol/events.py` | CompactionStartEvent/EndEvent |
| `src/klaude_code/tui/machine.py` | 状态机处理事件 |
| `src/klaude_code/tui/renderer.py` | display_compaction_summary() |

### 2.2 工具实现模式 (参考)

```python
# src/klaude_code/core/tool/todo/todo_write_tool.py
@register(tools.TODO_WRITE)
class TodoWriteTool(ToolABC):
    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name=tools.TODO_WRITE,
            type="function",
            description=load_desc(Path(__file__).parent / "todo_write_tool.md"),
            parameters={...},
        )

    @classmethod
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        args = TodoWriteArguments.model_validate_json(arguments)
        # ... 业务逻辑 ...
        return message.ToolResultMessage(status="success", output_text=response, ...)
```

### 2.3 ToolContext 结构

```python
# src/klaude_code/core/tool/context.py
@dataclass(frozen=True)
class ToolContext:
    file_tracker: FileTracker
    todo_context: TodoContext
    session_id: str
    run_subtask: RunSubtask | None = None
    sub_agent_resume_claims: SubAgentResumeClaims | None = None
    # ... 需要添加 backtrack_manager
```

---

## 三、Backtrack 实现设计

### 3.1 核心设计决策

1. **检查点嵌入 DeveloperMessage**: 不新增 CheckpointMarker 类型，直接使用现有的 DeveloperMessage
2. **利用现有附加机制**: 通过 `attach_developer_messages()` (见 `input_common.py`)，检查点标记自动附加到前一条 UserMessage/ToolResultMessage 后面
3. **默认启用**: Backtrack 功能默认开启
4. **自动执行**: 没有工具审批机制，Backtrack 自动执行
5. **UI 展示**: 回退后展示对应检查点的 UserMessage 内容，让用户知道回到了哪里

### 3.2 检查点机制 (无需新类型)

检查点通过 DeveloperMessage 实现，利用现有的消息附加机制：

```python
# 在每个 turn 开始时插入
checkpoint_msg = message.DeveloperMessage(
    parts=[message.TextPart(text=f"<system>Checkpoint {checkpoint_id}</system>")]
)
session.append_history([checkpoint_msg])
```

**现有的 `attach_developer_messages()` 机制**:
```python
# src/klaude_code/llm/input_common.py
def attach_developer_messages(messages: Iterable[message.Message]) -> list[tuple[message.Message, DeveloperAttachment]]:
    """Attach developer messages to the most recent user/tool message.

    Developer messages are removed from the output list and their text/images are
    attached to the previous user/tool message as out-of-band content for provider input.
    """
    # DeveloperMessage 被移除，其内容附加到前一条 UserMessage/ToolResultMessage
```

**LLM 看到的效果**:
```
用户: 帮我分析这个文件
<system>Checkpoint 0</system>

助手: 好的，让我读取文件... [调用 Read 工具]

[工具结果]
<system>Checkpoint 1</system>

助手: 文件内容如下...
```

### 3.3 新增数据模型 (仅 BacktrackEntry)

**文件**: `src/klaude_code/protocol/message.py`

```python
class BacktrackEntry(BaseModel):
    """记录一次 Backtrack 操作"""
    checkpoint_id: int              # 回退到的检查点 ID
    note: str                       # AI 给自己的备注
    reverted_from_index: int        # 从哪个历史索引回退的
    original_user_message: str      # 检查点对应的用户消息内容 (用于 UI 展示)
    created_at: datetime = Field(default_factory=datetime.now)


# 更新 HistoryEvent 类型
HistoryEvent = Message | StreamErrorItem | TaskMetadataItem | CompactionEntry | BacktrackEntry
```

### 3.4 状态管理器

**新增目录**: `src/klaude_code/core/backtrack/`

**文件**: `src/klaude_code/core/backtrack/__init__.py`
```python
from klaude_code.core.backtrack.manager import BacktrackManager, BacktrackRequest

__all__ = ["BacktrackManager", "BacktrackRequest"]
```

**文件**: `src/klaude_code/core/backtrack/manager.py`
```python
from dataclasses import dataclass


@dataclass
class BacktrackRequest:
    checkpoint_id: int
    note: str


class BacktrackManager:
    """管理 Backtrack 状态，每个 TaskExecutor 实例一个"""
    
    def __init__(self) -> None:
        self._pending: BacktrackRequest | None = None
        self._n_checkpoints: int = 0
        # 存储每个检查点对应的用户消息 (用于 UI 展示)
        self._checkpoint_user_messages: dict[int, str] = {}
    
    def set_n_checkpoints(self, n: int) -> None:
        self._n_checkpoints = n
    
    @property
    def n_checkpoints(self) -> int:
        return self._n_checkpoints
    
    def register_checkpoint(self, checkpoint_id: int, user_message: str) -> None:
        """注册检查点对应的用户消息"""
        self._checkpoint_user_messages[checkpoint_id] = user_message
    
    def get_checkpoint_user_message(self, checkpoint_id: int) -> str | None:
        """获取检查点对应的用户消息"""
        return self._checkpoint_user_messages.get(checkpoint_id)
    
    def send_backtrack(self, checkpoint_id: int, note: str) -> str:
        """由 Backtrack 工具调用"""
        if self._pending is not None:
            raise ValueError("Only one backtrack can be pending at a time")
        if checkpoint_id < 0 or checkpoint_id >= self._n_checkpoints:
            raise ValueError(f"Invalid checkpoint {checkpoint_id}, available: 0-{self._n_checkpoints - 1}")
        self._pending = BacktrackRequest(checkpoint_id=checkpoint_id, note=note)
        return "Backtrack scheduled"
    
    def fetch_pending(self) -> BacktrackRequest | None:
        """获取并清除待处理的 Backtrack 请求"""
        pending = self._pending
        self._pending = None
        return pending
```

### 3.5 Backtrack 工具

**文件**: `src/klaude_code/core/tool/backtrack/__init__.py`
```python
from klaude_code.core.tool.backtrack.backtrack_tool import BacktrackTool

__all__ = ["BacktrackTool"]
```

**文件**: `src/klaude_code/core/tool/backtrack/backtrack_tool.py`
```python
from pathlib import Path
from pydantic import BaseModel, Field

from klaude_code.core.tool.context import ToolContext
from klaude_code.core.tool.tool_abc import ToolABC, load_desc
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol import llm_param, message, tools


class BacktrackArguments(BaseModel):
    checkpoint_id: int = Field(description="The checkpoint ID to revert to")
    note: str = Field(description="A note to your future self with key findings/context to preserve")


@register(tools.BACKTRACK)
class BacktrackTool(ToolABC):
    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name=tools.BACKTRACK,
            type="function",
            description=load_desc(Path(__file__).parent / "backtrack_tool.md"),
            parameters={
                "type": "object",
                "properties": {
                    "checkpoint_id": {
                        "type": "integer",
                        "description": "The checkpoint ID to revert to",
                    },
                    "note": {
                        "type": "string",
                        "description": "A note to your future self with key findings/context",
                    },
                },
                "required": ["checkpoint_id", "note"],
                "additionalProperties": False,
            },
        )

    @classmethod
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        try:
            args = BacktrackArguments.model_validate_json(arguments)
        except ValueError as e:
            return message.ToolResultMessage(status="error", output_text=f"Invalid arguments: {e}")

        backtrack_manager = context.backtrack_manager
        if backtrack_manager is None:
            return message.ToolResultMessage(
                status="error",
                output_text="Backtrack is not available in this context",
            )

        try:
            result = backtrack_manager.send_backtrack(args.checkpoint_id, args.note)
            return message.ToolResultMessage(
                status="success",
                output_text=result,
            )
        except ValueError as e:
            return message.ToolResultMessage(status="error", output_text=str(e))
```

**文件**: `src/klaude_code/core/tool/backtrack/backtrack_tool.md`
```markdown
Revert conversation history to a previous checkpoint, discarding everything after it.

Use this tool when:
- You've spent many tokens on exploration that turned out to be unproductive
- You read large files but only need to keep key information
- A deep debugging session can be summarized before continuing
- The current approach is stuck and you want to try differently from an earlier point

The note you provide will be shown to your future self at the checkpoint, so include:
- Key findings from your exploration
- What approaches didn't work and why
- Any important context needed to continue

IMPORTANT:
- File system changes are NOT reverted - only conversation history is affected
- Checkpoints are created automatically at the start of each turn
- Available checkpoints are shown as <system>Checkpoint N</system> in the conversation
```

### 3.6 Session 扩展

**文件**: `src/klaude_code/session/session.py` (修改)

```python
class Session(BaseModel):
    # ... 现有字段 ...
    
    # 新增: 检查点计数器 (需要持久化)
    next_checkpoint_id: int = 0
    
    @property
    def n_checkpoints(self) -> int:
        return self.next_checkpoint_id
    
    def create_checkpoint(self) -> int:
        """创建新检查点，插入 DeveloperMessage 标记，返回检查点 ID"""
        checkpoint_id = self.next_checkpoint_id
        self.next_checkpoint_id += 1
        
        # 插入检查点标记作为 DeveloperMessage
        # 通过 attach_developer_messages() 会自动附加到前一条 UserMessage/ToolResultMessage
        checkpoint_msg = message.DeveloperMessage(
            parts=[message.TextPart(text=f"<system>Checkpoint {checkpoint_id}</system>")]
        )
        self.append_history([checkpoint_msg])
        
        return checkpoint_id
    
    def find_checkpoint_index(self, checkpoint_id: int) -> int | None:
        """找到指定检查点的 DeveloperMessage 索引"""
        target_text = f"<system>Checkpoint {checkpoint_id}</system>"
        for i, item in enumerate(self.conversation_history):
            if isinstance(item, message.DeveloperMessage):
                text = message.join_text_parts(item.parts)
                if target_text in text:
                    return i
        return None
    
    def get_user_message_before_checkpoint(self, checkpoint_id: int) -> str | None:
        """获取检查点之前最近的用户消息内容 (用于 UI 展示)"""
        checkpoint_idx = self.find_checkpoint_index(checkpoint_id)
        if checkpoint_idx is None:
            return None
        
        # 向前查找最近的 UserMessage
        for i in range(checkpoint_idx - 1, -1, -1):
            item = self.conversation_history[i]
            if isinstance(item, message.UserMessage):
                return message.join_text_parts(item.parts)
        return None
    
    def revert_to_checkpoint(self, checkpoint_id: int, note: str) -> message.BacktrackEntry:
        """回退到指定检查点，返回 BacktrackEntry 用于记录"""
        target_idx = self.find_checkpoint_index(checkpoint_id)
        if target_idx is None:
            raise ValueError(f"Checkpoint {checkpoint_id} not found")
        
        # 获取用户消息用于 UI 展示
        user_message = self.get_user_message_before_checkpoint(checkpoint_id) or ""
        
        # 记录回退信息
        reverted_from = len(self.conversation_history)
        entry = message.BacktrackEntry(
            checkpoint_id=checkpoint_id,
            note=note,
            reverted_from_index=reverted_from,
            original_user_message=user_message,
        )
        
        # 截断历史到检查点之后（保留检查点 DeveloperMessage 本身）
        self.conversation_history = self.conversation_history[:target_idx + 1]
        
        # 重置检查点计数器
        self.next_checkpoint_id = checkpoint_id + 1
        
        # 使缓存失效
        self._invalidate_messages_count_cache()
        
        return entry
    
    def get_llm_history(self) -> list[message.HistoryEvent]:
        """返回 LLM 面向的历史视图"""
        # ... 现有的 compaction 处理逻辑 ...
        
        result = []
        for item in history:
            match item:
                case message.BacktrackEntry() as be:
                    # 转换为 DeveloperMessage，注入给 LLM
                    result.append(message.DeveloperMessage(
                        parts=[message.TextPart(text=f"<system>Note from your future self: {be.note}</system>")]
                    ))
                case message.CompactionEntry():
                    # 已有逻辑
                    ...
                case _:
                    result.append(item)
        return result
```

### 3.7 事件定义

**文件**: `src/klaude_code/protocol/events.py` (修改)

```python
# 新增事件
class BacktrackEvent(Event):
    """Backtrack 完成事件，包含 UI 展示所需的全部信息"""
    checkpoint_id: int
    note: str
    original_user_message: str      # 检查点对应的用户消息 (UI 重新展示)
    messages_discarded: int | None = None


# 更新 __all__
__all__ = [
    # ... 现有导出 ...
    "BacktrackEvent",
]

# 更新 ReplayEventUnion
type ReplayEventUnion = (
    # ... 现有类型 ...
    | BacktrackEvent
)
```

### 3.6 工具名称常量

**文件**: `src/klaude_code/protocol/tools.py` (修改)

```python
# 新增
BACKTRACK = "Backtrack"
```

### 3.7 ToolContext 扩展

**文件**: `src/klaude_code/core/tool/context.py` (修改)

```python
from klaude_code.core.backtrack import BacktrackManager

@dataclass(frozen=True)
class ToolContext:
    file_tracker: FileTracker
    todo_context: TodoContext
    session_id: str
    run_subtask: RunSubtask | None = None
    sub_agent_resume_claims: SubAgentResumeClaims | None = None
    record_sub_agent_session_id: Callable[[str], None] | None = None
    register_sub_agent_metadata_getter: Callable[[GetMetadataFn], None] | None = None
    backtrack_manager: BacktrackManager | None = None  # 新增
    
    def with_backtrack_manager(self, manager: BacktrackManager | None) -> ToolContext:
        return replace(self, backtrack_manager=manager)
```

### 3.8 TaskExecutor 集成

**文件**: `src/klaude_code/core/task.py` (修改)

```python
from klaude_code.core.backtrack import BacktrackManager

class TaskExecutor:
    def __init__(self, context: TaskExecutionContext) -> None:
        self._context = context
        self._backtrack_manager: BacktrackManager | None = None
        # ... 其他字段 ...
    
    async def run(self, user_input: message.UserInputPayload) -> AsyncGenerator[events.Event]:
        ctx = self._context
        session_ctx = ctx.session_ctx
        
        # 初始化 BacktrackManager（仅主 Agent，子 Agent 不支持）
        if ctx.sub_agent_state is None:
            self._backtrack_manager = BacktrackManager()
        
        yield events.TaskStartEvent(...)
        
        while True:
            # 每个 turn 开始时创建检查点
            if self._backtrack_manager is not None:
                checkpoint_id = ctx.session.create_checkpoint()
                self._backtrack_manager.set_n_checkpoints(ctx.session.n_checkpoints)
                
                # 注册检查点对应的用户消息 (用于 UI 展示)
                user_msg = ctx.session.get_user_message_before_checkpoint(checkpoint_id)
                if user_msg:
                    self._backtrack_manager.register_checkpoint(checkpoint_id, user_msg)
            
            # ... 现有的 compaction 检查 ...
            
            # ... turn 执行循环 ...
            
            # turn 结束后检查是否有 pending backtrack
            if self._backtrack_manager is not None:
                if pending := self._backtrack_manager.fetch_pending():
                    entry = ctx.session.revert_to_checkpoint(pending.checkpoint_id, pending.note)
                    
                    # 追加 BacktrackEntry 到历史
                    session_ctx.append_history([entry])
                    
                    # 注入备注消息给 LLM（作为 DeveloperMessage）
                    note_message = message.DeveloperMessage(
                        parts=[message.TextPart(text=f"<system>Note from your future self: {pending.note}</system>")]
                    )
                    session_ctx.append_history([note_message])
                    
                    # 发送事件给 UI
                    yield events.BacktrackEvent(
                        session_id=session_ctx.session_id,
                        checkpoint_id=pending.checkpoint_id,
                        note=pending.note,
                        original_user_message=entry.original_user_message,
                        messages_discarded=entry.reverted_from_index - len(ctx.session.conversation_history),
                    )
                    
                    # 继续循环，从新检查点开始
                    continue
            
            # ... 现有的 task 完成判断 ...
```

### 3.9 TUI 状态机处理

**文件**: `src/klaude_code/tui/machine.py` (修改)

```python
# 在 process_event() 中添加处理
case events.BacktrackEvent() as e:
    if not is_replay:
        cmds.append(RenderBacktrack(
            checkpoint_id=e.checkpoint_id,
            note=e.note,
            original_user_message=e.original_user_message,
            messages_discarded=e.messages_discarded,
        ))
    return cmds
```

### 3.10 渲染命令

**文件**: `src/klaude_code/tui/commands.py` (修改)

```python
@dataclass(frozen=True)
class RenderBacktrack(RenderCommand):
    checkpoint_id: int
    note: str
    original_user_message: str      # 重新展示的用户消息
    messages_discarded: int | None = None
```

### 3.11 UI 渲染

**文件**: `src/klaude_code/tui/renderer.py` (修改)

```python
def display_backtrack(
    self, 
    checkpoint_id: int, 
    note: str, 
    original_user_message: str,
    messages_discarded: int | None,
) -> None:
    """显示 Backtrack 结果，重新展示对应的用户消息"""
    
    # 1. 显示回退分隔线
    self.console.print(
        Rule(
            Text(f"Backtracked to Checkpoint {checkpoint_id}", style=ThemeKey.BACKTRACK),
            characters="=",
            style=ThemeKey.LINES,
        )
    )
    self.print()
    
    # 2. 显示丢弃的消息数量
    if messages_discarded:
        self.console.print(
            Text(f"  Discarded {messages_discarded} messages", style=ThemeKey.BACKTRACK_INFO)
        )
    
    # 3. 重新展示对应的用户消息 (让用户知道回到了哪里)
    if original_user_message:
        self.console.print(
            Text("  Returned to:", style=ThemeKey.BACKTRACK_INFO)
        )
        # 截断过长的消息
        msg_preview = original_user_message[:200] + "..." if len(original_user_message) > 200 else original_user_message
        # 用引用格式展示
        self.console.print(
            Padding(
                Panel(
                    Text(msg_preview, style=ThemeKey.BACKTRACK_USER_MESSAGE),
                    box=box.SIMPLE,
                    border_style=ThemeKey.LINES,
                ),
                (0, 0, 0, 4),
            )
        )
    
    # 4. 显示备注摘要
    self.console.print(
        Text("  Note from future:", style=ThemeKey.BACKTRACK_INFO)
    )
    note_preview = note[:300] + "..." if len(note) > 300 else note
    self.console.print(
        Padding(
            Panel(
                NoInsetMarkdown(note_preview, code_theme=self.themes.code_theme),
                box=box.SIMPLE,
                border_style=ThemeKey.LINES,
                style=ThemeKey.BACKTRACK_NOTE,
            ),
            (0, 0, 0, 4),
        )
    )
    
    self.print()
```

**UI 效果示例**:
```
============ Backtracked to Checkpoint 2 ============

  Discarded 15 messages
  Returned to:
    ┌────────────────────────────────────────────────┐
    │ 帮我分析一下这个文件的结构                      │
    └────────────────────────────────────────────────┘
  Note from future:
    ┌────────────────────────────────────────────────┐
    │ 文件结构分析完成:                               │
    │ - 主入口在 main.py                             │
    │ - 核心逻辑在 core/ 目录                        │
    │ - 之前尝试的方法 X 不可行，因为...              │
    └────────────────────────────────────────────────┘

```

### 3.12 主题颜色

**文件**: `src/klaude_code/tui/components/rich/theme.py` (修改)

```python
class ThemeKey(StrEnum):
    # ... 现有定义 ...
    BACKTRACK = "backtrack"
    BACKTRACK_INFO = "backtrack_info"
    BACKTRACK_USER_MESSAGE = "backtrack_user_message"
    BACKTRACK_NOTE = "backtrack_note"

# 在主题定义中添加颜色
# BACKTRACK: yellow/orange (标题)
# BACKTRACK_INFO: dim white (信息文字)
# BACKTRACK_USER_MESSAGE: cyan (用户消息)
# BACKTRACK_NOTE: white (备注内容)
```

---

## 四、文件修改清单

### 新建文件
| 路径 | 描述 |
|------|------|
| `src/klaude_code/core/backtrack/__init__.py` | 模块导出 |
| `src/klaude_code/core/backtrack/manager.py` | BacktrackManager 和 BacktrackRequest |
| `src/klaude_code/core/tool/backtrack/__init__.py` | 工具模块导出 |
| `src/klaude_code/core/tool/backtrack/backtrack_tool.py` | Backtrack 工具实现 |
| `src/klaude_code/core/tool/backtrack/backtrack_tool.md` | 工具描述文档 |

### 修改文件
| 路径 | 修改内容 |
|------|----------|
| `src/klaude_code/protocol/message.py` | 添加 BacktrackEntry; 更新 HistoryEvent |
| `src/klaude_code/protocol/events.py` | 添加 BacktrackEvent |
| `src/klaude_code/protocol/tools.py` | 添加 BACKTRACK 常量 |
| `src/klaude_code/core/tool/context.py` | 添加 backtrack_manager 字段 |
| `src/klaude_code/core/tool/__init__.py` | 导出 BacktrackTool |
| `src/klaude_code/core/tool/tool_runner.py` | 传递 backtrack_manager 到 ToolContext |
| `src/klaude_code/core/task.py` | 集成检查点创建和回退逻辑 |
| `src/klaude_code/session/session.py` | 添加 create_checkpoint(), find_checkpoint_index(), get_user_message_before_checkpoint(), revert_to_checkpoint(); 更新 get_llm_history() |
| `src/klaude_code/tui/machine.py` | 处理 BacktrackEvent |
| `src/klaude_code/tui/commands.py` | 添加 RenderBacktrack |
| `src/klaude_code/tui/renderer.py` | 添加 display_backtrack() |
| `src/klaude_code/tui/components/rich/theme.py` | 添加 BACKTRACK 相关主题键 |

---

## 五、Action Items

- [ ] 在 `src/klaude_code/protocol/message.py` 添加 `BacktrackEntry` 模型，更新 `HistoryEvent` union
- [ ] 创建 `src/klaude_code/core/backtrack/` 模块，实现 `BacktrackManager` 和 `BacktrackRequest`
- [ ] 创建 `src/klaude_code/core/tool/backtrack/` 模块，实现 `BacktrackTool`
- [ ] 在 `src/klaude_code/protocol/tools.py` 添加 `BACKTRACK` 常量
- [ ] 扩展 `ToolContext` 添加 `backtrack_manager` 字段
- [ ] 扩展 `Session` 添加 `create_checkpoint()`、`find_checkpoint_index()`、`get_user_message_before_checkpoint()`、`revert_to_checkpoint()` 方法
- [ ] 更新 `Session.get_llm_history()` 处理 BacktrackEntry
- [ ] 在 `src/klaude_code/protocol/events.py` 添加 `BacktrackEvent`
- [ ] 在 `TaskExecutor.run()` 集成检查点创建 (DeveloperMessage) 和 Backtrack 处理逻辑
- [ ] 更新 `tool_runner.py` 传递 `backtrack_manager` 到 `ToolContext`
- [ ] 在 `src/klaude_code/tui/commands.py` 添加 `RenderBacktrack` 命令
- [ ] 在 `src/klaude_code/tui/machine.py` 处理 `BacktrackEvent`
- [ ] 在 `src/klaude_code/tui/renderer.py` 实现 `display_backtrack()` (展示用户消息 + note)
- [ ] 添加 BACKTRACK 相关主题键和颜色定义
- [ ] 编写单元测试: BacktrackManager、Session.revert_to_checkpoint()、BacktrackTool
- [ ] 使用 tmux-test skill 进行端到端测试

---

## 六、补充实现细节

### 6.1 TurnExecutionContext 需要添加 backtrack_manager

**文件**: `src/klaude_code/core/turn.py`

```python
@dataclass
class TurnExecutionContext:
    session_ctx: SessionContext
    llm_client: LLMClientABC
    system_prompt: str | None
    tools: list[llm_param.ToolSchema]
    tool_registry: dict[str, type[ToolABC]]
    sub_agent_state: model.SubAgentState | None = None
    backtrack_manager: BacktrackManager | None = None  # 新增
```

### 6.2 ToolContext 构建位置

**文件**: `src/klaude_code/core/turn.py` (约 401 行)

```python
async def _run_tool_executor(self, tool_calls: list[ToolCallRequest]) -> AsyncGenerator[events.Event]:
    ctx = self._context
    session_ctx = ctx.session_ctx
    tool_context = ToolContext(
        file_tracker=session_ctx.file_tracker,
        todo_context=session_ctx.todo_context,
        session_id=session_ctx.session_id,
        run_subtask=session_ctx.run_subtask,
        sub_agent_resume_claims=SubAgentResumeClaims(),
        backtrack_manager=ctx.backtrack_manager,  # 新增
    )
```

### 6.3 Session 持久化 next_checkpoint_id

**文件**: `src/klaude_code/session/store.py`

在 `build_meta_snapshot()` 添加:
```python
def build_meta_snapshot(
    *,
    # ... 现有参数 ...
    next_checkpoint_id: int = 0,  # 新增
) -> dict[str, Any]:
    return {
        # ... 现有字段 ...
        "next_checkpoint_id": next_checkpoint_id,
    }
```

**文件**: `src/klaude_code/session/session.py`

在 `load_meta()` 中恢复:
```python
next_checkpoint_id = int(raw.get("next_checkpoint_id", 0))

session = Session(
    # ... 现有字段 ...
    next_checkpoint_id=next_checkpoint_id,
)
```

在 `append_history()` 中传递:
```python
meta = build_meta_snapshot(
    # ... 现有参数 ...
    next_checkpoint_id=self.next_checkpoint_id,
)
```

### 6.4 历史回放处理 BacktrackEntry

**文件**: `src/klaude_code/session/session.py`

在 `get_history_item()` 方法中处理 (参考 CompactionEntry 的处理模式，约 440 行):
```python
case message.BacktrackEntry() as be:
    yield events.BacktrackEvent(
        session_id=self.id,
        checkpoint_id=be.checkpoint_id,
        note=be.note,
        original_user_message=be.original_user_message,
        messages_discarded=None,  # 回放时不计算
    )
```

回放时生成的 `BacktrackEvent` 与正向链路一致，TUI Machine 和 Renderer 逻辑完全复用。

### 6.5 Edge Cases 处理

1. **第一个 turn 没有前置 UserMessage**: 
   - `get_user_message_before_checkpoint()` 返回 None
   - BacktrackEntry.original_user_message 为空字符串
   - UI 回退时只显示 note，不显示 "Returned to"

2. **用户消息包含图片**:
   - `join_text_parts()` 只提取文本部分
   - 图片信息不在回退 UI 中展示

3. **Backtrack 回退到被 Compaction 压缩的区域**:
   - 在 `BacktrackManager.send_backtrack()` 中验证
   - 检查点 DeveloperMessage 如果不存在于当前历史中，返回错误

### 6.6 工具注册和导入

**文件**: `src/klaude_code/core/tool/__init__.py`

```python
# 添加导入
from .backtrack.backtrack_tool import BacktrackTool

# 添加到 __all__
__all__ = [
    # ... 现有导出 ...
    "BacktrackTool",
]
```

**文件**: `src/klaude_code/core/agent_profile.py`

在默认工具列表中添加 Backtrack:
```python
# 约 174 行
tool_names = [tools.BASH, tools.READ, tools.EDIT, tools.WRITE, tools.TODO_WRITE, tools.BACKTRACK]
```

### 6.7 循环引用说明

ToolContext 需要导入 BacktrackManager:
```python
# src/klaude_code/core/tool/context.py
from klaude_code.core.backtrack import BacktrackManager
```

这不会产生循环引用，因为:
- `backtrack/manager.py` 只依赖 dataclasses，不导入 tool 模块
- `backtrack_tool.py` 导入 `ToolContext` 是在运行时使用，不影响模块加载

### 6.8 修改文件清单补充

| 路径 | 修改内容 |
|------|----------|
| `src/klaude_code/core/turn.py` | TurnExecutionContext 添加 backtrack_manager; ToolContext 构建时传入 |
| `src/klaude_code/session/store.py` | build_meta_snapshot 添加 next_checkpoint_id |
| `src/klaude_code/core/agent_profile.py` | 默认工具列表添加 BACKTRACK |

---

## 七、Open Questions

1. **与 Compaction 的交互**: 如果 Backtrack 回退到一个已被 Compaction 压缩的区域，应该如何处理？
   - 建议: 禁止回退到被压缩的检查点（检查点 ID 必须 >= compaction 保留的起始索引对应的检查点）
