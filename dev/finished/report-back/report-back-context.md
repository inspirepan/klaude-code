# Report Back: Context Document

**Last Updated: 2025-12-09**

## Key Files

### Protocol Layer

| File | Purpose | Modifications Needed |
|------|---------|---------------------|
| `src/klaude_code/protocol/model.py` | Data models | Add `output_schema` to `SubAgentState` |
| `src/klaude_code/protocol/tools.py` | Tool constants | Add `REPORT_BACK` constant |
| `src/klaude_code/protocol/sub_agent/__init__.py` | Sub-agent profile | Add `output_schema_arg` to `SubAgentProfile`, `structured_output` to `SubAgentResult` |
| `src/klaude_code/protocol/sub_agent/task.py` | Task sub-agent | Add `output_schema` parameter |
| `src/klaude_code/protocol/events.py` | Event definitions | Add `structured_output` to `TaskFinishEvent` |

### Core Layer

| File | Purpose | Modifications Needed |
|------|---------|---------------------|
| `src/klaude_code/core/tool/report_back_tool.py` | **NEW** | ReportBackTool implementation |
| `src/klaude_code/core/tool/sub_agent_tool.py` | Sub-agent tool | Extract `output_schema` from args |
| `src/klaude_code/core/tool/tool_registry.py` | Tool registry | May need modification for dynamic tools |
| `src/klaude_code/core/turn.py` | Turn execution | Detect `report_back`, add `has_report_back` |
| `src/klaude_code/core/task.py` | Task execution | Modify end condition, result extraction |
| `src/klaude_code/core/manager/sub_agent_manager.py` | Sub-agent manager | Inject `report_back` tool |
| `src/klaude_code/core/agent.py` | Agent | May need profile modification support |

---

## Key Code Snippets

### Current SubAgentState (model.py:144-148)

```python
class SubAgentState(BaseModel):
    sub_agent_type: SubAgentType
    sub_agent_desc: str
    sub_agent_prompt: str
```

### Current SubAgentProfile (sub_agent/__init__.py:29-68)

```python
@dataclass(frozen=True)
class SubAgentProfile:
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    prompt_file: str = ""
    tool_set: tuple[str, ...] = ()
    prompt_builder: PromptBuilder = _default_prompt_builder
    active_form: str = ""
    enabled_by_default: bool = True
    show_in_main_agent: bool = True
    target_model_filter: AvailabilityPredicate | None = None
```

### Current Task End Logic (task.py:156-220)

```python
while True:
    # ... turn execution with retries ...
    
    if turn is None or not turn.has_tool_call:
        break

# Get result
yield events.TaskFinishEvent(
    session_id=session_ctx.session_id,
    task_result=_get_last_assistant_message(session_ctx.get_conversation_history()) or "",
)
```

### Current Tool Loading (tool_registry.py:50-65)

```python
def load_agent_tools(
    model_name: str, sub_agent_type: tools.SubAgentType | None = None, *, vanilla: bool = False
) -> list[llm_param.ToolSchema]:
    if sub_agent_type is not None:
        profile = get_sub_agent_profile(sub_agent_type)
        return get_tool_schemas(list(profile.tool_set))
    # ...
```

### Current Sub-Agent Profile Building (sub_agent_manager.py:46-50)

```python
child_profile = self._model_profile_provider.build_profile(
    self._llm_clients.get_client(state.sub_agent_type),
    state.sub_agent_type,
)
child_agent = Agent(session=child_session, profile=child_profile)
```

---

## Design Decisions

### Decision 1: output_schema 传递方式

**选择**: 通过 `SubAgentProfile.output_schema_arg` 标注参数名

**理由**:
- 更灵活，不同 sub-agent 可以用不同的参数名
- Schema 定义在 parameters 中，与其他参数一起维护
- Profile 只存标注，不存 schema 值

**替代方案被否决**:
- 静态配置在 profile 中 - 不够灵活，无法动态传入
- 同时支持静态+动态 - 过于复杂

### Decision 2: report_back 工具注册

**选择**: 在 SubAgentManager 中动态注入，不注册到全局 registry

**理由**:
- 避免全局 registry 并发问题
- report_back 只对特定子 session 有效
- 更清晰的生命周期管理

**实现方式**:
1. 创建子 agent profile 后，检查 `state.output_schema`
2. 如果存在，创建新的 AgentProfile，tools 列表添加 report_back schema
3. 在 tool_runner 或 turn 中特殊处理 report_back 调用

### Decision 3: 任务结束时机

**选择**: report_back 工具执行完成后，任务立即结束

**理由**:
- report_back 的语义就是"报告结果并结束"
- 避免子 agent 在 report_back 后继续执行无意义的操作

**行为**:
- 同一 turn 中 report_back 之后的工具仍会执行（保持序列完整）
- 但 task 循环会在这个 turn 后结束

### Decision 4: 结果获取优先级

**选择**: report_back 结果 > 最后 assistant message

**逻辑**:
```python
if turn.report_back_result:
    task_result = json.dumps(turn.report_back_result)
else:
    task_result = _get_last_assistant_message()
```

---

## Type Definitions Summary

### New Types

```python
# protocol/model.py
class SubAgentState(BaseModel):
    output_schema: dict[str, Any] | None = None  # NEW

# protocol/sub_agent/__init__.py
@dataclass(frozen=True)
class SubAgentProfile:
    output_schema_arg: str | None = None  # NEW

@dataclass
class SubAgentResult:
    structured_output: dict[str, Any] | None = None  # NEW

# core/turn.py
@dataclass
class TurnResult:
    report_back_result: dict[str, Any] | None = None  # NEW
```

### New Classes

```python
# core/tool/report_back_tool.py
class ReportBackTool(ToolABC):
    _schema: ClassVar[dict[str, Any]]
    
    @classmethod
    def for_schema(cls, schema: dict[str, Any]) -> type[ReportBackTool]: ...
```

---

## Testing Strategy

### Unit Tests

1. **ReportBackTool**
   - `for_schema` 创建正确的子类
   - `schema()` 返回正确的 ToolSchema
   - `call()` 返回成功结果

2. **TurnExecutor**
   - 检测 report_back 调用
   - 正确解析 arguments
   - `has_report_back` 属性正确

3. **TaskExecutor**
   - report_back 触发任务结束
   - 结果正确提取

### Integration Tests

1. **End-to-End**
   - 父 agent 调用 Task with output_schema
   - 子 agent 使用 report_back 返回结果
   - 父 agent 收到 structured_output

---

## Migration Notes

- 无破坏性变更
- 所有新字段都有默认值
- 不使用 output_schema 时行为不变
