# 独立 TUI 进程与 peer 通信重构计划

## 当前阶段

- 阶段 1–4 已实现；旧 WS/daemon、环境同步、attach/peek、`/reload` 与 `/detach` 已移除。
- 子 Agent、本地 IPC、独立 Headless 与 tmux 自动冒烟验收已通过；代码自查发现的 4 个问题已修复。
- 阶段 5 剩人工视觉验收和第二位审查者的独立审查。
- CLI 指南入口和历史列表优化已通过自动验收；用户已授权提交、推送 main 并发布 minor 版本 2.44.0。
- 内置 system skills、旧 checkout 和子模块升级流程已移除。

## 方向基线

1. 一个 TUI 进程拥有一场主对话及其子 Agent。
2. 终端多路复用器负责保持和切换终端；不再依赖统一 server 执行 TUI 会话。
3. 保留同类 Klaude 发现与消息能力，通过本机 IPC 连接独立进程。
4. 按此前讨论拆开全局会话管理、历史恢复和本会话任务管理。

## 当前实现事实

1. 普通启动与 `-c`、`-r` 使用进程内客户端；历史选择不连接 server。
   - `cli/main.py`、`cli/history.py`、`tui/client/local.py`。
2. Runtime 初始化/关闭复用 `app/runtime.py`；调度和会话状态从 server 移到 app。
   - `app/scheduler.py`、`app/runtime_facade.py`、`app/session_lease.py`。
3. 每进程 socket 登记可达会话；消息仍由接收方调度器持久化和排队。
   - `app/peer_endpoint.py`；保留 `PeerInfo`、`PeerMessage`、`PeerReceipt`。
4. Headless 由独立进程执行；在线 CLI 走 socket，离线 output/wait 读历史，离线 send 拒绝。
   - `cli/process_client.py`、`cli/process_worker.py`。
5. `klaude web` 不创建 Runtime；页面轮询落盘历史。
   - `server/read_only.py`、`server/web_state.py`、`web/src/app/session-page.tsx`。
6. 旧执行 server、WS/socket 客户端、环境同步、全局 AgentsPanel、CLI attach/peek、`/reload` 与 `/detach` 已移除。
   - `/exit` 保存并关闭本进程；内部会话切换使用 `switch_session`。
7. Web 列表使用 `/api/web/sessions`；移除旧执行状态字段和 WS history/meta observer。
8. 更新检查只提示显式执行 `klaude upgrade`；移除旧自动升级配置、代码指纹和通知钩子。

## 已确认决策

1. 每进程一个 Unix socket，直接通信，不引入常驻 broker。
2. TUI 正常退出时，有运行任务先确认；确认后停止所属 Agent/Shell 并保存历史。
   - 不保留 TUI 退出后的托管执行；断开终端多路复用器不等于退出 Klaude。
3. Peer 默认发现同工作目录的进程；保留本进程管理的父子关系。
4. 移除全局 `AgentsPanel` 及跨进程 attach/peek；保留 `-c`、`-r`、按 ID 恢复和 `/tasks`。
   - 活跃会话不得被第二个进程同时恢复执行。
   - `-r` 列表展示被其他进程持有的会话，但置灰、禁选；空闲但仍打开的会话同样禁选。
5. Headless 改为独立执行进程；在线查询和消息通过进程 socket，不依赖统一执行 server。
   - `klaude run` 默认后台启动并返回 session ID，可选等待完成。
   - 主任务结束后继续处理所属异步任务及完成报告；无任务和可执行待处理输入后保存结果并退出，不驻留等消息。
   - `ps` 默认只列在线进程，显式历史选项查看已退出记录；`output/wait` 可读取落盘输出与终态。
   - `send` 只向在线进程投递；离线时明确拒绝，不自动恢复，也不写离线收件箱。
6. `klaude web` 按需启动只读 Web server，持续刷新已落盘历史。
   - Web 不拥有会话 Runtime，不订阅执行进程内存状态，不提供会话执行控制。
7. `/new`、`/fork-session` 在原会话有运行任务时禁止切换，要求先显式停止任务。
8. 保留异步子 Agent、后台 Shell、完成报告、消息和 `/tasks`；只迁移执行归属，不取消异步能力。
9. 移除 `/reload`。
10. 移除重复的 `klaude agents` 列表；指南迁到 `klaude --skill`，help 显示 `Agent? Run: klaude --skill`。
    - `Available models` 只列可调用名称，不展示底层 model ID 映射。
11. `-r` 使用标题、工作目录、最近回复预览和时间分组的多行列表。
12. 不再维护内置 system skills 或 skills 子模块；用户和项目 skills 独立安装。

## 目标结构

当前主路径如下；HTTP server 仅用于只读 Web。

```text
klaude 进程 A                      klaude 进程 B
  TUI                               TUI
   ↕ 进程内调用与事件                ↕ 进程内调用与事件
  Runtime                           Runtime
   ├─ 主会话及子 Agent              ├─ 主会话及子 Agent
   └─ peer socket ←── 消息 ────────→ └─ peer socket

共享运行目录：活跃 endpoint 登记，不持有会话执行权
持久化历史：沿用现有格式
klaude web：独立只读 Web server，持续刷新持久化历史
```

1. 环境、凭证、代理与模型候选由所属进程解析；不再同步进共享 `os.environ`。
2. 保留操作协议、事件流、显示状态机与 event tape，不重写 Agent/TUI 渲染。
3. IPC 只负责发现与投递；队列、审批和执行调度归接收方 Runtime。

## 分阶段实施

用户已授权实施；仅对未确认的实质性产品选择另行确认。

### 阶段 1：本地 TUI 能完成一轮对话，不启动 server

- [x] 从 app/server 生命周期中分离可复用的本地 Runtime 初始化与关闭路径。
- [x] 通过现有 `RuntimeClient` 边界提供进程内适配；不另造执行引擎。
- [x] 普通 `klaude`、选模、操作提交、事件显示和审批在本进程完成。
- [x] 模型目录、配置管理、debug 等 runner 辅助调用不再隐式请求 server。
- [x] 验证：双进程使用不同环境时，模型列表与 Shell 环境互不覆盖。
- [x] 验证：首轮响应、AskUserQuestion 交互、Esc 中断、有任务时退出确认与停止刷盘；覆盖异常关闭。
- 代码入口：`app/runtime.py`、`app/runtime_facade.py`、`tui/client/base.py`、`tui/runner.py`、`cli/main.py`。
- 现有测试入口：`tests/app/test_app_runtime_close_session.py`、`tests/tui/test_runner_local.py`；将相关行为迁移到本地路径测试。

### 阶段 2：历史恢复与本会话任务管理脱离 attach

- [x] `-c`、`-r` 和按 ID 恢复改为本地历史选择与加载，不再连接远端会话。
- [x] 为会话建立单执行者约束；第二进程恢复活跃会话时明确拒绝。
- [x] 历史列表展示活跃会话并禁选；显式按 ID 恢复继续由执行锁兜底。
- [x] `/new`、`/fork-session` 在有运行任务时拒绝切换；无任务时在当前进程切换主会话。
- [x] 本地接入 `/tasks`、子 Agent 消息、后台 Bash、完成报告和 `/stop`。
- [x] 保留历史 replay 与实时事件的衔接；ctrl-o、ctrl-t、refresh 继续使用 event tape。
- [x] 验证：恢复既有历史不重复执行；同一会话不能被双进程执行。
- [x] 验证：异步子 Agent 不阻塞主对话，完成结果可回传并按现有规则唤醒主 Agent。
- [x] 验证：子任务状态、完成投递、问题交互与停止范围；不影响其他 Klaude 进程。
- 现有测试入口：`tests/agent/test_background_tasks.py`、`tests/tui/test_task_panel.py`；本地验收见 `tests/app/test_local_agent_e2e.py`、`tests/tui/test_local_runtime.py`。
- 迁移原则：保留行为断言，替换 server/WS 测试夹具；不为保留旧测试而保留旧架构。

### 阶段 3：两个独立 Klaude 可发现并发送消息

- [x] 按确认的范围登记本进程可达会话、endpoint 和状态；退出时撤销登记。
- [x] 实现 `PeerControlPort` 的跨进程适配；保留 `PeerInfo`、`PeerMessage`、`PeerReceipt`。
- [x] 接收方承担校验、持久化、幂等入队和本地 drain；不直接从 socket 回调启动模型。
- [x] 保留 busy 安全点读取、idle 唤醒、暂停/停止限制及 peer-only 连续执行上限。
- [x] 保留消息为非操作员输入的边界；父身份不得由自报 session ID 获得。
- [x] 验证：忙/闲投递、重试去重、queued 回执、断线和 SIGKILL 残留、身份与可达范围。
- [x] 验证：一个进程退出不影响另一个进程的对话与任务。
- 现有测试入口：`tests/app/test_peer_endpoint.py`、`tests/app/test_local_agent_e2e.py`、`tests/cli/test_peer_tasks_cli.py`。

### 阶段 4：Headless 独立执行，Web 只读历史，移除统一执行服务

- [x] Headless 使用独立进程拥有会话，并接入相同 Runtime 和 peer IPC 边界。
- [x] `run` 默认后台返回 session ID，支持等待；所属任务及完成报告收尾后保存结果并退出。
- [x] 迁移 `ps/send/wait/control/tasks` 等 CLI；在线操作走 socket，退出后的 `output/wait` 读取落盘结果。
- [x] `ps` 默认只列在线进程，显式选项查看历史；离线 `send` 拒绝投递，不自动启动接收方。
- [x] `klaude web` 按需启动只读 Web server；页面持续刷新落盘内容，不创建 Runtime 或控制执行。
- [x] 移除 `agents_panel.py` 及跨进程 attach/peek 浏览循环；历史选择器不依赖该面板。
- [x] 在新路径验证完成后，移除不再使用的 WS 适配、环境同步及 server 自动启动代码。
- [x] 更新帮助、README、相关 `AGENTS.md` 和旧 detach 语义。
- [x] 验证：普通交互启动不创建 daemon；历史恢复、peer 和 `/tasks` 不依赖全局面板。
- [x] 验证：Headless 与 TUI 不能争用同一会话；独立进程可查询和收消息。
- [x] 验证：Headless 默认后台、可选等待、异步任务收尾退出；退出后仍可查询输出与终态，离线消息被拒绝。
- [x] 验证：没有任何执行进程时 Web 仍可查看历史；新内容落盘后页面持续更新。
- 现有测试入口：`tests/cli/test_skill_guide.py`、`tests/cli/test_headless_cli.py`、`tests/server/test_web_api.py`。

### 阶段 5：回归与收尾

- [x] 各阶段运行对应测试：`uv run pytest <本阶段测试文件> -x -q --tb=short`。
- [x] 最终运行 `make format`、`make lint`、`make test`、`uv build`。
- [x] tmux 自动冒烟：两个真实 TUI、独立对话、消息、客户端断开重连与独立退出。
- [ ] 人工视觉验收：终端回放、输入焦点和交互弹窗。
- [x] 本会话代码自查：执行归属、IPC 身份、停止范围、关闭刷盘、回放顺序和失败传播。
- [ ] 第二位审查者的独立代码审查。

### 补充：CLI 指南与历史选择器

- [x] 移除 `agents`，统一用 `ps` 查看在线会话；`--skill` 输出指南，不启动 Runtime。
- [x] `Available models` 只列可调用名称；help 保留明确的 Agent 入口。
- [x] 历史卡片展示标题、目录、时间与两行最近回复；按日期分组并支持搜索。
- [x] 活跃会话置灰、禁选且可搜索；原进程退出后自动解锁；确认前及 Runtime 初始化时再次检查执行权。
- [x] 仅从落盘历史有限尾部读取回复预览；无可用回复时显示最近用户输入，不修改持久化格式。
- [x] 隔离 tmux 验收：120/60/40 列、12 行短终端、活跃结果 enter/tab 禁选、退出后在原列表恢复可选。
- [x] 最终 `make format`、`make lint`、`make test`、`uv build --offline`。
- 测试入口：`tests/cli/test_history.py`、`tests/cli/test_skill_guide.py`、`tests/tui/test_selector_disabled.py`。

### 补充：server 残留复查

- [x] `/detach` 注册、补全与实现改为 `/exit`；退出仍经过所属任务确认。
- [x] 删除旧升级握手、自动升级入口与配置；保留检查提示和手动升级。
- [x] 删除 WS history/meta observer、事件监听 tap、旧 history limit 接口及 live index 更新入口。
- [x] Web 改用历史列表路由；移除 `loaded`、`pending` 和 `live` context source。
- [x] 修复 `/rewind` 预加载后本地切换漏发 Welcome/replay；真实 LocalRuntime 回归覆盖一次回放且不重跑模型。
- [x] 更新包说明、帮助来源、示例数据及旧设计文档的历史标记。
- [x] 完整回归、真实双 TUI `/exit`、Web 构建与分发包验证。
- [x] 移除旧 skills checkout、本地子模块注册与 Git 元数据；删除升级同步、lint 排除和 system scope 展示。
- [x] 更新用户/项目 skills 的测试夹具；保留旧持久化 listing marker，兼容既有历史。

## 本期不做

- 不重写模型适配、工具实现、TUI 渲染或持久化历史格式。
- 不因本地化而取消审批、peer 安全边界或任务归属约束。
- 不保留 Web 会话控制或跨进程 TUI attach/peek。

## 验证与交接

1. 已验证
   - 移除内置 skills 后的全量非网络回归：3608 passed、1 skipped、4 deselected；skills/欢迎信息/升级/打包针对性回归 95 passed；此前 SIGKILL 执行锁/残留 endpoint 针对性验收 3 passed。
   - `make format`、`make lint` 通过；Web typecheck、157 项测试和 build 通过；`uv build --offline` 与分发包 Web 资源验证通过。
   - 2.44.0 发布前 `make pre-push` 全部通过：3608 passed、1 skipped、4 deselected；格式无改动，Web/wheel/sdist 构建和资源校验通过。
   - 假模型 + 真实 Runtime/工具/IPC：异步 Agent、报告一次投递、历史恢复不重跑、子问题路由、暂停后恢复、wait 被 follow-up 解除、Esc/stop-children/StopAll 范围。
   - Headless 子 Agent 继承 `hold/auto/deny`；`auto` 不代答问题；自由文本回答可到达模型。
   - 真实独立 Headless：主回答结束后等待子 Agent 报告，报告处理后退出；TUI 不能抢占其会话；SIGTERM 停止所属 Shell 并撤销登记。
   - 双进程 config/模型候选/Shell 环境隔离；peer 发现、身份降级、去重、限流、队列上限、落盘失败不确认、恢复重试和独立退出。
   - SIGKILL 后文件锁释放；残留登记不可发现，旧 socket 不可连接。
   - 只读 Web 没有 Runtime 或执行路由；落盘新增内容可见；状态仅反映持久化事实。
   - tmux 自动冒烟：隔离 HOME、假流式模型、两个真实 TUI；终端客户端断开/重连、断开期间处理消息、`/exit` 后另一方继续对话、退出后读取历史。
   - 历史选择器真实终端验收：120/60/40 列及 12 行；活跃会话搜索、enter/tab 禁选、原进程退出后实时解锁。预览/选择器/指南针对性回归 35 passed。
2. 测试迁移
   - scheduler/prevent-sleep 行为移到 `tests/app/`；共享假模型移到 `tests/fake_llm.py`。
   - 子 Agent、peer 和本地交互由 `test_local_agent_e2e.py`、`test_local_runtime.py`、`test_peer_endpoint.py`、`test_process_runtime.py` 验收。
   - 退役 WS 握手/重连/attach tape、daemon 升级和环境同步测试；保留显示 event tape、历史查询和只读 Web 断言。
   - 浏览器仅保留持久化历史合并及其测试；WS frames/reducer/splice 已删除。
   - 本次继续退役代码指纹、旧自动升级通知与 live context 专属测试；保留手动升级、JSONL 行数和历史上下文断言，增加预加载会话回放回归。
   - 移除旧 skills checkout 后不再收集其中 23 项测试；当前 wheel/sdist 已确认不含 `skill/assets`。
3. 代码自查已修复
   - 初始化状态可能把旧回合误报为新完成：保留 replay 序号边界，缓冲事件晚于实时状态消费也不会误报。
   - 本地与 IPC 控制操作失败仍可能返回成功：检查真实操作终态并向调用方返回失败。
   - `respond --text` / 无人值守文本回答丢失：按问答协议选中 `__other__`，真实工具链回归通过。
   - `/rewind` 预加载会话导致切换跳过欢迎信息和历史：初始化统一负责 Welcome/replay，不重复加载或执行模型。
4. 未完成与下一步
   - 人工视觉验收和第二位独立审查；本轮代码审查为本会话自查。
   - 全部模型验收使用假模型，未调用真实供应商；真实 AskUserQuestion 已覆盖，未把协议级 permission 自动批准当成真实工具审批验收。
   - 源码剩余 server 命中为只读 Web、peer Unix listener、OAuth、供应商或线程术语；CLI 的 `/api/headless/...` 仅为进程内分发，不是 HTTP 执行服务。
   - 旧 `src/klaude_code/skill/assets/` checkout 与 Git 元数据已移入废纸篓，本地子模块注册已撤销；不再存在内置 skill 指南或待发布子模块。
   - 用户已授权提交并发布 2.44.0；发布按仓库 publish 流程执行。后续仍需独立审查和人工检查历史列表、终端回放、焦点与弹窗。

## 待确认

- 是否支持独立进程自动升级；当前仅保留更新检查提示与显式 `klaude upgrade`。
