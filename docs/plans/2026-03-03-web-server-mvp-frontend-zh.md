# Web 服务器 MVP：前端计划（后端完成后执行）

> **前置（强制）：** 后端计划已完成，API 契约冻结并测试通过。

## 前端目标

1. 左侧 Session 栏新增“新建 Session”按钮。
2. 页面默认详情态为“新 Session 草稿”（不立即创建，发送首条消息时创建并选中）。
3. 基于后端已稳定 API，完成消息流、输入区、状态栏与工具渲染。

---

## 任务 1：基础工程与布局壳

**文件：**
- `web/src/App.tsx`
- `web/src/components/sidebar/*`
- `web/src/components/layout/MainPanel.tsx`

**步骤：**
1. 完成双栏布局与移动端抽屉侧边栏。
2. 在 Session 栏顶部添加“新建 Session”按钮（主入口）。
3. MainPanel 支持三种状态：
   - 初始化加载中
   - 默认新 Session 草稿（可直接输入）
   - 历史 Session 详情

**验收标准：**
- 侧边栏按钮始终可见且可触发创建。
- 无选中历史会话时，详情区默认展示新 Session 草稿。

---

## 任务 2：状态管理与 API 对接

**文件：**
- `web/src/stores/app-store.ts`
- `web/src/stores/session-store.ts`
- `web/src/api/client.ts`
- `web/src/api/sse.ts`

**步骤：**
1. 首次加载流程调整为：
   - `GET /api/sessions` 拉取列表。
   - 进入“新 Session 草稿”详情态（仅前端状态，无 session_id）。
   - 用户发送首条消息时再 `POST /api/sessions` 创建新 session。
   - 创建成功后发送首条消息，并建立 SSE 与历史状态。
2. “新建 Session”按钮复用同一草稿逻辑（进入草稿页，不立即创建）。
3. 断线重连和切换 session 时保持 SSE 生命周期正确。

**验收标准：**
- 每次进入页面默认落在新会话草稿详情。
- 点击“新建 Session”进入草稿页；发送首条消息后稳定创建并切换。

---

## 任务 3：消息流、输入区、状态栏

**文件：**
- `web/src/components/messages/*`
- `web/src/components/input/*`
- `web/src/components/status/StatusBar.tsx`

**步骤：**
1. 按既定映射渲染 user / assistant / thinking / tool / interaction 事件。
2. InputArea 对当前 session 提供 send/stop/model 操作。
3. StatusBar 展示上下文占用、模型、时长等状态。

**验收标准：**
- 新会话默认可直接发送消息并看到完整流式响应。
- 切换历史会话可回放并继续对话。

---

## 任务 4：联调与回归

**验证清单：**
1. 打开 `klaude web` 后浏览器自动进入页面。
2. 默认详情页为新 Session 草稿（首条消息才创建）。
3. 左侧按钮可连续进入新草稿；各草稿发送首条消息后可创建多个 session。
4. 新旧 session 切换、SSE 重连、发送/中断均正常。
5. 工具渲染（Read/Edit/Bash/WebSearch/Todo）与交互请求可用。

**完成定义（DoD）：**
- 前端行为与后端契约一致。
- 关键交互 smoke 测试通过。
