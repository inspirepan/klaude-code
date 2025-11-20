# SubAgent 架构简化任务清单

Last Updated: 2025-11-19

## Phase A：Profile 与客户端
- [ ] A1 定义 `SubAgentProfile` + 注册接口
- [ ] A2 `AgentLLMClients` 改为 dict 化结构

## Phase B：配置与 CLI
- [ ] B1 `Config` 新增 `subagent_models` 并兼容旧字段
- [ ] B2 CLI 初始化遍历 profile 创建 LLM 客户端

## Phase C：工具与 Prompt 路由
- [ ] C1 `tool_registry` 主/子 Agent 工具由 profile 派生
- [ ] C2 `Agent.refresh_model_profile` / `get_system_prompt` 接入 profile

## Phase D：UI 与日志
- [ ] D1 UI 渲染根据统一子 Agent 工具集合，并移除 Oracle 子 Agent 独占的 thinking 展示逻辑
- [ ] D2 日志/事件增加 profile 名称（可选）

## Phase E：迁移与测试
- [ ] E1 Explore/Task/Oracle 改用 profile；清理旧枚举
- [ ] E2 新增/更新单元测试与回归验证
