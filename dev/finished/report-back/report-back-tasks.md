# Report Back: Task Checklist

**Last Updated: 2025-12-09** (Phase 1, 2, 3, 4, 5 & 6 completed)

## Phase 1: Data Model Extensions

- [x] **1.1** SubAgentState 添加 output_schema 字段
  - File: `src/klaude_code/protocol/model.py`
  - Add: `output_schema: dict[str, Any] | None = None`
  - Effort: S

- [x] **1.2** SubAgentProfile 添加 output_schema_arg 字段
  - File: `src/klaude_code/protocol/sub_agent/__init__.py`
  - Add: `output_schema_arg: str | None = None`
  - Effort: S

- [x] **1.3** SubAgentResult 添加 structured_output 字段
  - File: `src/klaude_code/protocol/sub_agent/__init__.py`
  - Add: `structured_output: dict[str, Any] | None = None`
  - Effort: S

---

## Phase 2: Report Back Tool

- [x] **2.1** 定义 REPORT_BACK 常量
  - File: `src/klaude_code/protocol/tools.py`
  - Add: `REPORT_BACK = "report_back"`
  - Effort: S

- [x] **2.2** 创建 ReportBackTool 类
  - File: `src/klaude_code/core/tool/report_back_tool.py` (NEW)
  - Implement: `ReportBackTool` with `for_schema()` class method
  - Note: Not inheriting from ToolABC as it's handled specially (not registered in global registry)
  - Effort: M

- [x] **2.3** 导出 ReportBackTool
  - File: `src/klaude_code/core/tool/__init__.py`
  - Add export for ReportBackTool
  - Effort: S

---

## Phase 3: Turn/Task Executor Modifications

- [x] **3.1** TurnResult 添加 report_back_result 字段
  - File: `src/klaude_code/core/turn.py`
  - Add: `report_back_result: dict[str, Any] | None = field(default=None)`
  - Effort: S

- [x] **3.2** TurnExecutor 添加 has_report_back 属性
  - File: `src/klaude_code/core/turn.py`
  - Add property that checks `_turn_result.report_back_result is not None`
  - Also added `report_back_result` property for accessing the result
  - Effort: S

- [x] **3.3** TurnExecutor 添加 report_back 检测逻辑
  - File: `src/klaude_code/core/turn.py`
  - Added `_detect_report_back()` method called before running tools
  - Parses arguments and stores in `turn_result.report_back_result`
  - Effort: M

- [x] **3.4** TaskExecutor 修改结束条件
  - File: `src/klaude_code/core/task.py`
  - Add: `if turn.has_report_back: break`
  - Effort: S

- [x] **3.5** TaskExecutor 修改结果获取逻辑
  - File: `src/klaude_code/core/task.py`
  - Use `json.dumps(turn.report_back_result)` if available
  - Pass `structured_output` to TaskFinishEvent
  - Effort: M

- [x] **3.6** TaskFinishEvent 添加 structured_output
  - File: `src/klaude_code/protocol/events.py`
  - Add: `structured_output: dict[str, Any] | None = None`
  - Effort: S

---

## Phase 4: Tool Injection

- [x] **4.1** SubAgentTool.call() 提取 output_schema
  - File: `src/klaude_code/core/tool/sub_agent_tool.py`
  - Extract from args using `profile.output_schema_arg`
  - Pass to SubAgentState
  - Effort: M

- [x] **4.2** SubAgentManager 动态注入 report_back 工具
  - File: `src/klaude_code/core/manager/sub_agent_manager.py`
  - If `state.output_schema`: create new AgentProfile with report_back tool added to tools list
  - Also captures `structured_output` from TaskFinishEvent and passes to SubAgentResult
  - Effort: M

- [x] **4.3** 处理 report_back 工具执行
  - File: `src/klaude_code/core/tool/tool_runner.py`
  - Used 方案 A: Special handling for report_back in `run_tool()` (not in registry)
  - Effort: M

---

## Phase 5: Sub-Agent Profile Updates

- [x] **5.1** Task profile 添加 output_schema 参数
  - File: `src/klaude_code/protocol/sub_agent/task.py`
  - Added `output_schema` to TASK_PARAMETERS
  - Set `output_schema_arg="output_schema"` in profile
  - Effort: S

- [x] **5.2** 更新 Task description
  - File: `src/klaude_code/protocol/sub_agent/task.py`
  - Added "Structured output" section documenting output_schema and report_back behavior
  - Effort: S

- [x] **5.3** 子 agent system prompt 说明 report_back
  - File: `src/klaude_code/core/manager/sub_agent_manager.py`
  - Dynamically appends report_back instructions to system_prompt when output_schema is provided
  - Effort: S

- [x] **5.4** (Optional) Explore profile 添加支持
  - Skipped: Explore is primarily for code search, structured output not commonly needed
  - Effort: S

---

## Phase 6: UI Updates

- [x] **6.1** SubAgentState 展示 output_schema
  - File: `src/klaude_code/ui/renderers/sub_agent.py`
  - Modified `render_sub_agent_call` to show output_schema if present (styled with METADATA_DIM)
  - Effort: S

- [x] **6.2** build_sub_agent_state_from_tool_call 提取 output_schema
  - File: `src/klaude_code/ui/renderers/sub_agent.py`
  - Extract output_schema from payload using `profile.output_schema_arg` for replay rendering
  - Effort: S

---

## Phase 7: Testing

- [ ] **6.1** ReportBackTool 单元测试
  - File: `tests/core/tool/test_report_back_tool.py` (NEW)
  - Test: for_schema, schema(), call()
  - Effort: M

- [ ] **6.2** TurnExecutor report_back 检测测试
  - File: `tests/core/test_turn.py`
  - Test: has_report_back, report_back_result extraction
  - Effort: M

- [ ] **6.3** TaskExecutor 结束条件测试
  - File: `tests/core/test_task.py`
  - Test: report_back triggers task end
  - Effort: M

- [ ] **6.4** 端到端集成测试
  - File: `tests/integration/test_report_back.py` (NEW)
  - Test: full flow from parent to child and back
  - Effort: L

---

## Phase 7: Documentation & Cleanup

- [ ] **7.1** 更新类型导出
  - Ensure all new types are properly exported
  - Effort: S

- [ ] **7.2** 运行 pyright 类型检查
  - `uv run pyright`
  - Fix any type errors
  - Effort: S

- [ ] **7.3** 运行 ruff 格式化
  - `uv run ruff check --fix . && uv run ruff format`
  - Effort: S

---

## Progress Summary

| Phase | Total | Completed | Remaining |
|-------|-------|-----------|-----------|
| 1. Data Models | 3 | 3 | 0 |
| 2. Report Back Tool | 3 | 3 | 0 |
| 3. Turn/Task Executor | 6 | 6 | 0 |
| 4. Tool Injection | 3 | 3 | 0 |
| 5. Profile Updates | 4 | 4 | 0 |
| 6. UI Updates | 2 | 2 | 0 |
| 7. Testing | 4 | 0 | 4 |
| 8. Cleanup | 3 | 0 | 3 |
| **Total** | **28** | **21** | **7** |

---

## Notes

### Blocking Issues
- None currently

### Questions to Resolve
- [x] 工具注册方案确认 -> 特殊处理 report_back
- [x] 是否需要 system prompt 提示 report_back -> 需要
- [x] 多次调用 report_back 的处理 -> 只取第一次

### Decisions Made
- output_schema 通过参数名标注 (output_schema_arg)
- report_back 特殊处理，不注册到全局 registry
- report_back 后任务立即结束
- 多次调用 report_back 只取第一次
- system prompt 需要说明 report_back 工具
- UI 需要展示 output_schema
