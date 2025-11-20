# Explore 子Agent 任务上下文

Last Updated: 2025-11-19

## 1. 关键目标与范围

- 在现有 Codex Mini 架构中新增 Explore 子Agent 类型和对应工具，用于代码库的快速/深入探索；
- 支持通过配置选择独立的 Explore 模型；
- 更新主 Agent Prompt 的工具使用策略，引导在探索类问题上优先调用 Explore 子Agent；
- 保证所有变更对现有 Task/Oracle/主 Agent 工作流无破坏。

## 2. 关键代码文件与位置

> 以下路径与行号基于当前仓库快照，仅作为对齐上下文使用，具体行号在后续改动中可能发生偏移。

### 2.1 工具与子Agent 定义

- 工具常量与子Agent 类型：
  - `src/codex_mini/protocol/tools.py:3-13`：定义各工具名称常量（`BASH`, `APPLY_PATCH`, `READ`, `TASK`, `ORACLE`, `SKILL` 等）；
  - `src/codex_mini/protocol/tools.py:15-17`：`SubAgentType` 枚举，目前仅包含 `TASK`, `ORACLE`；
  - 未来将在此处加入 `EXPLORE` 常量与 `SubAgentType.EXPLORE`。

- 工具注册与工具集选择：
  - `src/codex_mini/core/tool/tool_registry.py:13-31`：工具注册与 Schema 提取逻辑；
  - `src/codex_mini/core/tool/tool_registry.py:56-91`：主 Agent 工具列表选择；
  - `src/codex_mini/core/tool/tool_registry.py:94-98`：子Agent 工具列表选择，目前仅针对 TASK 与 ORACLE；
  - Explore 子Agent 将在此处接入只读工具集。

### 2.2 Task / Oracle 工具实现

- Task 工具：
  - `src/codex_mini/core/tool/task_tool.py:11-14`：`TaskArguments` 参数模型；
  - `src/codex_mini/core/tool/task_tool.py:16-42`：`TaskTool.schema()` 定义与描述文案；
  - `src/codex_mini/core/tool/task_tool.py:60-81`：`TaskTool.call()` 逻辑，通过 `SubAgentType.TASK` 启动子Agent。

- Oracle 工具：
  - `src/codex_mini/core/tool/oracle_tool.py:11-16`：`OracleArguments` 参数模型；
  - `src/codex_mini/core/tool/oracle_tool.py:21-77`：`OracleTool.schema()` 描述与参数定义；
  - `src/codex_mini/core/tool/oracle_tool.py:80-108`：`OracleTool.call()` 逻辑，通过 `SubAgentType.ORACLE` 启动子Agent。

### 2.3 Prompt 与策略

- 主 Agent Prompt（Claude Code）：
  - `src/codex_mini/core/prompt_claude_code.md:6-12`：语气与简洁性要求；
  - `src/codex_mini/core/prompt_claude_code.md:57-66`：最终回答结构与风格；
  - `src/codex_mini/core/prompt_claude_code.md:130-135`：当前 `# Tool Usage Policy`，尚未包含 Explore 子Agent 的使用策略。

- 子Agent Prompt：
  - `src/codex_mini/core/prompt_subagent_explore.md:1-25`：Explore 子Agent 的系统提示，强调：
    - 只读探索；
    - 使用 `fd`/`rg`/`Read` 等工具；
    - 返回绝对路径等规范要求。
  - 目前未在 `get_system_prompt` 中通过 `key="explore"` 显式使用，需要在未来接入。

- Prompt 路由：
  - `src/codex_mini/core/prompt.py:7-20`：`get_system_prompt` 根据 `key` 选择不同 Prompt 文件（`main/task/oracle`）。

### 2.4 Agent 与执行器

- Agent 结构：
  - `src/codex_mini/core/agent.py:25-30`：`AgentLLMClients`，目前字段：`main`, `fast`, `task`, `oracle`；
  - `src/codex_mini/core/agent.py:31-37`：`get_sub_agent_client` 对 TASK/ORACLE 的模型选择逻辑；
  - `src/codex_mini/core/agent.py:461-490`：`refresh_model_profile` 根据 `SubAgentType` 选择 Prompt、工具与提醒；
  - `src/codex_mini/core/agent.py:499-507`：`_resolve_llm_client_for` 根据 `SubAgentType` 选择 LLM 客户端。

- 执行器：
  - `src/codex_mini/core/executor.py:171-211`：`_run_agent_task`，封装主 Agent 的任务执行；
  - `src/codex_mini/core/executor.py:217-257`：`_run_subagent_task`，负责：
    - 创建子 Session 并设置 `sub_agent_type`；
    - 使用 `get_sub_agent_client` 构造子Agent；
    - 调用 `refresh_model_profile(sub_agent_type)` 切换 Prompt 与工具；
    - 汇总子Agent 最终结果为 `SubAgentResult`。

### 2.5 配置与示例

- 配置结构：
  - `src/codex_mini/config/config.py:20-24`：`ModelConfig` 定义；
  - `src/codex_mini/config/config.py:26-35`：`Config`，目前字段包括 `main_model`, `task_model`, `oracle_model`；
  - `src/codex_mini/config/config.py:36-57`：`get_main_model_config` 与 `get_model_config`，根据 `model_list` 与 `provider_list` 构建 `LLMConfigParameter`；
  - `src/codex_mini/config/config.py:73-121`：`get_example_config` 示例配置。

## 3. 关键设计决策与约束

- Explore 作为独立子Agent 类型：
  - 不通过 Task 的 `subagent_type` 概念在实现层复用，而是新增 `SubAgentType.EXPLORE` 与独立工具；
  - 主 Agent Prompt 文案仍可以沿用“使用 Task 工具并指定 subagent_type=Explore”的表述，对用户透明底层实现。

- 只读 vs 工具全集：
  - 用户需求文本中给出 “(Tools: All tools)”；
  - 但 `prompt_subagent_explore.md` 明确强调只读和禁止文件写操作；
  - 规划上优先遵守 Prompt，只将只读工具暴露给 Explore 子Agent，后续如需放开写操作再统一调整。

- 配置兼容性：
  - 新增 `explore_model` 时必须保持旧配置可用；
  - Explore 未配置专属模型时应回退到 main 模型，避免引入必填项。

## 4. 依赖关系总结

- 对协议与类型的依赖：
  - 所有 Explore 相关实现依赖 `protocol/tools.py` 中新增的 `EXPLORE` 常量与 `SubAgentType.EXPLORE`。 

- 对 Agent/Executor 的依赖：
  - Explore 工具通过 `current_run_subtask_callback` 与 `_run_subagent_task` 调用子Agent；
  - 因此任何对子Agent 类型的扩展必须同时调整：
    - `AgentLLMClients` 与 `get_sub_agent_client`；
    - `Agent.refresh_model_profile` 的 Prompt/工具选择逻辑。

- 对 Prompt 的依赖：
  - Explore 子Agent 依赖 `prompt_subagent_explore.md` 提供的系统提示；
  - 主 Agent 行为依赖 `prompt_claude_code.md` 中的 Tool Usage Policy 文案引导是否调用 Explore。

- 对配置的依赖：
  - `Config` 中的 `explore_model` 将影响 Explore 子Agent 使用哪个模型；
  - 示例配置应帮助用户理解配置方式，但不强制用户必须配置。

## 5. 未决问题与需要确认的点

- Explore 工具对外名称与 UI 展示：
  - 是否在 UI 中单独展示 Explore 工具；
  - 还是主要通过 Task 工具的“子Agent 类型”概念对外暴露。

- 工具集范围：
  - 是否需要为 Explore 提供 TodoWrite 以便记录探索过程中的子任务；
  - 是否未来会允许 Explore 进行轻度代码修改（目前规划保持只读）。

- 配置默认值：
  - 是否需要在 `get_example_config` 中显式展示 `explore_model` 配置（哪一个模型更适合作为默认 Explore 模型）。

本上下文文档将随着实现推进进行更新，确保后续开发与 Review 均能快速获取关键背景信息。
