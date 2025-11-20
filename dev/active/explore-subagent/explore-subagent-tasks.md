# Explore 子Agent 任务清单

Last Updated: 2025-11-19

> 用途：用于跟踪 Explore 子Agent 功能落地的执行进度。勾选顺序建议参考依赖关系，但可根据实际情况调整。

## Phase 1：协议与配置

- [ ] EX-1.1 在 `protocol/tools.py` 中新增 `EXPLORE` 常量与 `SubAgentType.EXPLORE`。
- [ ] EX-1.2 在 `AgentLLMClients` 中新增 `explore` 字段，并更新 `get_sub_agent_client` 处理 Explore。
- [ ] EX-1.3 在 `Config` 中新增 `explore_model` 字段，并在创建 LLM 客户端时接入。
- [ ] EX-1.4 更新 `get_example_config` 或相关注释，说明如何配置 `explore_model`。

## Phase 2：Explore 工具与子Agent 接入

- [ ] EX-2.1 在 `src/klaude_code/core/tool` 下新增 `ExploreArguments` 与 `ExploreTool.schema()`。
- [ ] EX-2.2 实现 `ExploreTool.call()`，通过 `SubAgentType.EXPLORE` 调用子Agent，并处理 `thoroughness` 参数。
- [ ] EX-2.3 在 `get_sub_agent_tools` 中为 Explore 配置只读工具集（如 `[BASH, READ]`）。
- [ ] EX-2.4 更新 `Agent.refresh_model_profile` 与 `get_system_prompt`，使 Explore 使用 `prompt_subagent_explore.md`。

## Phase 3：Prompt 与策略

- [ ] EX-3.1 在 `prompt_claude_code.md` 的 `# Tool Usage Policy` 中添加 Explore 使用策略与示例。
- [ ] EX-3.2 （可选）在 `prompt_subagent_explore.md` 中引入 `thoroughness` 相关指引。

## Phase 4：验证与测试

- [ ] EX-4.1 在 CLI 中手工验证 Explore 在典型问题上的表现（错误处理位置、代码结构）。
- [ ] EX-4.2 为 Explore 相关逻辑补充/更新测试用例（Config/Tools/Agent）。
- [ ] EX-4.3 进行回归检查与文档对齐（确认 Task/Oracle/主 Agent 行为无回归，文案与实现一致）。

> 使用建议：
> - 每完成一个任务勾选对应条目，并在需要时在代码 Review 说明中引用任务编号（如“完成 EX-2.2”）；
> - 如中途新增任务，请保持编号连续性或在末尾追加新编号（例如 EX-2.5）。
