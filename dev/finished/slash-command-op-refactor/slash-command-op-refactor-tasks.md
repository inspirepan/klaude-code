# Slash Command / Operation Refactor - Tasks

Last Updated: 2025-11-29

> 本文件用于跟踪任务执行情况。每一项对应 plan 文档中的任务编号和阶段。

## Phase 0 – 需求澄清与方案定稿

- [ ] (0.1, S) 明确本迭代范围与优先级（以 `/model` 为先，`/compact` 等复杂命令作为后续阶段）
- [ ] (0.2, S) 确定 Input Action 结构与定义位置（Enum/数据类/Pydantic 等）

## Phase 1 – Input Action 与 CommandResult 扩展

- [ ] (1.1, M) 在代码中定义 `InputAction` 抽象，至少包含 `RunAgent`
- [ ] (1.2, M) 为 `CommandResult` 新增 `internal_actions: list[InputAction] | None`
- [ ] (1.3, M) 更新 `dispatch_command`，对非斜杠文本返回 `RunAgent` 默认动作
- [ ] (1.4, S) 确认现有命令在未使用 `internal_actions` 的情况下行为保持不变（回归测试）

## Phase 2 – Executor 消费 Input Actions

- [ ] (2.1, M) 在 `ExecutorContext` 中实现 `_run_input_action`，支持 `RunAgent`
- [ ] (2.2, L) 重构 `handle_user_input`：优先消费 `internal_actions`，否则从 `agent_input` 回退
- [ ] (2.3, M) 确保所有耗时任务使用 `UserInputOperation.id` 作为 `active_tasks` key，并通过 `_handle_submission` 正确被 `wait_for` 等待

## Phase 3 – `/model` 命令与 ChangeModel 动作

- [ ] (3.1, M) 将 `/model` 迁移为返回 `ChangeModel` 输入动作，由 executor 统一处理模型切换
- [ ] (3.2, M) 在 executor 中实现 `ChangeModel` 处理逻辑（加载配置、构造新 LLM client、更新 `agent.profile`）

## Phase 4 – 其它命令迁移与 `/compact` 预研（可选）

- [ ] (4.1, M) 评估并视情况为 `/clear` 引入 `ResetSession` 动作，集中 Session 重建逻辑
- [ ] (4.2, M) 梳理 `/compact` 需求和压缩策略，形成后续阶段的设计文档（不实现代码）

## Phase 5 – 测试与文档

- [ ] (5.1, L) 增加/更新单元测试：Input Actions、`handle_user_input`、`/model` 正常与“无变化”场景
- [ ] (5.2, L) 增加 ESC 行为回归测试：确保引入 Input Actions 后普通任务中断行为未回归
- [ ] (5.3, M) 更新开发文档，记录：
  - 命令系统如何返回 Input Actions
  - Executor 如何解释 Input Actions 并与 ESC 协作
  - `/model` 重构后的执行路径与未来 `/compact` 的扩展点
