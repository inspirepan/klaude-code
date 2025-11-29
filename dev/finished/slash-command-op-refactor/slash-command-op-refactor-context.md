# Slash Command / Operation Refactor - Context

Last Updated: 2025-11-29

## Key Files

- `src/klaude_code/cli/runtime.py`
  - 交互模式入口，创建 `Executor` 与 UI display
  - REPL 循环中：
    - 把用户输入封装为 `op.UserInputOperation`
    - 调用 `executor.submit` / `wait_for`
    - 管理 ESC 监控逻辑（`start_esc_interrupt_monitor`）
- `src/klaude_code/core/executor.py`
  - 定义 `Executor` 与 `ExecutorContext`
  - 管理 `submission_queue`、`_completion_events`、`context.active_tasks`
  - 核心方法：
    - `ExecutorContext.handle_user_input`
    - `ExecutorContext.handle_interrupt`
    - `_run_agent_task`
    - `Executor._handle_submission`
- `src/klaude_code/protocol/op.py`
  - 定义 `OperationType` 与各类 `Operation`：
    - `UserInputOperation`
    - `InterruptOperation`
    - `InitAgentOperation`
    - `EndOperation`
  - 所有 operation 都通过 `execute(context: ExecutorContext)` 接入 executor
- `src/klaude_code/command/command_abc.py`
  - 定义 `CommandABC` 与 `CommandResult`
  - 当前 `CommandResult` 包含：
    - `agent_input: str | None`
    - `events: list[DeveloperMessageEvent | WelcomeEvent | ReplayHistoryEvent] | None`
- `src/klaude_code/command/registry.py`
  - 全局命令注册与分发：
    - `register_command`
    - `dispatch_command(raw: str, agent: Agent) -> CommandResult`
    - `is_interactive_command`
- `src/klaude_code/command/*.py`
  - 各种具体命令实现：
    - `clear_cmd.py`：重置 Session
    - `model_cmd.py`：切换模型
    - `export_cmd.py`：导出会话
    - `help_cmd.py`：展示可用命令
    - `refresh_cmd.py` / `terminal_setup_cmd.py` 等
- `src/klaude_code/core/agent.py`
  - `Agent` 封装：
    - `run_task`：构造 `TaskExecutionContext`，委托 `TaskExecutor`
    - `cancel`：取消当前任务并追加 `InterruptItem`
- `src/klaude_code/core/task.py` 与 `src/klaude_code/core/turn.py`
  - `TaskExecutor` 与 `TurnExecutor`：
    - 执行完整任务（多 turn）与单 turn
    - 管理工具调用、重试、元数据聚合
- `src/klaude_code/session/session.py`
  - `Session` 存储与加载
  - `conversation_history` 与 `append_history` 逻辑
  - 决定了压缩时需要操作的数据结构
- `src/klaude_code/command/prompt-update-dev-doc.md`
  - 与“接近上下文上限时更新 dev 文档”的提示模板，
  - 为 `/compact` 压缩策略与文案提供参考

## Key Decisions (So Far)

1. 保持 `UserInputOperation` 作为对外统一入口
   - 所有来自 CLI 的用户输入仍然转换为 `UserInputOperation`，以简化 CLI 层逻辑。
   - 内部通过 Input Actions 在 executor 内拆分更细粒度的行为，而不引入新的顶层 `OperationType` 给 CLI 使用。

2. 使用 Input Actions 表达命令的高层意图
   - 命令系统不再仅返回 `agent_input`，而是返回一组 Input Actions：
     - 当前迭代主要为 `RunAgent` / `ChangeModel`
     - 未来可扩展 `RunCompact` 等复杂动作
   - Executor 负责解释这些动作，并注册对应耗时任务到 `active_tasks[UserInputOperation.id]`。

3. 保持 ESC / Interrupt 逻辑不变
   - 不对 CLI 层 ESC 监控与 `InterruptOperation` 协议做任何变更。
   - 所有新引入的耗时任务遵循现有 `_run_agent_task` 模式：
     - 以 `UserInputOperation.id` 为 key 加入 `active_tasks`
     - 捕获 `CancelledError`，发出合适的结束事件。

4. `/model` 作为首个基于 Input Actions 的重构命令
   - `/model` 将成为第一个使用 `ChangeModel` 动作的命令，用于验证：
     - Input Actions 的表达能力
     - Executor 内部协调命令决策与具体执行的能力
   - `/compact` 被视为后续阶段的复杂命令候选，利用同一机制实现会话压缩

5. Session 更新采用“构造新快照再替换”策略（拟定）
   - 为避免压缩过程中部分写入导致的历史不一致，优先在内存中构造新的 `conversation_history`，
     确认无误后整体替换并保存。

## Open Questions

1. `/compact` 的默认压缩策略
   - 保留最近多少轮完整对话？
   - 是否根据 token 使用率动态调整保留数量？
   - 摘要信息放在 `DeveloperMessageItem` 还是 `SystemMessageItem`，或两者结合？

2. `/compact` 是否需要更新 dev 文档 / memory？
   - 是否在压缩前自动调用“更新 dev 文档”的提示模板？
   - 是否需要在 memory 中记录“压缩点”与历史摘要，以便后续任务使用？

3. Input Action 的具体技术形态
   - 使用 Enum + dataclass / Pydantic model 还是简单的 Python 类？
   - 是否需要为 actions 提供统一的序列化能力（目前主要在 executor 内部使用，可能不需要）？

4. 现有命令迁移的范围
   - 哪些命令值得迁移到 Input Actions 模型（例如 `/model`、`/clear`），哪些保持现状即可？
   - 是否需要为命令分层（纯 UI 命令 vs 需要 Executor 协作的命令）？

5. 测试覆盖范围
   - 针对 ESC 行为，需要增加哪些新的集成测试？
   - `/compact` 的压缩结果是否需要 golden 文件或更结构化的断言？

## Dependencies and Related Work

- 现有“smart truncation” 机制
  - 已经有针对工具输出进行智能截断与持久化的方案（`dev/finished/smart-truncation`），
    `/compact` 可以借鉴其中的思路，为上下文压缩输出控制提供参考。

- 提示模板与 dev 文档更新流
  - `prompt-update-dev-doc.md` 已经为“接近上下文上限时更新文档”提供了一套 prompt 规范，
    `/compact` 的实现可以复用或调用这些模板，以减少新设计成本。

- 现有中断与错误处理模型
  - 需要确保 `_run_compact_task` 遵循与 `_run_agent_task` 一致的错误处理与清理模式，
    避免重复设计一套中断语义。
