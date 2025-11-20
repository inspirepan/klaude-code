# SubAgent 架构简化方案

Last Updated: 2025-11-19

## Executive Summary
- 目标：以配置化/注册表驱动的方式统一管理 SubAgent 定义，使新增 Explore 这类子 Agent 不再需要在多处手工枚举，降低后续拓展成本 ≥70%。
- 价值：工程师只需编写一份 SubAgent Profile，即可自动获得工具可见性、Prompt 路由、LLM 配置加载、UI 渲染能力，减少易错点并提升一致性。
- 成功标准：新增子 Agent 时，除自身业务逻辑外，最多修改 1-2 个集中入口文件即可完成功能接入，且现有 Task/Oracle/Explore 全量回归通过。

## Current State Analysis
- **多点硬编码**：`src/klaude_code/core/agent.py`、`core/tool/tool_registry.py`、`ui/repl/renderer.py` 等多处以 if/elif 枚举 TASK/ORACLE/EXPLORE，耦合严重。
- **配置分散**：`Config` 中为每个子 Agent 单独设字段（`task_model`/`oracle_model`/`explore_model`），CLI 初始化时逐一解析，难以扩展。
- **工具/Prompt 路由重复**：`get_sub_agent_tools` 与 `Agent.refresh_model_profile` 同步维护提示词与工具集，缺乏统一来源。
- **UI 渲染不可扩展**：REPL 渲染层只识别 Task/Oracle/Explore，未来添加类型需再次修改。
- **缺少元数据层**：目前没有集中描述“子 Agent → Prompt key、工具集、只读策略、LLM 配置字段”等信息的结构。

## Proposed Future State
- 以 `SubAgentProfile` 注册表为唯一事实来源，字段包含：`type`、`tool_name`、`prompt_key`、`config_field`、`tool_policy`、`ui_behavior` 等。
- `AgentLLMClients` 持有 `dict[SubAgentType, LLMClientABC]`，`get_sub_agent_client`/`Executor` 等组件通过 profile 自动路由。
- `Config` 中统一维护 `subagent_models: dict[str, str]`，并提供兼容层将旧字段映射到新结构；示例配置/CLI 初始化均走通用逻辑。
- 工具/Prompt/Reminders/UI 均通过 profile 派生：`get_sub_agent_tools` 根据 profile/tool policy 决定暴露能力，UI 根据集合识别“子 Agent 工具”。
- 允许在 profile 中声明只读/可写策略，后续新增写操作型子 Agent 亦可直接配置。

## Implementation Phases
1. **Phase A：Profile 与客户端基础** — 引入 `SubAgentProfile`、重构 `AgentLLMClients`、提供统一查询 API。
2. **Phase B：配置与 CLI 初始化改造** — 调整 `Config` Schema、兼容旧字段、以 profile 驱动 LLM 客户端创建。
3. **Phase C：工具/Prompt/提醒路由** — 重写 `tool_registry`、`Agent.refresh_model_profile`、`get_system_prompt` 的调用路径。
4. **Phase D：UI 与可观测性** — REPL/Renderer/事件流使用统一集合，统一取消 Oracle 专属的子 Agent thinking 展示并记录 profile 名称方便调试。
5. **Phase E：迁移与测试** — 更新现有 Explore/Task/Oracle 接入逻辑、补充单元测试与回归验证。

## Detailed Tasks
| 编号 | 描述 | 依赖 | 验收标准 | 预估 |
| --- | --- | --- | --- | --- |
| A1 | 定义 `SubAgentProfile` 数据类（含 Prompt key、工具策略、配置键等），并提供注册/查询接口 | 无 | 能通过 `register_subagent(profile)` 获取 profile；单元测试覆盖查找/重复注册 | M |
| A2 | 将 `AgentLLMClients` 改为 `sub_clients: dict[SubAgentType, LLMClientABC | None]`，`get_sub_agent_client` 使用 profile | A1 | 现有 Task/Oracle/Explore 正常运行；新增类型无需修改该类 | M |
| B1 | `Config` 新增 `subagent_models`（dict），保留 task/oracle/explore 字段但在 model_validator 中迁移数据 | A2 | 旧配置可无修改加载；`config.subagent_models["Explore"]` 可获取值 | M |
| B2 | `cli/main.py` 初始化遍历 profile，根据 `config_field` 创建 LLM 客户端并存入 `sub_clients` | B1 | CLI 在仅配置 main 模型情况下仍可启动；配置 Explore 后能正确输出 Debug 信息 | M |
| C1 | `tool_registry.get_sub_agent_tools` 根据 profile.tool_policy 构建列表；主 Agent 工具集合自动包含所有 `profile.tool_name`（除非禁用） | B2 | Explore 继续只读；Task 仍含 EDIT；未来新 profile 仅需配置即可生效 | M |
| C2 | `Agent.refresh_model_profile` 使用 profile.prompt_key/工具策略；`get_system_prompt` 支持所有注册 key | C1 | 更换 sub agent 时 system prompt 与 tools 与 profile 定义一致；vanilla 模式不受影响 | M |
| D1 | `ui/repl/renderer` 与 `ui/renderers/tools` 通过 `SUB_AGENT_TOOL_NAMES` 判断渲染；颜色/Quote 逻辑复用 | C2 | 新增 profile 自动获得 Task 风格渲染；现有 UI 截屏无回归 | S |
| D2 | 事件与日志中记录 profile 名称，方便调试（可选） | D1 | Debug 日志可区分 sub agent | S |
| E1 | 迁移 Explore 接入到 profile；删除已无用的显式枚举；回归手测 | D1 | `uv run pytest` 全绿；Explore 手工测试通过 | M |
| E2 | 新增单元测试覆盖 profile 注册、配置迁移、CLI 初始化、工具路由 | E1 | 有针对 profile/Config/CLI 的测试；CI 通过 | M |

## Risk Assessment & Mitigation
- **兼容风险**：旧配置缺少 `subagent_models` 可能报错 → 通过 model_validator 自动迁移并在日志中提示。
- **性能影响**：Profile 查表增加轻微开销 → 使用缓存/常量 dict，影响可忽略。
- **测试缺口**：缺少针对 profile 的测试导致回归 → Phase E 加强单测覆盖。

## Success Metrics
- 新增子 Agent 时，除了自身业务逻辑，最多修改 2 个文件即可接入；通过代码审阅确认。
- 回归套件（`uv run pytest`、关键 CLI 手测）全部通过。
- 工程师反馈：新增子 Agent 所需时间减少至少 50%。

## Required Resources & Dependencies
- 1 名熟悉核心框架的 Python 工程师负责代码与测试。
- 可选 1 名产品/UX 人员确认 UI 行为。
- 依赖现有测试基础（pytest、uv），无额外外部服务需求。

## Timeline Estimates
- Phase A：0.5 人日
- Phase B：0.5-1 人日
- Phase C：1 人日
- Phase D：0.5 人日
- Phase E：0.5-1 人日
- 总计：约 2.5-4 人日（含回归）
