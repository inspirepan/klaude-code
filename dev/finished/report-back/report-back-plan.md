# Report Back: Sub-Agent Structured Output

**Last Updated: 2025-12-09**

## Executive Summary

实现 `report_back` 工具，使父 agent 能够在调用子 agent 时定义 JSON Schema，子 agent 通过调用 `report_back` 工具返回结构化数据并结束任务。这将为父 agent 提供对子 agent 输出格式的精确控制能力。

### Key Goals

1. 父 agent 可以在调用 sub-agent 时动态传入 `output_schema`
2. 子 agent 获得 `report_back` 工具，其参数 schema 由父 agent 定义
3. 调用 `report_back` 触发任务结束，参数作为结构化输出返回
4. 向后兼容：不传 `output_schema` 时行为不变

---

## Current State Analysis

### 任务结束逻辑

```
TaskExecutor.run()
  └── while True:
        └── TurnExecutor.run()
              └── 检查 turn.has_tool_call
        └── if not turn.has_tool_call: break
  └── task_result = _get_last_assistant_message()
```

**问题**: 只能通过最后一条 assistant message 获取结果，无法返回结构化数据。

### 工具加载流程

```
SubAgentManager.run_sub_agent()
  └── model_profile_provider.build_profile(client, sub_agent_type)
        └── DefaultModelProfileProvider.build_profile()
              └── load_agent_tools(model_name, sub_agent_type)
                    └── get_tool_schemas(profile.tool_set)
```

**问题**: 工具集在 `SubAgentProfile.tool_set` 中静态定义，无法动态添加工具。

### 数据传递

```
SubAgentTool.call()
  └── SubAgentState(sub_agent_type, desc, prompt)  # 无 output_schema
        └── SubAgentManager.run_sub_agent()
              └── 子 agent 无法知道期望的输出格式
```

---

## Proposed Future State

### 数据流

```
┌─────────────────────────────────────────────────────────────────┐
│ 父 Agent                                                         │
│  调用 Task(prompt="...", output_schema={...})                   │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ SubAgentTool.call()                                              │
│  output_schema = args.get(profile.output_schema_arg)            │
│  SubAgentState(..., output_schema=output_schema)                │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ SubAgentManager.run_sub_agent()                                  │
│  if state.output_schema:                                        │
│      tools += [ReportBackTool.for_schema(state.output_schema)]  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ 子 Agent                                                         │
│  tools: [Bash, Read, Edit, Write, report_back]                  │
│  执行任务 -> 调用 report_back(result)                            │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ TurnExecutor                                                     │
│  检测 report_back 调用 -> 设置 report_back_result               │
│  触发任务提前结束                                                │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ TaskExecutor                                                     │
│  检测 turn.has_report_back -> break                             │
│  task_result = JSON(report_back_result)                         │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ SubAgentResult                                                   │
│  task_result: str (JSON)                                        │
│  structured_output: dict (parsed)                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## Implementation Phases

### Phase 1: Data Model Extensions

扩展核心数据模型以支持 output_schema 传递。

| Task | Description | Effort | Dependencies |
|------|-------------|--------|--------------|
| 1.1 | SubAgentState 添加 output_schema 字段 | S | - |
| 1.2 | SubAgentProfile 添加 output_schema_arg 字段 | S | - |
| 1.3 | SubAgentResult 添加 structured_output 字段 | S | - |

### Phase 2: Report Back Tool

实现 report_back 工具本身。

| Task | Description | Effort | Dependencies |
|------|-------------|--------|--------------|
| 2.1 | 创建 ReportBackTool 类 | M | 1.1 |
| 2.2 | 实现动态 schema 生成 (for_schema) | M | 2.1 |
| 2.3 | 定义 REPORT_BACK_TOOL_NAME 常量 | S | - |

### Phase 3: Turn/Task Executor Modifications

修改任务执行逻辑以支持 report_back 触发结束。

| Task | Description | Effort | Dependencies |
|------|-------------|--------|--------------|
| 3.1 | TurnResult 添加 report_back_result 字段 | S | 2.3 |
| 3.2 | TurnExecutor 添加 report_back 检测逻辑 | M | 3.1 |
| 3.3 | TurnExecutor 添加 has_report_back 属性 | S | 3.2 |
| 3.4 | TaskExecutor 修改结束条件 | M | 3.3 |
| 3.5 | TaskExecutor 修改结果获取逻辑 | M | 3.4, 1.3 |

### Phase 4: Tool Injection

在子 agent 构建时动态注入 report_back 工具。

| Task | Description | Effort | Dependencies |
|------|-------------|--------|--------------|
| 4.1 | SubAgentTool.call() 提取 output_schema | M | 1.1, 1.2 |
| 4.2 | 修改 load_agent_tools 支持动态工具 | M | 2.1 |
| 4.3 | SubAgentManager 传递 output_schema 给工具加载 | M | 4.2 |
| 4.4 | 或: 创建新的 ProfileProvider 支持动态工具 | L | 4.2 |

### Phase 5: Sub-Agent Profile Updates

更新现有 sub-agent profiles 支持 output_schema。

| Task | Description | Effort | Dependencies |
|------|-------------|--------|--------------|
| 5.1 | Task profile 添加 output_schema 参数 | S | 1.2 |
| 5.2 | 更新 Task description 说明 output_schema | S | 5.1 |
| 5.3 | (Optional) Explore profile 添加支持 | S | 5.1 |

### Phase 6: Testing

| Task | Description | Effort | Dependencies |
|------|-------------|--------|--------------|
| 6.1 | ReportBackTool 单元测试 | M | 2.x |
| 6.2 | TurnExecutor report_back 检测测试 | M | 3.x |
| 6.3 | TaskExecutor 结束条件测试 | M | 3.x |
| 6.4 | 端到端集成测试 | L | All |

---

## Detailed Tasks

### 1.1 SubAgentState 添加 output_schema 字段

**File**: `src/klaude_code/protocol/model.py`

```python
class SubAgentState(BaseModel):
    sub_agent_type: SubAgentType
    sub_agent_desc: str
    sub_agent_prompt: str
    output_schema: dict[str, Any] | None = None  # NEW
```

**Acceptance Criteria**:
- [ ] 字段类型为 `dict[str, Any] | None`，默认 None
- [ ] 现有代码不受影响（向后兼容）

---

### 1.2 SubAgentProfile 添加 output_schema_arg 字段

**File**: `src/klaude_code/protocol/sub_agent/__init__.py`

```python
@dataclass(frozen=True)
class SubAgentProfile:
    # ... existing fields ...
    output_schema_arg: str | None = None  # NEW: 指向 parameters 中的字段名
```

**Acceptance Criteria**:
- [ ] 字段类型为 `str | None`，默认 None
- [ ] 不设置时，子 agent 不支持结构化输出

---

### 1.3 SubAgentResult 添加 structured_output 字段

**File**: `src/klaude_code/protocol/sub_agent/__init__.py`

```python
@dataclass
class SubAgentResult:
    task_result: str
    session_id: str
    error: bool = False
    task_metadata: model.TaskMetadata | None = None
    structured_output: dict[str, Any] | None = None  # NEW
```

**Acceptance Criteria**:
- [ ] 字段类型为 `dict[str, Any] | None`，默认 None
- [ ] 当子 agent 调用 report_back 时填充此字段

---

### 2.1 创建 ReportBackTool 类

**File**: `src/klaude_code/core/tool/report_back_tool.py` (新文件)

```python
class ReportBackTool(ToolABC):
    """Special tool for sub-agents to return structured output and end the task."""
    
    _schema: ClassVar[dict[str, Any]]
    
    @classmethod
    def for_schema(cls, schema: dict[str, Any]) -> type[ReportBackTool]:
        """Create a tool class with the specified output schema."""
        return type("ReportBackTool", (ReportBackTool,), {"_schema": schema})
    
    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name=REPORT_BACK_TOOL_NAME,
            type="function",
            description="Report the final structured result back to the parent agent. Call this when you have completed the task and want to return structured data.",
            parameters=cls._schema,
        )
    
    @classmethod
    async def call(cls, arguments: str) -> model.ToolResultItem:
        # Just validate and return success - actual handling in TurnExecutor
        return model.ToolResultItem(
            status="success",
            output="Result reported successfully.",
        )
```

**Acceptance Criteria**:
- [ ] 继承 ToolABC
- [ ] for_schema 返回动态子类
- [ ] schema() 使用传入的 schema 作为 parameters
- [ ] call() 返回成功结果

---

### 2.3 定义 REPORT_BACK_TOOL_NAME 常量

**File**: `src/klaude_code/protocol/tools.py`

```python
REPORT_BACK = "report_back"
```

**Acceptance Criteria**:
- [ ] 常量定义在 tools.py 中
- [ ] 其他模块通过 import 使用此常量

---

### 3.2 TurnExecutor 添加 report_back 检测逻辑

**File**: `src/klaude_code/core/turn.py`

在 `_run_tool_executor` 之前检测 report_back:

```python
async def run(self) -> AsyncGenerator[events.Event]:
    # ... existing code ...
    
    if self._turn_result.tool_calls:
        # Check for report_back before running tools
        for tool_call in self._turn_result.tool_calls:
            if tool_call.name == tools.REPORT_BACK:
                self._turn_result.report_back_result = json.loads(tool_call.arguments)
                break
        
        async for ui_event in self._run_tool_executor(self._turn_result.tool_calls):
            yield ui_event
```

**Acceptance Criteria**:
- [ ] 在 tool_calls 中检测 report_back
- [ ] 解析 arguments 并存入 report_back_result
- [ ] 继续执行工具（包括 report_back）以保持历史记录完整

---

### 3.4 TaskExecutor 修改结束条件

**File**: `src/klaude_code/core/task.py`

```python
while True:
    # ... turn execution ...
    
    if turn is None or not turn.has_tool_call:
        break
    
    # NEW: report_back also triggers task end
    if turn.has_report_back:
        break
```

**Acceptance Criteria**:
- [ ] 检测 turn.has_report_back
- [ ] report_back 调用后任务结束

---

### 3.5 TaskExecutor 修改结果获取逻辑

**File**: `src/klaude_code/core/task.py`

```python
# Get task result
if turn and turn.report_back_result is not None:
    task_result = json.dumps(turn.report_back_result)
    structured_output = turn.report_back_result
else:
    task_result = _get_last_assistant_message(session_ctx.get_conversation_history()) or ""
    structured_output = None

yield events.TaskFinishEvent(
    session_id=session_ctx.session_id,
    task_result=task_result,
    structured_output=structured_output,  # NEW
)
```

**Acceptance Criteria**:
- [ ] 有 report_back 时使用其参数作为 task_result
- [ ] structured_output 传递到 TaskFinishEvent

---

### 4.1 SubAgentTool.call() 提取 output_schema

**File**: `src/klaude_code/core/tool/sub_agent_tool.py`

```python
@classmethod
async def call(cls, arguments: str) -> model.ToolResultItem:
    profile = cls._profile
    args = json.loads(arguments)
    
    # Extract output_schema if configured
    output_schema = None
    if profile.output_schema_arg:
        output_schema = args.get(profile.output_schema_arg)
    
    result = await runner(
        model.SubAgentState(
            sub_agent_type=profile.name,
            sub_agent_desc=description,
            sub_agent_prompt=prompt,
            output_schema=output_schema,  # NEW
        )
    )
```

**Acceptance Criteria**:
- [ ] 根据 output_schema_arg 提取 schema
- [ ] 传递给 SubAgentState

---

### 4.3 SubAgentManager 传递 output_schema 给工具加载

**File**: `src/klaude_code/core/manager/sub_agent_manager.py`

需要修改 profile 构建逻辑，在有 output_schema 时添加 report_back 工具。

方案 A: 修改 load_agent_tools 签名
方案 B: 在 SubAgentManager 中手动添加工具

推荐方案 B，更简单直接:

```python
async def run_sub_agent(self, parent_agent: Agent, state: model.SubAgentState) -> SubAgentResult:
    child_profile = self._model_profile_provider.build_profile(
        self._llm_clients.get_client(state.sub_agent_type),
        state.sub_agent_type,
    )
    
    # Inject report_back tool if output_schema is provided
    if state.output_schema:
        report_back_tool = ReportBackTool.for_schema(state.output_schema)
        child_profile = AgentProfile(
            llm_client=child_profile.llm_client,
            system_prompt=child_profile.system_prompt,
            tools=[*child_profile.tools, report_back_tool.schema()],
            reminders=child_profile.reminders,
        )
        # Also register the tool dynamically
        ...
```

**Acceptance Criteria**:
- [ ] 有 output_schema 时添加 report_back 工具
- [ ] 工具 schema 使用传入的 output_schema
- [ ] 工具注册到 tool_registry（需要考虑并发安全）

---

### 5.1 Task profile 添加 output_schema 参数

**File**: `src/klaude_code/protocol/sub_agent/task.py`

```python
TASK_PARAMETERS = {
    "type": "object",
    "properties": {
        "description": {...},
        "prompt": {...},
        "output_schema": {  # NEW
            "type": "object",
            "description": "Optional JSON Schema for structured output. When provided, the agent will have a 'report_back' tool to return data matching this schema.",
        },
    },
    "required": ["description", "prompt"],
    "additionalProperties": False,
}

register_sub_agent(
    SubAgentProfile(
        name="Task",
        description=TASK_DESCRIPTION,
        parameters=TASK_PARAMETERS,
        output_schema_arg="output_schema",  # NEW
        # ...
    )
)
```

**Acceptance Criteria**:
- [ ] output_schema 参数添加到 TASK_PARAMETERS
- [ ] output_schema_arg 设置为 "output_schema"

---

## Risk Assessment

### Risk 1: 并发安全问题

**描述**: 动态注册 report_back 工具到全局 registry 可能导致并发问题。

**缓解**: 
- 方案 A: 使用 thread-safe registry
- 方案 B: 为每个子 session 创建独立的 tool_registry 副本
- 方案 C: 不注册到全局 registry，在 TurnExecutor 中特殊处理

**推荐**: 方案 C - 在 `run_tool` 之前检查是否为 report_back，单独处理

### Risk 2: Schema 验证

**描述**: report_back 参数可能不符合 output_schema。

**缓解**: 
- 在 ReportBackTool.call() 中使用 jsonschema 验证
- 验证失败返回 error 状态

### Risk 3: 多次调用 report_back

**描述**: 子 agent 可能在一个 turn 中多次调用 report_back。

**缓解**: 只取第一次调用的结果，后续调用返回错误或忽略。

---

## Success Metrics

1. **功能完整性**: 父 agent 能够传入 output_schema，子 agent 能够通过 report_back 返回结构化数据
2. **向后兼容**: 不使用 output_schema 时，行为与现有完全一致
3. **测试覆盖**: 核心逻辑测试覆盖率 > 80%
4. **性能**: 无明显性能回归

---

## Dependencies

### External Dependencies
- jsonschema (可选，用于 schema 验证)

### Internal Dependencies
- protocol/model.py
- protocol/sub_agent/__init__.py
- core/tool/tool_abc.py
- core/tool/tool_registry.py
- core/turn.py
- core/task.py
- core/manager/sub_agent_manager.py
- core/agent.py

---

## Open Questions

1. **report_back 后是否执行其他工具?** 
   - 建议: 执行，保持历史记录完整，但任务随后结束

2. **是否需要在 system prompt 中提示 report_back 工具的存在?**
   - 建议: 是的，应该告知子 agent 需要使用 report_back 返回结果

3. **structured_output 是否需要添加到 events.TaskFinishEvent?**
   - 建议: 是的，以便 UI 层可以访问

4. **工具注册并发问题的解决方案选择?**
   - 需要进一步讨论
