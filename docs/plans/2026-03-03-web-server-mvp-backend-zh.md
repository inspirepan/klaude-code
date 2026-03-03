# Web 服务器 MVP：后端计划（含完整 API 测试）

> **前置:** 无。该计划必须先于前端计划完成。

## 后端目标

1. `klaude web` 默认启动后端 API + 前端入口，并自动打开浏览器。
2. 在源码环境与 PyPI 安装环境都提供同样默认行为（开箱可用 Web UI）。
3. 提供稳定的 `/api` 契约，供前端后续直接接入。
4. 覆盖完整 API 自动化测试。

---

## 任务 1：依赖与打包基线

**文件：**
- 修改: `pyproject.toml`

**步骤：**
1. 保持 `fastapi`/`uvicorn`/`sse-starlette` 归入 `web` extra。
2. 明确前端构建产物（`web/dist`）在打包时被包含到 wheel/sdist。
3. 验证：
   - `uv sync --extra web`
   - `uv build` 后检查产物含静态文件（若有 dist）

**验收标准：**
- 不安装 `web` extra 时不引入 web 依赖。
- 安装 `web` extra 可正常运行 `klaude web`。

---

## 任务 2：Web 适配层与 API 应用

**文件：**
- 创建/修改: `src/klaude_code/web/app.py`
- 创建/修改: `src/klaude_code/web/display.py`
- 创建/修改: `src/klaude_code/web/interaction.py`
- 创建/修改: `src/klaude_code/web/routes/*.py`

**步骤：**
1. 实现 WebDisplay 与 WebInteractionHandler（复用核心端口抽象）。
2. 完成 API 路由：
   - `GET /api/sessions`
   - `POST /api/sessions`
   - `POST /api/sessions/{id}/message`
   - `POST /api/sessions/{id}/interrupt`
   - `POST /api/sessions/{id}/respond`
   - `POST /api/sessions/{id}/model`
   - `GET /api/sessions/{id}/history`
   - `GET /api/sessions/{id}/events` (SSE)
   - `GET /api/files`
3. 明确 `POST /api/sessions` 的语义：用于“新建 Session”按钮，以及默认新会话草稿在发送首条消息时的懒创建。

**验收标准：**
- API 返回码、响应结构与文档一致。
- SSE 能按 `session_id` 正确推流。
- 文件端点具备路径白名单保护。

---

## 任务 3：`klaude web` 启动编排（默认前后端同启 + 自动打开）

**文件：**
- 创建/修改: `src/klaude_code/web/server.py`
- 修改: `src/klaude_code/cli/main.py`

**步骤：**
1. 默认行为：
   - 启动后端 API。
   - 启动前端入口（见“运行模式”）。
   - 自动打开浏览器到前端 URL。
2. 运行模式：
   - **源码开发环境**：优先启动前端 dev server（如 Vite）并代理 `/api`。
   - **PyPI/无 Node 环境**：回退到后端托管内置 `web/dist` 静态资源。
3. CLI 选项至少保留：`--host`、`--port`、`--no-open`、`--debug`（可扩展）。
4. Ctrl+C 时同时清理 API 服务、前端子进程（若有）和 runtime 任务。

**验收标准：**
- `klaude web` 一条命令进入可用页面。
- PyPI 安装后运行体验与源码环境一致（不要求实现方式一致）。

---

## 任务 4：完整后端 API 测试

**文件：**
- 创建/修改: `tests/test_web_display.py`
- 创建/修改: `tests/test_web_interaction.py`
- 创建/修改: `tests/test_web_app.py`
- 创建/修改: `tests/test_web_server_startup.py`

**测试范围（必须覆盖）：**

1. **适配层单测**
   - WebDisplay 多订阅者分发、按 session 过滤、断开清理。
   - WebInteractionHandler 请求挂起、响应回填、pending 查询。

2. **API 契约测试（REST）**
   - sessions/list/create/message/interrupt/respond/model/history。
   - 错误路径（无效 session、无效参数、busy/rejected）。

3. **SSE 流测试**
   - `event`/`id`/`data` 结构。
   - 同 session 连续事件 seq 单调递增。
   - 不同 session 过滤正确。

4. **文件访问安全测试**
   - 允许：session images、work_dir、`/tmp`。
   - 拒绝：路径穿越、白名单外路径。

5. **启动行为测试**
   - 默认启动流程会触发“前后端同启”分支。
   - `--no-open` 不打开浏览器。
   - 前端 dev server 不可用时可回退静态托管。

6. **打包场景测试（关键行为）**
   - 模拟“仅安装包”环境下，`klaude web` 仍可打开前端页面并可访问 `/api/sessions`。

**验收标准：**
- `pytest tests/test_web_*.py -v` 全通过。
- 与 `make test`、`make lint` 不冲突。

---

## 完成定义（DoD）

- 后端 API 文档与实现一致。
- 默认启动与 PyPI 场景行为一致（一键可用）。
- 自动化测试覆盖完整且稳定。
