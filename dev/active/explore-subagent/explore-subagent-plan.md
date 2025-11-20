# Explore 子Agent 规划

Last Updated: 2025-11-19

## 一、执行概要（Executive Summary）

- 目标：新增 Explore 子Agent 与对应工具，用于高效、只读地探索代码库（查找文件、搜索关键字、理解结构），并支持独立模型配置与“搜索彻底程度”参数。
- 范围：
  - 在工具层面新增 Explore 工具（类似 Task/Oracle），通过子 Agent 调用执行探索任务；
  - 在协议与执行层面扩展 `SubAgentType`、子 Agent LLM 选择与 Prompt 路由；
  - 更新主 Agent Prompt 的 Tool Usage Policy，强制在非精确 Needle 查询时使用 Explore 子Agent；
  - 在配置层面为 Explore 引入独立的 `explore_model` 配置项；
  - 产出本任务的中文规划文档与任务清单。
- 关键设计决策：
  - Explore 作为独立子Agent 类型存在（新增 `SubAgentType.EXPLORE`），不复用 Task 的 `subagent_type` 字段；
  - Explore 子Agent 的系统提示使用现有 `prompt_subagent_explore.md`，并在工具可见性上支持“工具全集”，但在提示中仍强调只读约束；
  - 主 Agent prompt 中允许使用“Task tool with subagent_type=Explore”这一文案以贴合用户习惯，实际实现为 Explore 子Agent。

## 二、现状分析（Current State Analysis）

### 2.1 工具与子Agent 体系

- 工具枚举与子Agent 类型：
  - `src/klaude_code/protocol/tools.py:3-12` 定义了工具常量 `BASH`, `APPLY_PATCH`, `EDIT`, `READ`, `TASK`, `ORACLE`, `SKILL`，暂未包含 Explore；
  - `SubAgentType` 目前仅包含：
    - `TASK = TASK`
    - `ORACLE = ORACLE`（`src/klaude_code/protocol/tools.py:15-17`）。
- 工具注册与子Agent 工具集：
  - `get_main_agent_tools` 基于 `model_name` 返回主 Agent 可用工具，包含 `TASK`、`ORACLE` 等（`src/klaude_code/core/tool/tool_registry.py:56-90`）；
  - `get_sub_agent_tools` 仅支持：
    - Task 子Agent：`[BASH, READ, EDIT]`（可读写）；
    - Oracle 子Agent：`[READ, BASH]`（只读）；
    - 未对 Explore 做分支处理（`src/klaude_code/core/tool/tool_registry.py:94-98`）。

### 2.2 现有 Task / Oracle 工具

- Task 工具（`TaskTool`）：
  - 文件：`src/klaude_code/core/tool/task_tool.py`
  - 参数：`description`, `prompt`（`TaskArguments`，`src/klaude_code/core/tool/task_tool.py:11-14`）；
  - 描述：用于启动复杂、多步骤任务的子Agent，强调何时/何时不应使用 Task（`schema.description`，`src/klaude_code/core/tool/task_tool.py:23-41`）；
  - 调用：通过 `current_run_subtask_callback` 获取 runner，并以 `SubAgentType.TASK` 启动子Agent（`src/klaude_code/core/tool/task_tool.py:67-73`）。
- Oracle 工具（`OracleTool`）：
  - 文件：`src/klaude_code/core/tool/oracle_tool.py`
  - 参数：`context`, `files`, `task`, `description`（`OracleArguments`，`src/klaude_code/core/tool/oracle_tool.py:11-16`）；
  - 描述：高端推理 Advisor，支持规划、Review、复杂问题分析（`schema.description`，`src/klaude_code/core/tool/oracle_tool.py:25-53`）；
  - 调用：拼接上下文和文件列表后，以 `SubAgentType.ORACLE` 启动子Agent（`src/klaude_code/core/tool/oracle_tool.py:91-102`）。

### 2.3 Prompt 体系

- 主 Agent Prompt（Claude Code）：
  - 文件：`src/klaude_code/core/prompt_claude_code.md`
  - 在 `# Tool usage policy` 中仅有：
    - “When doing file search, prefer to use the Task tool...” 等原则性描述（`src/klaude_code/core/prompt_claude_code.md:130-133`）；
  - 尚未明确提到 Explore 子Agent，亦未有示例说明何时使用该子Agent。
- 子Agent Prompt：
  - Task / Oracle：通过 `get_system_prompt` 中的 `key == "task" / "oracle"` 分支加载不同 MD 文件（`src/klaude_code/core/prompt.py:8-20`）。
  - Explore：
    - 文件已存在：`src/klaude_code/core/prompt_subagent_explore.md`；
    - 内容定义为“file search specialist”，强调：
      - 严格只读（不得创建/修改文件）；
      - 使用 `fd`/`rg`/`Read` 等工具进行搜索（`src/klaude_code/core/prompt_subagent_explore.md:1-25`）；
    - 但目前未在 `get_system_prompt` 或 `Agent.refresh_model_profile` 中接入。

### 2.4 Agent 与执行器

- 子Agent LLM 选择：
  - `AgentLLMClients` 目前字段：`main`, `fast`, `task`, `oracle`（`src/klaude_code/core/agent.py:25-30`）；
  - `get_sub_agent_client` 支持 `TASK` / `ORACLE`，其他类型回退到 `main`（`src/klaude_code/core/agent.py:31-37`）。
- Prompt 与工具选择：
  - `refresh_model_profile`：
    - 判断 `effective_sub_agent_type`，TASK/ORACLE 使用 `prompt_key = "task"/"oracle"`，其它使用 `"main"`（`src/klaude_code/core/agent.py:461-478`）；
    - 对 TASK/ORACLE：分别调用 `get_sub_agent_tools` 与 `get_sub_agent_reminders`，其余情况使用主 Agent 工具与提醒（`src/klaude_code/core/agent.py:480-490`）。
- 执行器 `ExecutorContext`：
  - `_run_subagent_task` 使用 `SubAgentType` 创建子 Session，并通过 `AgentLLMClients.get_sub_agent_client` 与 `Agent.refresh_model_profile(sub_agent_type)` 初始化子Agent（`src/klaude_code/core/executor.py:217-247`）。

### 2.5 配置体系

- `Config` 模型（`src/klaude_code/config/config.py:26-35`）：
  - 字段包含：`main_model`, `task_model`, `oracle_model` 等；
  - 尚无 `explore_model` 字段。
- 模型解析：
  - `get_main_model_config()` 返回 `main_model` 对应配置；
  - `get_model_config(model_name: str)` 根据 `model_list` 与 `provider_list` 拼装最终 `LLMConfigParameter`（`src/klaude_code/config/config.py:36-57`）。
- 示例配置：
  - `get_example_config` 提供 `gpt-5` 与 `sonnet-4` 两个示例模型，并设置 `main_model="gpt-5"`，未演示 `task_model/oracle_model` 的用法，更未包含 Explore（`src/klaude_code/config/config.py:73-121`）。

## 三、目标状态设计（Proposed Future State）

### 3.1 Explore 子Agent 类型

- 在协议层：
  - 新增工具常量 `EXPLORE = "Explore"`；
  - 在 `SubAgentType` 中增加 `EXPLORE = EXPLORE`；
  - 确保枚举可被序列化与日志打印，避免拼写差异。
- 在 LLM 客户端选择层：
  - `AgentLLMClients` 增加 `explore: LLMClientABC | None = None` 字段；
  - `get_sub_agent_client` 为 `SubAgentType.EXPLORE` 返回 `self.explore or self.main`，保持向后兼容。

### 3.2 Explore 工具（Tool）

- 新增 `ExploreTool`（命名暂定）至 `src/klaude_code/core/tool`：
  - 参考 `TaskTool` 与 `OracleTool` 结构，使用 `@register(EXPLORE)` 注册；
  - 工具 Schema：
    - 名称：`Explore`；
    - 描述（英文，对外暴露）：
      - 使用用户提供的文本描述（题中给出的长描述）作为 `description` 字段；
    - 参数字段示例：
      - `description: str`（任务短描述）；
      - `prompt: str`（需要执行的探索任务自然语言描述）；
      - `thoroughness: Literal["quick", "medium", "very thorough"]`（探索彻底程度）；
      - 可视需要增加 `focus_paths: list[str]` 等高级参数，但在首版中保持精简。
  - 调用逻辑：
    - 从 `arguments` JSON 反序列化到 `ExploreArguments`；
    - 通过 `current_run_subtask_callback` 的 runner 调用 `SubAgentType.EXPLORE`；
    - 拼接子Agent Prompt，将 `thoroughness` 明确传递给子Agent（例如作为前置信息或标签）；
    - 返回 `ToolResultItem`，`ui_extra` 为子 Session ID，便于 UI 重放。

### 3.3 Explore 子Agent Prompt 路由

- Prompt 路由：
  - 扩展 `get_system_prompt` 支持 key=`"explore"`，映射到 `prompt_subagent_explore.md`；
  - 在 `Agent.refresh_model_profile` 中：
    - 对 `SubAgentType.EXPLORE` 使用 `prompt_key = "explore"`；
    - 对 Explore 子Agent 调用 `get_sub_agent_tools` 和 `get_sub_agent_reminders`（如有单独提醒逻辑需求，可后续扩展）。
- 工具集路由：
  - 在 `get_sub_agent_tools` 中为 `SubAgentType.EXPLORE` 返回合适的工具集合：
    - 基本候选：`[BASH, READ]` 或 `BASH + READ + TODO_WRITE`;
    - 需要在设计上权衡：
      - 题面描述标注 “(Tools: All tools)”；
      - `prompt_subagent_explore.md` 强调“只读”，不应暴露 `EDIT`/`APPLY_PATCH` 等改写工具；
    - 规划建议：首版严格遵循只读原则，限制为 `[BASH, READ]`，后续若有需求再扩展。

### 3.4 主 Agent Prompt 与使用策略

- 更新 `prompt_claude_code.md` 中 `# Tool Usage Policy`：
  - 加入题面给出的英文段落：
    - 强调：在探索代码库获取上下文或回答非 Needle 类型问题时，必须使用 Task 工具并指定 `subagent_type=Explore`；
    - 提供两个使用 Explore 的示例（错误处理位置、代码结构等）；
  - 虽然实现层是独立 Explore 工具 + 子Agent 类型，但文案以“Task tool + subagent_type=Explore” 对外，兼顾既有认知与文案风格；
  - 确保新增段落紧接在现有 Tool Usage Policy 中现有规则之后，维持整体结构与口吻一致。

### 3.5 配置支持：独立 Explore 模型

- `Config` 模型：
  - 新增字段：`explore_model: str | None = None`；
  - 行为：若为 `None`，Explore 默认复用 `main_model`；
  - 为保持 API 简洁，暂不增加单独的 `get_explore_model_config` 方法，可由上层在构造 `AgentLLMClients` 时使用 `get_model_config(config.explore_model or config.main_model)`。
- 示例配置：
  - 在 `get_example_config` 的返回值中加入合理的注释示例（或最小改动保留当前模型列表，但在文档中解释如何配置 Explore 模型）；
  - 避免破坏现有兼容性，不强制用户立刻配置 Explore 模型。

### 3.6 文档与可观测性

- 当前任务文档：本 `*-plan.md` / `*-context.md` / `*-tasks.md` 即为主要中文文档，供后续实现与 Review 使用；
- 后续如有需要，可在用户文档或帮助命令中补充 Explore 使用说明（不在本次范围内，仅在任务清单中提供占位）。

## 四、实施阶段规划（Implementation Phases）

### Phase 1：协议与配置扩展（Types & Config）

- 扩展 `protocol/tools.py`：新增 `EXPLORE` 常量与 `SubAgentType.EXPLORE`；
- 扩展 `Config` 模型：新增 `explore_model` 字段，并确认 `load_config`/`save` 行为正常；
- 更新 `AgentLLMClients` 与 `get_sub_agent_client`，支持 Explore 子Agent 独立模型选择；
- 产出：类型定义完整，配置读写与回退逻辑清晰。

### Phase 2：Explore 工具与子Agent 接入

- 新增 `ExploreTool`，与 `TaskTool` / `OracleTool` 一致接入 executor；
- 扩展 `get_sub_agent_tools` 与 `Agent.refresh_model_profile`，使 `SubAgentType.EXPLORE` 使用 `prompt_subagent_explore.md` 与只读工具集；
- 确保 Explore 调用路径（Tool -> Executor `_run_subagent_task` -> Agent -> Explore Prompt）端到端打通。

### Phase 3：Prompt 更新与策略强化

- 修改 `prompt_claude_code.md`：在 `# Tool Usage Policy` 中加入 Explore 使用要求与示例；
- 审核 Explore Prompt 与工具集之间的契合度（只读 vs Tools: All tools），必要时在描述中加注说明；
- 可选：对 `prompt_subagent_explore.md` 做微调，以适配 `thoroughness` 参数的语义（例如在 Guidelines 中提及）。

### Phase 4：验证、测试与回归检查

- 手工验证典型场景：
  - 使用 Explore 查找错误处理位置；
  - 使用 Explore 总结代码结构；
- 如果已有测试基础，增加针对 Explore 的单元/集成测试（例如对 `get_sub_agent_tools`、配置加载的测试）；
- 检查日志与 UI 表现，确保 Explore 子Agent 的 Session/Tool 调用都可追踪与回放。

## 五、详细任务（Detailed Tasks）

> 说明：任务编号采用 `EX-[Phase].[Index]` 形式，每个任务给出依赖关系、验收标准与预估工作量（S/M/L/XL）。

### Phase 1：协议与配置

1. EX-1.1 新增 Explore 工具常量与子Agent 类型（S）
   - 内容：
     - 在 `src/klaude_code/protocol/tools.py` 中新增 `EXPLORE` 字符串常量；
     - 在 `SubAgentType` 中增加 `EXPLORE = EXPLORE` 枚举项；
   - 依赖：无；
   - 验收标准：
     - 代码完成类型检查；
     - 其他模块引用 `SubAgentType.EXPLORE` 不报错。

2. EX-1.2 扩展 AgentLLMClients 支持 Explore 模型（M）
   - 内容：
     - 在 `AgentLLMClients` 中新增 `explore: LLMClientABC | None` 字段；
     - 扩展 `get_sub_agent_client`，在遇到 `SubAgentType.EXPLORE` 时返回 `self.explore or self.main`；
   - 依赖：EX-1.1；
   - 验收标准：
     - 类型检查通过；
     - 现有 Task/Oracle 使用路径不受影响（回归跑通）。

3. EX-1.3 扩展 Config 支持 explore_model（M）
   - 内容：
     - 在 `Config` 中新增 `explore_model: str | None = None` 字段；
     - 视需要在创建 `AgentLLMClients` 的位置使用 `config.explore_model` 构造 Explore LLM 客户端；
     - 保证 `load_config` 在旧配置文件下依旧能成功解析（需考虑 `extra`/`allow_missing` 行为）。
   - 依赖：EX-1.1；
   - 验收标准：
     - 旧配置文件无需修改即可正常运行；
     - 在配置中设置 `explore_model` 时，Explore 子Agent 能使用对应模型。

4. EX-1.4 更新示例配置与文档注释（S）
   - 内容：
     - 在 `get_example_config` 或相关注释中说明如何配置 `explore_model`；
   - 依赖：EX-1.3；
   - 验收标准：
     - 新用户能通过示例快速理解 Explore 模型配置方式。

### Phase 2：Explore 工具与子Agent

5. EX-2.1 实现 Explore 工具 Schema 与参数模型（M）
   - 内容：
     - 新建 `ExploreArguments`（Pydantic 模型），包含 `description`, `prompt`, `thoroughness`；
     - 定义 `ExploreTool.schema()`，描述使用场景与参数字段；
   - 依赖：EX-1.1；
   - 验收标准：
     - 工具能够在 `list_tools()` 中被正确枚举；
     - OpenAPI / Tool Schema 结构与现有工具保持一致风格。

6. EX-2.2 实现 Explore 工具调用逻辑（M）
   - 内容：
     - 在 `ExploreTool.call` 中使用 `current_run_subtask_callback`，以 `SubAgentType.EXPLORE` 启动子Agent；
     - 将 `thoroughness` 信息嵌入子Agent prompt（例如在前缀文本中说明）；
     - 处理异常并返回带有 `session_id` 的 `ToolResultItem`。
   - 依赖：EX-2.1, EX-1.2；
   - 验收标准：
     - 在手动构造 Tool 调用时，能创建新的 Explore Session 并返回结果；
     - 错误情况下返回明确的 error status 与信息。

7. EX-2.3 为 Explore 子Agent 配置工具集（S）
   - 内容：
     - 在 `get_sub_agent_tools` 中增加 Explore 分支，默认仅提供 `[BASH, READ]`；
     - 再次确认 `prompt_subagent_explore.md` 中的只读约束与工具集保持一致。
   - 依赖：EX-1.1；
   - 验收标准：
     - Explore 子Agent 内仅能使用只读相关工具，无法调用 EDIT/APPLY_PATCH 等写操作工具；
     - 不影响 Task/Oracle 的工具列表。

8. EX-2.4 将 Explore Prompt 接入刷新逻辑（M）
   - 内容：
     - 在 `Agent.refresh_model_profile` 中为 `SubAgentType.EXPLORE` 增加分支：
       - 设定 `prompt_key = "explore"`；
       - 使用 `get_sub_agent_tools(..., SubAgentType.EXPLORE)` 与 `get_sub_agent_reminders`（如需要）；
     - 在 `get_system_prompt` 中支持 `key == "explore"` 时读取 `prompt_subagent_explore.md`。
   - 依赖：EX-1.1, EX-2.3；
   - 验收标准：
     - Explore 子Agent 启动时的系统 Prompt 为 `prompt_subagent_explore.md` 内容；
     - Task/Oracle/主 Agent 的行为无回归。

### Phase 3：Prompt 与策略

9. EX-3.1 更新 Tool Usage Policy 文案（M）
   - 内容：
     - 在 `prompt_claude_code.md` 的 `# Tool Usage Policy` 追加题目中给定的英文段落；
     - 确保示例与内部实现的一致性（文案提到 Task+Explore，实际实现为 Explore 子Agent，需要在内部文档中解释）。
   - 依赖：EX-2.1-EX-2.4（建议在功能基本就绪后修改文案，减小不一致窗口）；
   - 验收标准：
     - Prompt 渲染结果中能看到关于 Explore 的新策略说明；
     - 语言风格与现有内容保持一致。

10. EX-3.2 （可选）在 Explore Prompt 中加入 thoroughness 指南（S）
    - 内容：
      - 在 `prompt_subagent_explore.md` 中加入如何根据 `thoroughness` 调整搜索范围与策略的说明；
    - 依赖：EX-2.1, EX-2.2；
    - 验收标准：
      - Explore 子Agent 在不同 `thoroughness` 参数下能给出风格上明显不同的搜索深度。

### Phase 4：验证与测试

11. EX-4.1 手工验证典型用例（M）
    - 内容：
      - 在 CLI 中通过 Explore 调用实现如下场景：
        - 问题一：“Where are errors from the client handled?”；
        - 问题二：“What is the codebase structure?”；
      - 观察工具调用轨迹，确认实际使用 Explore 子Agent 而非直接 Bash 搜索。
    - 依赖：Phase 1-3 完成；
    - 验收标准：
      - 上述问题给出合理答案，并列出关键文件路径；
      - 工具调用记录中包含 Explore 工具与对应子 Session。

12. EX-4.2 新增或更新测试用例（M）
    - 内容：
      - 若项目中已有 Tool/Agent/Config 层的测试，则：
        - 为 `SubAgentType.EXPLORE` 与 `get_sub_agent_tools` 补充测试；
        - 为 `Config` 的 `explore_model` 读写补充测试；
      - 如暂时缺失测试框架，则将此任务标记为后续优化项。
    - 依赖：Phase 1-2 完成；
    - 验收标准：
      - `uv run pytest` 通过；
      - 覆盖率中包含 Explore 相关分支（如有覆盖率报告）。

13. EX-4.3 回归与文档确认（S）
    - 内容：
      - 回顾本任务相关代码变更，确认未影响现有 Task/Oracle 行为；
      - 校对 Prompt 与配置示例中的文案与最终实现一致；
    - 依赖：Phase 1-3 完成；
    - 验收标准：
      - 手动 Spot Check 未发现明显回归；
      - 文档中的路径与 API 名称均可在代码中找到对应实现。

## 六、风险评估与缓解策略（Risk Assessment & Mitigation）

- 文案与实现不一致风险：
  - 风险：Prompt 中提到 “Task tool with subagent_type=Explore”，而实现为独立 Explore 工具与子Agent；
  - 缓解：
    - 在内部文档中清晰说明这一映射关系；
    - 若未来 UI 或 CLI 需暴露底层实现细节，再同步调整文案。
- 只读约束与“Tools: All tools” 的冲突：
  - 风险：题目描述为 “(Tools: All tools)”，但 Explore Prompt 要求只读；
  - 缓解：
    - 首版按 Prompt 要求，仅暴露只读工具；
    - 在后续版本中，如需支持改写，可先调整 Prompt，再扩展工具集。
- 配置兼容性：
  - 风险：增加 `explore_model` 可能影响现有配置文件解析；
  - 缓解：
    - 保持该字段为可选，旧配置默认不设置；
    - 在测试中覆盖旧配置场景。
- 性能与费用：
  - 风险：Explore 子Agent 若频繁被调用，可能增加 Token 消耗与延迟；
  - 缓解：
    - 通过 `thoroughness` 区分搜索深度，引导在简单问题上使用 `quick`；
    - 在后续监控与优化任务中，评估实际调用频率与成本。

## 七、成功度量（Success Metrics）

- 功能正确性：
  - Explore 工具可以被主 Agent 可靠调用，并产出预期的代码搜索结果；
  - 对典型问题（错误处理位置、代码结构）给出清晰、可复现的回答。
- 体验与效率：
  - 相比直接使用 `rg`/`fd` 等命令，使用 Explore 时，用户能更少地手动操作即可获取关键文件与片段；
  - 在 `quick` 模式下响应足够快，在 `very thorough` 模式下覆盖范围显著更广。
- 稳定性与兼容性：
  - 现有 Task/Oracle 功能无回归，CLI 工作流保持稳定；
  - 旧配置无需修改即可继续使用，新增 Explore 仅为增量能力。

## 八、资源与依赖（Required Resources & Dependencies）

- 人力：
  - 1 名熟悉本仓库结构与 Python 类型系统的工程师；
  - 视需要 1 名对产品体验敏感的同学配合调优 Prompt 文案。
- 代码依赖：
  - 依赖现有 Tool/Agent/Executor/Config 基础设施，无额外三方库需求；
  - 如需增加测试，依赖现有 pytest 与 uv 流程。
- 运营与配置：
  - 若 Explore 使用单独模型，需在实际部署环境中配置好对应 provider/api key；
  - 需要用户在本地 `~/.klaude/config.yaml` 中按需配置 `explore_model`。

## 九、时间预估（Timeline Estimates）

- Phase 1（协议与配置）：
  - 预估：0.5-1 人日（含类型扩展、Config 调整与回归检查）。
- Phase 2（工具与子Agent 接入）：
  - 预估：1-1.5 人日（实现 ExploreTool、子Agent 工具集与 Prompt 路由）。
- Phase 3（Prompt 与策略）：
  - 预估：0.5 人日（修改 Prompt、对齐文案与实现）。
- Phase 4（测试与验证）：
  - 预估：0.5-1 人日（手工验证、测试补充与回归确认）。

整体上，本任务可在约 3 人日内完成首版落地，视测试覆盖与文案打磨程度有所浮动。
