# SubAgent 架构简化上下文

Last Updated: 2025-11-19

## 关键代码位置
- `src/codex_mini/core/agent.py`: 子 Agent 客户端选择、Prompt/工具刷新逻辑，当前以 if/elif 硬编码 TASK/ORACLE/EXPLORE。
- `src/codex_mini/core/tool/tool_registry.py`: 主/子 Agent 工具可见性列表，需改造成 profile 驱动。
- `src/codex_mini/cli/main.py`: 根据配置加载 task/oracle/explore 模型，未来需要统一遍历 profile。
- `src/codex_mini/config/config.py`: `Config` 模型（含 task/oracle/explore 字段）与 `get_example_config`。
- `src/codex_mini/ui/repl/renderer.py`, `src/codex_mini/ui/renderers/tools.py`: Tool call 渲染层，目前只识别特定子 Agent。
- `src/codex_mini/core/prompt.py`, `prompt_subagent*.md`: Prompt 路由与模板资源。
- `src/codex_mini/core/executor.py`: `_run_subagent_task` 中对子 Agent 客户端复制逻辑。

## 现有设计约束
- 配置兼容性：必须兼容仅含 `main_model` 的旧配置；task/oracle/explore 字段短期内仍需支持。
- 工具策略：Explore 只读；Task 可写；Oracle 读/写受限（目前 READ+BASH）。
- UI 特例：Oracle 子 Agent 会显示 thinking，而其他子 Agent 不会；在本次改造中计划统一取消该特例。
- Prompt 选择：`prompt_key` 需与 `prompt_*.md` 文件对应，注册新子 Agent 同时需提供模板。

## 决策背景
- 目标是减少在多处枚举子 Agent 的重复劳动，采用集中元数据驱动。
- Profile 需支持扩展字段（如 UI 行为、只读策略、默认 thoroughness），确保未来新增类型无需重构核心代码。
- 允许通过 feature flag/配置关闭某些子 Agent（profile 中可包含 `enabled_by_default`）。

## 依赖
- 依赖现有 `uv run pytest`、`ruff`、`pyright` 工作流验证。
- 需与 Prompt/设计同学同步任何模板命名变更。
