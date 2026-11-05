# Steering naming

- 范围：将现有安全步骤边界输入队列的 Python 名称统一为 `steering`，入队动词用 `steer`；提交、注入、排空与批处理行为不变。
- 本期不做：真正 follow-up 队列、mode、新抽象、历史文档与 changelog 修改。
- 兼容值：保留磁盘键 `follow_up_queue`、操作 wire 值 `follow_up_agent`、事件类型 `follow.up.queue.updated`、操作与事件的 JSON 字段 `resume_follow_ups`；边界字段保留原 Python 名称，不引入 alias 或迁移。
- 已完成：跨层内部 API、属性、操作、事件、handler、scheduler、TUI 客户端与测试改名；保留 `inject_pending_inputs`；同步当前队列说明；未添加旧 Python API alias。
- 保留文本：日志、错误和用户可见的原文不变；普通追问、后续文本响应、测试消息正文及时间标记测试的局部 `follow_up` 不属于队列 API。
- 兼容回归：新增 `tests/protocol/test_steering_wire.py` 覆盖操作 dump/parse、事件 envelope round-trip 与中断字段；现有 session 测试增加旧磁盘键断言。
- 已运行检查：`make format`、`make lint`、`uv run ruff format --check .` 均通过；最后一次格式化排除下述两个并行文件，未改动其内容。
- 测试：首轮 `make test` 为 3721 passed、1 skipped、1 failed、4 deselected；`test_headless_process_waits_for_native_agent_report_and_rejects_second_executor` 读到输出时状态仍是 `running`，预期 `waiting_agents`。该用例单独复测通过；第二轮完整 `make test` 为 3725 passed、1 skipped、4 deselected（64.53s，包含并行新增测试）；未修改该状态逻辑。
- 复核：主代理运行协议、session 与 agent task 测试，123 passed；独立审查未发现问题，审查侧重点回归 206 passed，动态操作与事件解析兼容检查通过。
- 状态：已完成并验证，纳入本次提交；未 push。

## 本任务文件集（40 个，花括号列举同目录文件）

- `docs/tasks/steering-naming/progress.md`
- `src/klaude_code/agent/agent.py`、`src/klaude_code/agent/runtime/{agent_ops,dispatcher}.py`
- `src/klaude_code/app/scheduler.py`、`src/klaude_code/control/runtime/actor.py`
- `src/klaude_code/protocol/{events,op,op_handler}.py`、`src/klaude_code/session/{meta,session,store}.py`
- `src/klaude_code/tui/{AGENTS.md,runner.py}`、`src/klaude_code/tui/client/{base,local}.py`
- `src/klaude_code/tui/command/{AGENTS.md,command_abc.py}`、`src/klaude_code/tui/input/{flicker_safe_stdout,key_bindings,prompt_status_bar,prompt_toolkit}.py`
- `tests/agent/test_{agent_ops_resume,agent_task,background_tasks,prompt_suggestion,rewind_summary,sub_agent_registry,task_interrupt_persistence}.py`
- `tests/app/test_{local_agent_e2e,peer_endpoint,scheduler}.py`、`tests/cli/test_process_runtime.py`、`tests/control/test_runtime_hub.py`
- `tests/protocol/test_{shell_completion_origin,steering_wire}.py`、`tests/session/test_session.py`、`tests/tui/test_{key_bindings,local_runtime,runner_local}.py`
- 并行外部改动，不属本任务：`src/klaude_code/tui/renderer.py`、`tests/tui/test_renderer_spacing.py`；未修改或还原。