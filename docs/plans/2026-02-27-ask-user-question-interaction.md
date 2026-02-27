# AskUserQuestion + 通用 UserInteraction 框架 Implementation Plan

> **For Claude:** Use the executing-plans skill to implement this plan task-by-task.

**Goal:** 在主 agent 中实现 `AskUserQuestion` 工具（多选 + 同屏可输入补充文本），并抽象出可复用的 `UserInteraction` 通道，为后续“工具执行前用户审批”复用。

**Architecture:** 新增一条通用的人机交互链路：Tool/Core 发起 interaction request 并挂起，TUI 在任务执行期间接管交互 UI，用户提交后通过 Op 回填，Core 恢复同一轮 tool 执行。`AskUserQuestion` 作为首个 consumer 落地；底层 request/response 语义保持通用，不绑定“问问题”场景。按约束仅主 agent 可用、同一时刻仅允许一个 pending interaction、取消时不悬挂 future。

**Tech Stack:** Python asyncio、Pydantic、prompt_toolkit（复用 `selector.py`）、现有 Executor Event/Op 架构、pytest。

---

### Task 1: 定义通用 UserInteraction 协议模型（非工具专用）

**Files:**
- Create: `src/klaude_code/protocol/user_interaction.py`
- Modify: `src/klaude_code/protocol/events.py`
- Modify: `src/klaude_code/protocol/op.py`
- Modify: `src/klaude_code/protocol/op_handler.py`
- Test: `tests/test_user_interaction_protocol.py`

**Intent:** 先固定 request/response 协议边界，避免后续实现时把“问题交互”硬编码进底层通道，确保审批场景可复用。

**Steps:**
1. 写失败测试：校验 request/response model 的基本结构、`cancelled/submitted` 状态语义。
2. 新增 `user_interaction.py`，定义通用 payload/response model（含 AskUserQuestion 所需字段）。
3. 在 `events.py` 增加 `UserInteractionRequestEvent`；在 `op.py` 增加 `UserInteractionRespondOperation`。
4. 在 `op_handler.py` 增加 `handle_user_interaction_respond` 协议方法。
5. 验证：`pytest tests/test_user_interaction_protocol.py -v`。
6. Commit: `feat(protocol): add generic user interaction event and op models`

**Acceptance criteria:**
- 协议层存在通用 interaction request/response，不与具体工具名耦合。
- Event 与 Op 能表达：request id、session id、source、payload、取消状态。

**Notes:**
- `answers` 仅出现在工具输出，不放入工具输入 schema。
- 预留 `source` 字段（如 `tool`/`approval`），后续审批直接复用。

---

### Task 2: 实现 Core 挂起/恢复管理器（串行 + 可取消）

**Files:**
- Create: `src/klaude_code/core/user_interaction/manager.py`
- Create: `src/klaude_code/core/user_interaction/__init__.py`
- Modify: `src/klaude_code/core/executor.py`
- Test: `tests/test_user_interaction_manager.py`

**Intent:** 提供统一的挂起点：tool 发起请求时 await future；UI 回答后恢复。并严格执行“仅 1 个 pending interaction”。

**Steps:**
1. 写失败测试：串行约束（第二个请求被拒绝）、正常应答恢复、取消后 future 不悬挂。
2. 新增 manager：`request(...) -> await`、`respond(...)`、`cancel_pending(...)`、`wait_next_request()`。
3. 在 `ExecutorContext` 挂载 manager；实现 `handle_user_interaction_respond` 调用 manager.respond。
4. 在中断路径接入 `cancel_pending`，确保取消时 pending future 终止。
5. 验证：`pytest tests/test_user_interaction_manager.py -v`。
6. Commit: `feat(core): add user interaction manager with serial pending and cancel semantics`

**Acceptance criteria:**
- 同一 session 任一时刻最多一个 pending interaction。
- interrupt/cancel 后无 pending 泄漏，future 不会永久等待。

**Notes:**
- 返回给工具侧的取消信号统一映射为 `status=aborted` 语义。

---

### Task 3: 将交互能力注入 ToolContext（仅主 agent 可发起）

**Files:**
- Modify: `src/klaude_code/core/tool/context.py`
- Modify: `src/klaude_code/core/turn.py`
- Test: `tests/test_tool_context_user_interaction.py`

**Intent:** 让工具通过显式上下文访问 interaction 能力，保持依赖可见、可测、可控。

**Steps:**
1. 写失败测试：缺少交互能力时工具返回可读错误；主 agent 上下文具备交互回调。
2. 在 `ToolContext` 增加通用 `request_user_interaction` 回调与类型定义。
3. 在 `TurnExecutor._run_tool_executor` 构造 `ToolContext` 时注入该回调。
4. 加主/子 agent 约束：子 agent 调用该回调时直接报错（或返回 unavailable）。
5. 验证：`pytest tests/test_tool_context_user_interaction.py -v`。
6. Commit: `feat(tool): inject generic user interaction callback into tool context`

**Acceptance criteria:**
- ToolContext 可发起 interaction request，且仅主 agent 可用。
- 子 agent 调用会被明确拒绝。

**Notes:**
- 这里不实现审批逻辑，只提供可复用通道。

---

### Task 4: 实现 AskUserQuestion 工具与 schema（多题、多选、自动 Other）

**Files:**
- Create: `src/klaude_code/core/tool/ask_user_question_tool.py`
- Create: `src/klaude_code/core/tool/ask_user_question_tool.md`
- Modify: `src/klaude_code/core/tool/__init__.py`
- Modify: `src/klaude_code/protocol/tools.py`
- Modify: `src/klaude_code/core/agent_profile.py`
- Test: `tests/test_ask_user_question_tool.py`

**Intent:** 按用户给定 schema 落地工具；工具只做参数校验、发起交互、回传结构化答案。

**Steps:**
1. 写失败测试：参数校验（1-4 题、每题 2-4 选项、multiSelect 行为）、取消返回。
2. 实现工具 schema（保留 `AskUserQuestion` 工具名），输入不接受 `answers` 字段。
3. 调用通用 interaction 回调，接收 UI 回答并序列化为 JSON 文本结果。
4. 将工具注册到主 agent 工具集（不加入 sub-agent 工具集）。
5. 验证：`pytest tests/test_ask_user_question_tool.py -v`。
6. Commit: `feat(tool): add AskUserQuestion tool on generic interaction channel`

**Acceptance criteria:**
- `AskUserQuestion` 仅主 agent 可用。
- tool result 中包含用户选择与补充文本，取消时返回 `aborted` 风格结果。

**Notes:**
- `Other` 由 UI 自动追加，不要求模型显式提供。

---

### Task 5: 扩展 selector 为“同屏选择+输入”交互（单题）

**Files:**
- Modify: `src/klaude_code/tui/terminal/selector.py`
- Test: `tests/test_selector_question_mode.py`

**Intent:** 复用现有 selector 风格，实现你给图示那种“最后一行可输入”的同屏体验，避免两阶段弹窗。

**Steps:**
1. 写失败测试：多选 toggle、焦点移动到输入行后可编辑文本、提交返回结构化值。
2. 在 selector 增加 question 模式 API（返回 selected ids + inline input text）。
3. 增加输入行渲染与焦点状态（输入行获得焦点时可打字）。
4. 保持现有 `select_one`/`SelectOverlay` 行为不回归。
5. 验证：`pytest tests/test_selector_question_mode.py -v`。
6. Commit: `feat(tui): add single-panel question selector with inline input row`

**Acceptance criteria:**
- 单屏内可完成选项选择与补充输入。
- 多选题与单选题都可用，键位行为一致且可预测。

**Notes:**
- v1 使用一个 inline input 同时承载 `Other` 文本和额外补充；后续可拆分双输入。

---

### Task 6: 在任务等待期接入交互循环（runner 侧）

**Files:**
- Modify: `src/klaude_code/tui/runner.py`
- Modify: `src/klaude_code/tui/input/prompt_toolkit.py` (仅在需要暴露辅助输入接口时)
- Test: `tests/test_runner_user_interaction.py`

**Intent:** 保持 agent task 在后台运行时，runner 仍可处理中途 interaction request，并通过 Op 回填。

**Steps:**
1. 写失败测试：任务等待期间收到 request 能弹出交互并提交 response；取消能正确回填 cancelled。
2. 增加 `wait_for_with_interactions(...)`：并行等待 task completion 与 interaction request。
3. 收到 request 后调用 selector question 模式，提交 `UserInteractionRespondOperation`。
4. 与 ESC interrupt 监控协调：交互进行中避免 stdin 争抢。
5. 验证：`pytest tests/test_runner_user_interaction.py -v`。
6. Commit: `feat(tui): handle user interaction requests while agent task is running`

**Acceptance criteria:**
- 不需要 `/continue`，同一轮 tool 可直接恢复。
- 交互期间不出现 ESC monitor 与输入焦点冲突。

**Notes:**
- 显示层回放不新增历史项，仍只靠 tool call/result 体现用户选择结果。

---

### Task 7: 端到端行为与回归测试

**Files:**
- Create: `tests/test_ask_user_question_integration.py`
- Modify: `tests/test_tool_runner.py` (如需补充 aborted 断言)
- Modify: `tests/test_tui_machine_interrupt.py` (如需补充中断后状态断言)

**Intent:** 从“工具发起 -> UI回答 -> Op回填 -> tool result”全链路验证，并覆盖中断取消场景。

**Steps:**
1. 写失败测试：submitted 路径与 cancelled 路径。
2. 补充中断期间 pending interaction 的取消断言。
3. 跑局部测试集合。
4. 跑全量测试。
5. Commit: `test(interaction): add end-to-end coverage for AskUserQuestion flow`

**Verification:**
- `pytest tests/test_ask_user_question_integration.py -v`
- `pytest tests/test_user_interaction_manager.py tests/test_ask_user_question_tool.py tests/test_selector_question_mode.py tests/test_runner_user_interaction.py -v`
- `make test`

**Acceptance criteria:**
- 全链路稳定通过，取消无悬挂。
- 既有 selector 与 TUI 行为无明显回归。

**Notes:**
- 若交互测试受 TTY 限制，可用 mock + 纯逻辑 helper 测试保证稳定性。

---

### Task 8: 文档与后续审批复用钩子说明

**Files:**
- Modify: `AGENTS.md` (如需补充工具能力说明)
- Create: `docs/plans/2026-02-27-user-interaction-approval-followup.md` (可选)

**Intent:** 把“通用 interaction 可复用到审批”写清楚，避免后续实现时重复设计。

**Steps:**
1. 记录当前落地范围（AskUserQuestion）与未做项（工具前审批）。
2. 记录复用点：同一 manager/event/op/selector。
3. 列出审批最小改造入口（`ToolExecutor._run_single_tool_call` 前置 hook）。
4. Commit: `docs: document reusable user interaction architecture for approval flow`

**Acceptance criteria:**
- 团队成员可据文档直接继续做“工具前审批”，无需重构 AskUserQuestion。

**Notes:**
- 严格保持 YAGNI：本次不提前实现审批执行逻辑，只铺复用通道。

---

## 全局验收清单

- 仅主 agent 能调用 `AskUserQuestion`，子 agent 调用会被拒绝。
- 同一时刻仅 1 个 pending interaction（串行）。
- 用户取消后：future 被取消，tool result 为 aborted/error 风格，不悬挂。
- UI 为单面板：可多选 + 同屏输入补充文本（输入行可获焦并编辑）。
- 回放历史中仅体现 tool call / tool result（不新增独立“用户问答历史项”）。

