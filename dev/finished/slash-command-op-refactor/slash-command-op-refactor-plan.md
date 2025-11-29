# Slash Command / Operation Refactor Plan

Last Updated: 2025-11-29

## Executive Summary

本计划的目标是重构当前斜杠命令（slash commands）与执行器（`Executor`）的交互方式，使其：

- 在第一阶段优先完成 `/model` 命令的内部重构：通过 Input Actions 和 Executor 来统一处理模型切换逻辑
- 保持现有的 `Executor` 调度模型与 ESC 中断语义：所有耗时操作都可被 `InterruptOperation` 干净打断
- 提升命令系统的可扩展性与可测试性，为未来新增更复杂的命令 / operation（如 `/compact` 会话压缩、更多 session 维护操作）打基础

核心思路：

- 对外仍然以一次 `UserInputOperation` 表达“这一轮用户输入”
- 在 `ExecutorContext.handle_user_input` 内部，将解析后的语义转成一组结构化的“内部动作”（Input Actions），例如：
  - `RunAgent(text)`：触发一次完整的 Agent 任务
  - `ChangeModel(new_model)`：切换模型（当前迭代的重点）
  - 未来可扩展 `RunCompact(params)` 等动作用于复杂命令（如会话压缩）
- 所有长耗时任务使用同一个 `UserInputOperation.id` 作为 key 挂在 `active_tasks` 中，使：
  - `wait_for(submission_id)` 直到内部所有动作完成才返回
  - ESC 通过 `InterruptOperation` 可以统一取消这些任务

本计划当前迭代专注于：引入 Input Action 抽象、扩展 `CommandResult`、重构 `handle_user_input`，并优先完成 `/model` → `ChangeModel` 动作的落地；`/compact` 压缩能力保留在未来阶段实施。

## Current State Analysis

### 技术现状

- 斜杠命令入口：
  - CLI（`src/klaude_code/cli/runtime.py`）在交互模式中对每次用户输入：
    - 始终提交 `op.UserInputOperation(input=UserInputPayload, session_id)` 到 `Executor`
    - 然后 `wait_for(submission_id)`，如果是非 interactive 命令，还会启动 ESC 监控
- Executor 处理链路：
  - `Executor.start` 循环从 `submission_queue` 取出 `Submission`
  - `_handle_submission`：
    - `await submission.operation.execute(self.context)`
    - 若 `context.active_tasks[submission.id]` 中注册了 `ActiveTask`，则起一个后台任务等待该 `task` 完成，再 `set()` 完成事件
  - `UserInputOperation.execute` 仅调用 `context.handle_user_input(self)`
- `ExecutorContext.handle_user_input` 职责：
  - 通过 `_ensure_agent(session_id)` 获取/创建 `Agent` 与 `Session`
  - 发 `UserMessageEvent`
  - 调 `dispatch_command(user_input.text, agent)` 处理斜杠命令
  - 根据 `CommandResult`：
    - 如果 `events` 非空：发 UI 事件并写入部分历史
    - 如果 `agent_input` 非空：
      - 构造新的 `UserInputPayload(text=agent_input, images=...)`
      - 起 `asyncio.create_task(self._run_agent_task(...))`
      - 将该 task 注册为 `self.active_tasks[operation.id] = ActiveTask(...)`
- ESC 中断机制：
  - CLI ESC → 提交 `op.InterruptOperation(target_session_id)`
  - `ExecutorContext.handle_interrupt`：
    - 对目标 session 的 `Agent` 调 `agent.cancel()`，追加 `InterruptItem` 并取消内部工具执行
    - 遍历 `active_tasks`，对目标 session 对应的 `asyncio.Task` 调 `task.cancel()`
    - `_run_agent_task` 捕获 `CancelledError`，发出 `TaskFinishEvent(task_result="task cancelled")`

### 当前痛点

- 复杂命令（例如未来的 `/compact`）如果在命令内部直接调用 LLM（`agent.run_task` 或 `llm_client.call`）：
  - 无法通过 `active_tasks` 统一管理
  - ESC 只能取消当前 `Agent` 的工具执行，无法打断命令内部直接发起的 LLM 调用
  - `wait_for(UserInputOperation.id)` 的完成语义会与“内部命令行为”脱节
- `dispatch_command` 与命令系统目前只返回 `agent_input` / `events`：
  - 无法表达更丰富的“高层意图”（例如：压缩会话、切换模型、重建 Session 等）
  - 导致 executor 中的逻辑越来越难以维护（越多特殊命令，越多 if/else）

## Proposed Future State

### 概念与责任划分

- 保持对外接口不变：
  - CLI 仍然只提交 `UserInputOperation`（加上现有的 `Interrupt`/`InitAgent`/`End`）
  - `Executor.wait_for(submission_id)` 的语义保持为“这一轮用户输入相关的所有内部动作都结束”
- 在 executor 内部引入 Input Action 抽象（名称可具体敲定）：
  - `RunAgent(text: str)`：发起一次标准 agent 任务
  - `RunCompact(params: CompactParams)`：发起一次压缩任务（内部可调子 agent / 当前 agent 的 LLM）
  - `ChangeModel(new_model: str)`：切换当前 session 使用的模型
  - 未来可扩展：`ResetSession`, `ExportSession`, `MaintenanceAction` 等
- 命令系统（`dispatch_command` + 各 `CommandABC` 实现）从“直接操作 Agent/Session + 返回 agent_input”升级为：
  - 解析命令文本，构造高层意图（Input Actions）与 UI 事件
  - 返回包含 actions 的 `CommandResult`

### 执行器内部行为

- `ExecutorContext.handle_user_input`：
  - 发出原始 `UserMessageEvent`（保持 UI 行为不变）
  - 调用 `dispatch_command` 获取 `CommandResult`
  - 播放 `CommandResult.events`
  - 遍历 `CommandResult.internal_actions`（Input Actions），对每个 action：
    - 若为耗时动作（如 `RunAgent` / `RunCompact`）：
      - 用当前 `UserInputOperation.id` 作为 key，创建并注册 `ActiveTask(task=..., session_id=...)`
    - 若为快操作（如 `ChangeModel`，且纯本地）：直接执行
- `_handle_submission` 保持通用逻辑：
  - 仍然只认 `self.context.active_tasks[submission.id]` 里的 `ActiveTask`
  - `wait_for(submission_id)` 会在所有耗时动作完成后才返回
- ESC：
  - 不需要任何细节变更，依然通过 `InterruptOperation` + `active_tasks` 做 cancel
  - 新增的 `_run_compact_task` 等协程只要遵守：
    - 捕获 `CancelledError`
    - 发出合适的 `TaskFinishEvent` 或错误事件

### `/compact` 的目标行为

- 用户输入 `/compact [options]`：
  - 命令系统返回：
    - 一些说明性的 UI 事件（例如 “开始压缩上下文…”）
    - 一个 `RunCompact(params)` Input Action
  - Executor 内部：
    - 起一个 `_run_compact_task(agent, params, task_id=submission.id, session_id=...)`
    - 该任务：
      - 根据当前 `Session.conversation_history`、配置与策略，构造压缩 prompt
      - 调用 LLM 生成 summary、重写策略等
      - 以工程化方式更新 `Session`（例如：
        - 保留最近 N 轮完整对话
        - 更早的对话归并为一两条 `DeveloperMessageItem`/`SystemMessageItem` 总结
        - 必要时更新 dev docs 或 memory）
      - 发出 `TaskFinishEvent`，提示压缩结果
- 全流程可被 ESC 打断：压缩进行中按 ESC，`_run_compact_task` 会被 cancel，Session 若有部分写入需考虑幂等或补偿策略。

## Implementation Phases

### Phase 0：需求澄清与方案定稿

目标：把 Input Action 模型、`CommandResult` 扩展方式、`/model` 行为重构范围对齐清楚，并明确 `/compact` 等复杂命令属于后续阶段。

- 明确 `/compact` 的压缩策略：
  - 保留多少轮最近对话？
  - 旧对话摘要是放到 `DeveloperMessageItem` 还是 `SystemMessageItem`？
  - 是否需要同步更新 dev docs / memory？
- 与现有 dev 文档（如 `prompt-update-dev-doc.md`、`smart-truncation` 文档）对齐设计风格
- 最终确定 Input Action 的具体结构（Enum + dataclass 或 Pydantic model）

### Phase 1：Input Action 抽象与 `CommandResult` 扩展

目标：在不改变现有行为的前提下，引入 Input Action 及其在命令系统中的返回路径。

- 在合适位置定义 `InputAction`（例如新模块或 `command_abc`/`registry` 附近）：
  - 至少包含 `RunAgent(text)`，作为对当前行为的等价表达
- 扩展 `CommandResult`：
  - 增加字段：`internal_actions: list[InputAction] | None`
  - 保持 `agent_input` 兼容，但在新路径里优先使用 `internal_actions`
- 更新 `dispatch_command`：
  - 非斜杠文本：
    - 返回 `CommandResult(internal_actions=[RunAgent(raw_text)])`
  - 现有命令（`/clear`、`/export`、`/help`、`/model` 等）：
    - 初期可以仍然只设置 `events` 和/或 `agent_input`，`internal_actions` 留空

### Phase 2：Executor 消费 Input Actions

目标：让 `ExecutorContext.handle_user_input` 能够解释 Input Actions，并基于同一个 `UserInputOperation.id` 注册耗时任务。

- 在 `ExecutorContext` 中添加私有 helper：
  - `_run_input_action(action: InputAction, operation: UserInputOperation, agent: Agent)`
  - 对 `RunAgent`：
    - 构造 `UserInputPayload(text=..., images=operation.input.images)`
    - 起 `asyncio.create_task(self._run_agent_task(...))`
    - `self.active_tasks[operation.id] = ActiveTask(task=task, session_id=operation.session_id)`
- 调整 `handle_user_input`：
  - 优先使用 `CommandResult.internal_actions`：
    - 若非空：遍历执行每个 action
    - 若为空但 `agent_input` 不为空：构建等价的 `RunAgent(agent_input)`
    - 若都为空：与当前行为一致，仅发 `events` 并结束
- 确保 `_handle_submission` 和 `wait_for` 逻辑无需修改：
  - 仍然只通过 `active_tasks[submission.id]` 判断是否需要等待

### Phase 3：实现 `/compact` 命令与压缩任务

目标：让 `/compact` 成为第一批使用 `RunCompact` 输入动作的复杂命令，完整打通压缩链路。

- 在命令系统中新增 `/compact`：
  - 继承 `CommandABC`，解析参数（策略、保留轮数等）
  - 返回：
    - 一条或多条 `DeveloperMessageEvent`（说明“开始压缩…”）
    - `internal_actions=[RunCompact(params)]`
- 在 executor 中实现 `_run_compact_task(agent, params, task_id, session_id)`：
  - 读取当前 `Session.conversation_history`
  - 基于策略切分“需要压缩的历史”与“保留的最近对话”
  - 构造压缩 prompt，调用 LLM：
    - 可以使用当前 agent 的 LLM 或子 agent
  - 根据 LLM 输出生成 summary items：
    - 例如一条 `DeveloperMessageItem(content=summary)`
  - 原子性更新 Session：
    - 替换较早部分的 history 为 summary + 最近 N 轮完整对话
  - 记录并发出 `TaskFinishEvent(task_result=简要说明)`
  - 捕获 `CancelledError`，在任务被 ESC 打断时给出合理的部分成功语义（例如“不修改 Session，只提示取消”）

### Phase 4：可选——将其它命令迁移到 Input Actions 模型与 `/compact` 预研

目标：逐步把部分命令改造成返回 Input Actions，而非直接在命令内部操作 Agent/Session，同时为 `/compact` 等复杂命令做前期设计。

- `/clear` → `ResetSession` 动作（可选，是否引入单独动作视复杂度而定）
- `/compact`：仅进行策略设计与 RunCompact 动作抽象预研，不在本迭代落地代码
- 保持兼容性：在迁移前后，命令行为对用户来说不可见差异

### Phase 5：测试、文档与回归

目标：保证行为与 ESC 语义正确，`/model` 重构稳定工作，并为后续 `/compact` 等提供清晰扩展路径。

- 补充/更新单元测试：
  - `handle_user_input` 对不同 `CommandResult.internal_actions` 的处理
  - `/model` 在不同路径（模型不变 / 模型变更）下的行为
- 更新开发文档：
  - 命令系统架构
  - Input Action 的扩展方式
  - `/model` 重构后的执行路径与扩展点

## Detailed Tasks

下面任务按优先级与阶段划分，每个任务包含：简要描述、依赖、验收标准、预估工作量（S/M/L/XL）。

### Phase 0：需求澄清与方案定稿

1. 明确 `/compact` 压缩策略（后续阶段）
   - Effort: S
   - Dependencies: 无
   - Acceptance Criteria:
     - 文字化说明：保留轮数、摘要写入的 Item 类型、是否更新 dev 文档 / memory
     - 这些规则在 `/compact` 命令实现和 `_run_compact_task` 中都有体现

2. 确定 Input Action 结构与定义位置
   - Effort: S
   - Dependencies: 任务 1
   - Acceptance Criteria:
     - 一个统一的 `InputAction` 抽象（Enum+dataclass 或 Pydantic model）被定义
     - 包含至少 `RunAgent` 与 `ChangeModel` 两类，后续可扩展 `RunCompact` 等
     - 不与现有 `Operation` 类型产生概念混淆（文档中有清晰说明）

### Phase 1：Input Action 与 `CommandResult` 扩展

3. 扩展 `CommandResult` 支持 `internal_actions`
   - Effort: M
   - Dependencies: 任务 2
   - Acceptance Criteria:
     - `CommandResult` 新增 `internal_actions: list[InputAction] | None`
     - 现有命令的构造与校验全部通过（类型检查、测试）
     - 不改变现有运行行为（在 executor 还未消费 `internal_actions` 前）

4. 更新 `dispatch_command` 默认行为为 `RunAgent`
   - Effort: M
   - Dependencies: 任务 3
   - Acceptance Criteria:
     - 对于非斜杠文本，`dispatch_command` 返回 `internal_actions=[RunAgent(raw_text)]`
     - 在 executor 未使用 `internal_actions` 之前，逻辑仍然兼容（通过 `agent_input` 回退）

### Phase 2：Executor 消费 Input Actions

5. 在 `ExecutorContext` 中实现 `_run_input_action` helper
   - Effort: M
   - Dependencies: 任务 3、4
   - Acceptance Criteria:
     - `_run_input_action` 支持至少 `RunAgent`，并为后续动作预留扩展点
     - 为 `RunAgent` 创建的 task 使用 `operation.id` 作为 `active_tasks` key

6. 重构 `handle_user_input` 使用 Input Actions
   - Effort: L
   - Dependencies: 任务 5
   - Acceptance Criteria:
     - 优先消费 `CommandResult.internal_actions`；若为空则根据 `agent_input` 构造 `RunAgent`
     - 所有现有交互模式行为保持不变（任务、ESC、回放历史等）
     - 回归测试通过（包括 ESC 行为）

### Phase 3（后续）：实现 `/compact` 命令与 `_run_compact_task`

7. 新增 `/compact` 命令类
   - Effort: M
   - Dependencies: 任务 1–4
   - Acceptance Criteria:
     - 命令能解析基本参数（如保留轮数、模式）
     - 返回包含说明性的 `events` 与 `internal_actions=[RunCompact(params)]`
     - 在 help 列表与 slash 补全中正常展示

8. 实现 `_run_compact_task` 并接入 `active_tasks`
   - Effort: L
   - Dependencies: 任务 5、7
   - Acceptance Criteria:
     - 任务读取 Session 历史，按策略构造压缩 prompt 并调用 LLM
     - 在压缩成功时原子更新 Session：插入 summary、保留最近 N 轮
     - 在任务被取消（ESC）时不破坏 Session 的一致性（要么不写，要么保证写入幂等）
     - 发出 `TaskFinishEvent`，描述压缩结果或取消信息

9. 回归 ESC 对 `/compact` 的中断能力
   - Effort: M
   - Dependencies: 任务 8
   - Acceptance Criteria:
     - `/compact` 在压缩过程中按 ESC 能触发 `InterruptOperation`
     - `_run_compact_task` 被取消且正确处理 `CancelledError`
     - UI 收到合适的任务结束事件（包括取消场景）

### Phase 4：其它命令迁移（可选）

10. 将 `/model` 迁移为 `ChangeModel` 输入动作
    - Effort: M
    - Dependencies: 任务 5、6
    - Acceptance Criteria:
      - 命令实现主要只负责参数解析与构造 `ChangeModel` 动作
      - 模型切换逻辑统一移至 Executor/Agent 层
      - 行为与当前 `/model` 一致（包括 interactive 特性）

11. 评估并迁移 `/clear` 等命令
    - Effort: M
    - Dependencies: 任务 10
    - Acceptance Criteria:
      - 若引入 `ResetSession` 动作，命令实现保持薄逻辑
      - Session 重建流程在 Executor 层集中管理

### Phase 5：测试与文档

12. 补充单元/集成测试覆盖新路径
    - Effort: L
    - Dependencies: 任务 6–9
    - Acceptance Criteria:
      - 新增测试覆盖：Input Actions 解析、`handle_user_input` 路径、`/compact` 正常与取消场景
      - 现有测试全部通过

13. 更新开发文档与 dev 任务文档
    - Effort: M
    - Dependencies: 任务 6–9
    - Acceptance Criteria:
      - 命令系统和 Executor 架构变更被清晰记录
      - 对外行为（尤其 ESC 与 `/compact`）在文档中有完整说明

## Risk Assessment and Mitigation Strategies

1. 风险：破坏现有 ESC 行为或任务完成语义
   - 描述：如果 `active_tasks` 注册或清理不当，可能导致 `wait_for` 提前返回或任务泄漏。
   - 缓解：
     - 保持所有耗时任务都使用 `UserInputOperation.id` 作为 key
     - 为 `_run_compact_task` 与 `_run_agent_task` 做对称的异常处理与清理逻辑
     - 增加针对 ESC 的自动化测试

2. 风险：Session 更新过程中的数据不一致
   - 描述：压缩任务在中途被取消或异常结束时，如果部分写入 Session，可能留下半成品状态。
   - 缓解：
     - 在内存中先构造新的 `conversation_history` 快照，确认无误后整体替换
     - 如需写多步，确保每一步是幂等的，或引入简单的“事务式”写入封装

3. 风险：命令系统复杂度提升
   - 描述：`CommandResult` 增加新字段、命令返回更复杂结果，可能增加维护成本。
   - 缓解：
     - 将 Input Action 设计为简单明确的枚举/数据类
     - 为命令增加针对 `CommandResult` 的单元测试

4. 风险：用户对 `/compact` 行为预期不一致
   - 描述：压缩策略（保留轮数、摘要粒度）不符合用户期待，可能造成“信息丢失”的感知。
   - 缓解：
     - 在 Phase 0 明确并记录策略
     - 在 `/compact` 任务完成的提示文案中说明压缩规则
     - 预留参数（例如 `/compact --keep-last 5`）以支持用户调整

## Success Metrics

- 功能性：
  - `/model` 重构后仍支持现有交互式模型切换体验
  - 模型切换对后续任务与上下文行为不产生意外影响
- 稳定性：
  - ESC 对普通 agent 任务的中断行为保持稳定
  - 引入 Input Actions 后，无任务泄漏或 `wait_for` 行为异常
- 可维护性：
  - 新增 Input Action 后，添加新命令只需在命令层创建对应动作，无需大改 Executor
  - 新的架构被文档和测试清晰覆盖，为后续 `/compact` 等复杂命令提供扩展点

## Required Resources and Dependencies

- 人力：
  - 熟悉当前命令系统与 Executor 的核心开发者 1–2 名
  - 测试与文档支持 0.5 人（可与开发重叠）
- 技术依赖：
  - 现有 LLM 客户端与 Agent/Task/Turn 体系
  - 现有测试框架（pytest）、类型检查（pyright）、格式化工具（ruff、isort）
  - 现有 dev 文档与 memory 机制（用于参考 `/compact` 语义）

## Timeline Estimates

基于中等规模改动的粗略估算（以人日计）：

- Phase 0：需求澄清与方案定稿
  - 0.5–1 天
- Phase 1：Input Action 与 `CommandResult` 扩展
  - 1–1.5 天（视现有命令适配复杂度）
- Phase 2：Executor 消费 Input Actions
  - 1.5–2 天（需要回归 ESC、任务完成语义）
- Phase 3：`/compact` 实现
  - 2–3 天（含 LLM prompt 设计与 Session 写回逻辑）
- Phase 4：其它命令迁移（可选）
  - 1–2 天
- Phase 5：测试与文档
  - 1–2 天

整体端到端（包括 buffer）约 7–11 个工作日，具体取决于 `/compact` 压缩策略与 Session 更新逻辑的复杂度，以及回归测试范围。
