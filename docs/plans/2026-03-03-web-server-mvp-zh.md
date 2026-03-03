# Web 服务器 MVP 计划（拆分版）

> **针对 Claude:** 使用 executing-plans 技能按阶段执行。先完成后端计划并通过完整 API 测试，再进入前端计划。

## 目标（更新）

1. `klaude web` 默认同时拉起后端 API 与前端 Web UI，并自动打开浏览器。
2. 源码安装与 PyPI 安装保持同一用户体验：执行 `klaude web` 后都能直接进入可用 Web 界面。
3. 左侧 Session 栏提供“新建 Session”按钮；进入页面时默认详情页为“新 Session（草稿）”，在发送首条消息时才创建真实 session。
4. 计划拆分为：
   - **后端计划**：含完整 API 测试（REST + SSE + 文件访问安全 + 启动行为）。
   - **前端计划**：以后端 API 完成为前置条件。

---

## 执行顺序

### 阶段 A（必须先完成）

- 文档：`docs/plans/2026-03-03-web-server-mvp-backend-zh.md`
- 退出条件：
  - 所有后端 API 测试通过。
  - `klaude web` 默认启动行为满足目标 1/2。

### 阶段 B（仅在阶段 A 完成后）

- 文档：`docs/plans/2026-03-03-web-server-mvp-frontend-zh.md`
- 退出条件：
  - Session 栏“新建 Session”入口可用。
  - 默认详情页为新 Session 草稿（首条消息时创建）。
  - 前端与后端契约一致，手动 smoke 通过。

---

## 交付物

- 后端实现与测试：见后端计划文档
- 前端实现与测试：见前端计划文档
- 设计约束同步更新：`docs/web/1-execution-architecture.md`、`docs/web/2-frontend-and-api-design.md`
