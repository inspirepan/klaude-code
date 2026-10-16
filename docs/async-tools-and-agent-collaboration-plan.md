# 异步工具与 Agent 协作：统一边界的调查与建议

> 状态：四个 Phase 已实现并完成自动化验收及分阶段独立 review，尚未提交或重启现有服务。skills 子模块旧指引待独立发布。下文早期调查保留为设计记录，不代表当前接口。
> 日期：2026-10-15。与 `docs/steering-plan.md` 一起阅读。
> 仅阅读本地源码、测试和用户提供的指南，未运行同行项目的测试或示例。

## 用户最新决策优先于下文早期建议

- Agent 默认异步，启动后返回引用；不再采用“默认前台等待、steering 时才让出”的早期建议。
- 首版不使用 fast model 做完成事件相关性判断。
  - 明确依赖的结果解除等待；预期停止只更新状态；同一已交付终态不重复回投。
  - 其他结果保留状态与输出，不通过模型猜测内容重要性；具体交付仍遵守安全边界。
- 重启恢复上下文、结果及待处理投递；活跃执行标 interrupted/lost，不盲目重放副作用。
- Peer 发送只负责入队，不强制等待回复，也不自动转发最后一条助手输出。
  - 用户确认按 Claude Code cross-session messaging 的显式消息方式设计。
- Esc 停当前推理或等待，后台 child 继续；停止单个子任务、停止全部子 agent 是独立操作。
- 新增 TUI `/stop`，终止当前会话的全部子 agent；不解释为全局所有会话或所有 Bash 任务。
- 用户确认做轻量共享任务管理层，统一查询、等待、停止和交付确认；底层执行器继续分开。
- Phase3A CLI 命名已确认并实现，以本节之后的接入点为准；文末旧建议保留为设计记录。
- 下文独立评估和旧建议保留为取舍记录；如与本节冲突，以本节为准。

## 最终验收与交付边界

- 最终同一验收链路通过：`make format-check && make lint && make test && make build`。
  - Python 非 network 测试：3361 passed，4 deselected；4 条依赖弃用警告。
  - Web 测试：194 passed；`pnpm typecheck` 通过。
  - Web bundle、wheel、sdist 构建及 bundled web/skill assets 校验通过；Vite 保留大 chunk 提示。
- 新增集成覆盖原生 MessagePeer 工具到真实 runtime/headless/模型输入来源，以及异步 Agent、steering 解除等待、root-only Esc 和 owned-child stop。
- 最终集成 review 发现的不可信任务报告附件展开与内部交付 ID 冲突已修复；第二轮独立复核没有新增 finding。
- 渲染 smoke 使用真实 renderer 与 Console capture；另用 PTY 验证新 CLI 帮助。没有运行真实模型、network 测试或完整人工 TUI 操作。
- 未安装或重载当前运行的 klaude 服务，未 commit/push；运行中旧进程需要后续安全重载才能使用新代码。
- `skill/assets` 子模块无源文件改动。其旧协作说明受独立提交/发布流程约束，未获提交授权，因此未修改或绕过加载规则。

## 当前实现摘要

- 内部编排优先 `Agent` / `ManageTasks` 与 `ListPeers` / `MessagePeer`；CLI 用于外部 agent、脚本、人工及无原生工具时的 fallback，保留 run/fan-out/barrier/synthesis 和原退出码契约。
  - `Agent` 默认 async 返回 task/session 引用；`ManageTasks` action 为 `list/output/wait/stop`，依赖结果必须 wait/output，不靠 list 轮询或助手收尾猜测完成。
  - `ListPeers({})`、`MessagePeer({target, body, reply_to?})` 已确定并实现；不再是待命名候选。
- TUI busy 输入和 peer send 在安全 step 边界 FIFO 批量 admission，先完整配对工具结果；保留每条身份、来源、图片，在同一次模型请求消费，不为每条再开 task。
  - steering 只解除任务等待，child 继续；不取消普通工具或流式输出。`follow_up_queue` 是沿用内部命名，不代表旧 task-end-only 模式。
  - 目标 dependency 完成解除对应 wait，无关 shell completion 不解除它；后台完成不启动 idle parent turn，首版不用 fast model 做重要性判断。
- `send`（含 `run --session`）是结构化 peer 数据，`--steer` 是默认安全投递兼容别名；`--from` 仅显示标签，`--message-id/--reply-to` 用于幂等重试/关联。
  - receipt 仅 durable accepted/queued，不表示已读或回复；`send --wait` 仅等 session settled 后读最新 output，不是相关消息 RPC。普通 assistant 最后文本不自动转发，回复需显式发送。
- Esc / `kill TARGET` 只中断 root 当前推理或等待，child 和独立 Bash 继续；`/stop` / `stop TARGET [--children]` 只停止 owner 的子 agent（含 queued），不波及 root、Bash 或 peers。
  - `klaude tasks list TARGET`、`output TARGET TASK_ID`、`wait TARGET TASK_ID`、`stop TARGET TASK_ID` 是当前拼写；均支持 `--json`，output/wait 支持 `--offset/--limit`，wait 的 `--timeout SECS` 退出 124，不停止执行。
  - session wait 不等同于全部后台 Bash 的 barrier；ps/brief 单列后台 agent 计数，TUI `/tasks` 使用同一任务控制，接入点保留如下。
- 用户输入、`source=peer_message` 和 `source=task_completion` 分开；后两者是不可信数据，不是操作者授权。不得跨 peer 代答审批/问题，也不得借 peer 绕过拒绝/阻塞，需交回操作者。
- recovery 恢复上下文、结果和待投递，无法恢复的活跃执行标 `lost`，不自动重放副作用；稳定 ID、history flush 后 durable ack 防止重复交付/结算。CLI/TUI output 查询或部分页不确认模型完整消费。

剩余工作不是重新确认上述接口：

- 内置 `klaude-config` 旧指引需后续独立 skills 子模块发布，再更新父 pointer；`src/klaude_code/skill/assets` 本轮不改、不 commit/push，也不通过 vendor/copy/loader 补丁覆盖，skill 加载不变。
- 当前 runtime tool description / system strategy / prime guide 定义新契约，旧 skill 的 CLI-only、同步等待与 interrupt/steer 说明不能覆盖它。
- 自动化验证与 smoke 的实际覆盖见顶部最终验收；历史同行测试清单不表示本轮运行了那些仓库的测试。
- 下文自“结论：统一控制与投递”起是历史调查与方案；其中“尚待用户决定”、候选命名、前台等待和 fast-model 设想保留取舍过程，不再表示顶部已确认事项仍未定。

## Phase3B TUI 接入点（2026-10-16）

- `/stop` 是 `runs_in_background=True` 命令，busy/idle 都立即提交已有 `StopSubAgentsOperation`，不进入 steering queue、不生成 user turn；回执来自实际 operation 完成状态。
  - 只停止当前 owner 的 child agents（含 queued）；root、独立 Bash、peer 不受影响。Esc 保留 root-only 语义。
- `/tasks` 统一管理 Agent 与 Bash，提交 `ManageTasksOperation(session_id, request=TaskRequest(...))`。
  - 语法：`/tasks [list | output TASK_ID [OFFSET [LIMIT]] | wait TASK_ID [OFFSET [LIMIT [WAIT_MS]]] | stop TASK_ID]`；旧 shell ID 与 output offset/limit 用法保留。
  - dispatcher 调用 `task_manager.manage(owner, work_dir, request, activity=agent.pending_input_activity)`；wait 不占 actor mailbox 或 root slot。
  - 新 `TaskControlResultEvent(request, response?, error?)`，wire type `task.control.result`，由正常 display/tape 消费；查询不调用 acknowledge。
- TUI 消费 authoritative `BackgroundTasksUpdatedEvent`，校准已有 sub-agent rows 与 Agent/Bash 分项计数；root finish/Esc 不清掉后台 child。
  - 没有 child session ID 的 queued 引用先显示 task-ID 行，拿到 session ID 后替换；已有 coloring/model/progress/status sink 继续复用。
  - typed 快照到达后旧 shell 快照不重复计算；socket 的后台计数不改变 root `is_running`。
  - ctrl-o、resize、refresh 仍只重放 display tape；attach/resume 沿用 Phase3A 全量快照，不增加第二套恢复路径。
- `source=peer_message` compact 是独立 dim 一行，expanded 展示原始 body 与 sender/recipient/id/reply_to；不解析包裹文本，不当用户输入卡片。
  - `MessagePeer` 调用有目标与正文首行摘要，receipt 明确仅表示传输入队；`ListPeers`、`ManageTasks` 结果用可读行和分页提示，不直接塞 JSON。
- `source=task_completion` 独立显示后台报告；长输出只提示 `/tasks output` 或 shell log 位置，不生成额外助手收尾。
  - 历史 replay 保留独立 `background_task_id` metadata，不产生父回合边界；typed 快照与历史费用按 task ID 去重。
- 未修改 Phase3A setter/store/peer delivery/WS snapshot 准备；Web viewer 沿用 unknown-event 忽略路径。

### Phase3B 修改文件范围

- 命令与控制协议：
  - `src/klaude_code/tui/command/stop_cmd.py`、`src/klaude_code/tui/command/tasks_cmd.py`、`src/klaude_code/tui/command/types.py`、`src/klaude_code/tui/command/__init__.py`。
  - `src/klaude_code/protocol/op.py`、`src/klaude_code/protocol/op_handler.py`、`src/klaude_code/protocol/events.py`。
  - `src/klaude_code/control/runtime/actor.py`、`src/klaude_code/agent/runtime/dispatcher.py`。
  - `src/klaude_code/app/runtime_facade.py`：停止失败仅发 lifecycle 失败回执，不把仍运行的 root 标成 fatal error。
  - `src/klaude_code/server/routes/ws.py`：异步提交 `/stop`，不阻塞 socket reader；未改快照准备。
- 状态、格式与重放：
  - `src/klaude_code/tui/machine.py`、`src/klaude_code/tui/commands.py`、`src/klaude_code/tui/renderer.py`。
  - `src/klaude_code/tui/components/background_tasks.py`、`src/klaude_code/tui/components/tools/_dispatch.py`、`src/klaude_code/tui/components/tools/_presentation.py`。
  - `src/klaude_code/tui/client/base.py`、`src/klaude_code/tui/client/socket_client.py`。
  - `src/klaude_code/session/session.py`：仅调整历史 replay 的后台费用与报告边界，不改 setter/store。
- 回归与说明：
  - 新增 `tests/tui/test_shared_tasks.py`、`tests/server/test_task_control_operation.py`。
  - 更新 `tests/tui/test_tasks_cmd.py`、`tests/tui/test_runner_attach.py`、`tests/tui/test_tui_machine_sub_agent_status.py`。
  - 更新 `tests/tui/test_tui_machine_handler_table.py`、`tests/tui/test_tui_machine_transition_characterization.py`、`tests/agent/test_sub_agent_registry.py`。
  - 更新本说明与 `src/klaude_code/tui/AGENTS.md`；保留其他 phase 的现有 worktree。

## Phase3A 原生 peer 消息与 CLI/API 接入点（2026-10-16）

- 公共 peer 协议：`protocol/peer.py` 的 `PeerInfo`、`PeerMessage`、`PeerReceipt`。
  - `PeerMessage` 保存 `id`、`sender_session_id`（外部发送为 null）、`sender_label`、`recipient`、`body`、可选 `reply_to`。
  - `UserInputPayload`、`UserMessage`、`UserMessageEvent` 都保存 `source="peer_message"` 与 `peer_message`，独立于 task completion。
  - 模型输入带来源与非操作者授权说明；附件收集忽略 peer 的 `@file` 和显式 `/skill:`；正文不经过 slash command dispatch。
  - 接收会话仍按自己的权限策略审批；peer 数据不是 respond，也不是批准。最后一条 assistant 从不自动转发；回复必须再次显式发送。
- 原生工具：`ListPeers({})`、`MessagePeer({target, body, reply_to?})`。
  - `ListPeers` 默认发现同一工作区、未归档且仍有 actor/排队工作的其他会话，提供稳定 ID、name、state、description、work_dir。
  - `MessagePeer` 可指定已存在的 ID、唯一前缀或名称；重名（包括归档同名）明确拒绝，不挑第一个。
  - 工具仅通过 `ToolContext.peer_control` 窄接口调用；可信发送者绑定 `context.session_id`，工具参数和 shell 环境不建立身份。
  - `RuntimeFacade.peer_control` 是 callback bridge；`server/peers.py:wire_peers` 在 server 初始化注入现有 index 与 `HeadlessRuntime` 调度，没有第二套 registry/scheduler。
  - main 和允许的子 agent 都注册这两个工具；没有增加子 agent 的嵌套 spawn 权限。
- 可靠投递：`HeadlessRuntime.deliver_peer(peer, work_dir)` 复用 Phase1 持久 follow-up queue、admission batch、历史 ID 去重和 flush 确认。
  - peer 的稳定 ID 同时作为 queued input/history ID；相同 ID 同内容重试幂等，不同来源或内容占用同 ID 明确拒绝。
  - 忙时安全 step 边界消费全部待处理消息；idle 走既有 drain/并发 slot 队列开启新 turn，不覆盖已有 slot 条目。
  - 每个接收方最多 50 条待消费 peer；每个可信 sender-recipient 在 10 秒内最多 10 条；同一对短窗重复正文拒收，不跨发送者按正文去重。
  - 短窗限流记录在进程内；历史/待处理 ID 去重与队列容量依靠持久数据，重启后仍生效。拒收不静默丢弃旧消息。
  - receipt 仅表示 durable accepted/queued，不表示模型已读、处理或回复；当前 peer receipt 的 `mode` 为 `queued`。
- REST 公共接口（沿用 `/api/headless`）：
  - `POST /sessions/{target}/send`：`{text, sender?, message_id?, reply_to?, steer?}`，保留旧 `session_id/mode/pending` 并增加 `message_id/target/accepted`。
  - 所有 send 都是 peer 数据；旧 `sender_session_id` 字段仅接受兼容输入但不信任、不升级为原生身份；`sender` 仅是显示标签。
  - `POST /sessions/{target}/tasks`：typed `TaskRequest` → `TaskResponse`，action 为 `list/output/wait/stop`；task ID 必须属于 target owner，读取不调用 acknowledge。
  - `POST /sessions/{target}/stop`：提交并等待 `StopSubAgentsOperation`；回执 `{session_id, scope:"sub_agents", status}`。只停止 owned 子 agent，不停止 root、独立 Bash 或 peer。
  - 现有 `/interrupt` 仍是 Esc-equivalent root 中断；`/respond` 仍是单独的操作者交互入口。
  - `ps`/`brief` JSON 增加 `background_agent_count/background_state`，文本 activity/brief 也显示后台 child 数量；不把独立 dev server 改成会话永不 settled 的 barrier。
- CLI 公共接口：
  - `klaude send TARGET TEXT [--from LABEL] [--message-id ID] [--reply-to ID] [--steer] [--json]`；`run --session TARGET` 复用同一投递。
  - `send --wait [--timeout SECS]` 为脚本保留：等会话 settled 后读取 output，不是当前 message 的相关回复；`output` 仍只是转录查询。
  - `klaude tasks list TARGET`、`output TARGET TASK_ID`、`wait TARGET TASK_ID`、`stop TARGET TASK_ID`，均支持 `--json`。
  - task output/wait 支持 `--offset/--limit`；task wait 支持 `--timeout SECS`，超时退出 124，不停止执行。HTTP timeout 比每次 long poll 多留 15 秒。
  - `klaude stop TARGET [--children]` 仅停止 child agents；`kill TARGET` 仅中断 root；`kill --all` 显式选择所有活跃 sessions（含 child session），不是隐式级联。
  - run 默认后台与既有 ps/brief/output/attach/respond、会话 wait 类别保持不变。
- Phase3B 展示接点：
  - live、Session 历史 replay、event tape 都保留 `UserMessageEvent.peer_message`；compact/expanded 可直接读取发送者、接收者与原始 body，不解析包裹文本。
  - 发出的原生消息参数保存在常规 tool call 历史中，结果只有 receipt，不含对方 assistant 文本。
  - WS attach/resume 都发送 authoritative `BackgroundTasksUpdatedEvent` typed 全量快照（包含 descendant owner），并抑制快照之前的过时 live 更新；重连不依赖碰巧收到完成事件。
  - Phase3A 当时未实现的 TUI 展示已由 Phase3B 接入，见上一节；没有修改 bundled skills 子模块。外层技能协作指引与独立 review 留给主会话。

## Phase2 后端接入点（2026-10-16）

- 公共协议：`protocol/background_task.py` 中的 `TaskReference`、`TaskRequest`、`TaskResponse`、`BackgroundTaskSnapshot`、`BackgroundTaskResult`。
  - 引用绑定 kind、owner session、稳定 task/run ID，以及可选 child session/operation ID；查询与控制始终限制当前 owner。
  - snapshot 保留结果 metadata、文件变更和 shell 原始快照；报告正文只从 output/wait 分页返回，不在 list/event 中重复放全文。
- runtime API：`RuntimeFacade.task_manager.manage(session_id, work_dir, TaskRequest(...), activity=...)`。
  - action 为 list/output/wait/stop；wait_ms 仅限制等待，不限制执行；activity 使用 `Agent.pending_input_activity`，解除等待但不取消底层任务。
  - `await acknowledge(session_id, delivery_id)` 只能在完整交付已持久化后调用；读取状态或部分输出不能视为完整交付。
  - shell 日志被 prune 或丢失时，output/wait 显式返回 `output_unavailable`，保留真实终态和可查询记录；不生成完整结果 receipt，也不永久保留为 pending。
  - 模型通过 `ToolContext.task_control` 访问 `ManageTasks`；`ManageShell` 与 shell 原日志/状态接口保留。
- 停止全部子 agent：提交 `StopSubAgentsOperation(session_id=owner)`；也可调用 `task_manager.stop_sub_agents(owner, work_dir)` 停止已注册的任务。
  - operation 还处理 owned child actor 中的后续活跃/排队运行、待批准交互与排队输入；不停止其他 peer 或独立 Bash。
  - `InterruptOperation` 只中断目标当前 root 推理/等待；不再级联 child，不停止后台 shell。
- 完成事件：`BackgroundTasksUpdatedEvent(session_id=owner, tasks=typed_snapshots)`，wire type 为 `background.tasks.updated`，已接入 parser。
  - 任务结束只更新状态；headless 不再把 shell 完成排成空闲 turn，已移除旧式 shell generation/disabled/pending 专属通道。
  - 忙碌父 agent 在安全边界消费未交付报告；idle 保留结果，不仅为复述完成而开新 turn；明确 wait 直接收到结果。
  - 完成输入以 `task-result:<stable ID>` 幂等入历史，flush 后确认；来源为 `task_completion`，正文标记 source/untrusted，不代表用户授权。
  - 过长报告保留为可分页读取结果，不把部分正文确认成完整交付；工具输出被通用 offload 截断时也不确认。
- 持久化：owner session 目录下的 `background_tasks/<task_id>.json` 保存任务引用、结果与 receipt；shell 原目录与日志不变。
  - runtime 持有 collector 到真实 child `OperationFinishedEvent`；父工具返回或 Esc 不取消 collector。
  - collector 对 owner actor 持生命周期 pin，阻止 non-force close/reclaim，但不占 root slot；force close 先停父 root，再等待 child/collector 收尾后释放 owner。
  - 结果先持久化，再用带稳定 `background_task_id` 的独立 `TaskMetadataItem` 记费用；meta 的 `background_task_ids` 与文件差量一起写入，独立确认合并是否完成。串行 writer 只补缺失 marker，history/meta 部分失败可重试，磁盘确认前不视为结算完成。
  - 任务快照按 record 串行 `to_thread` 原子写入；取消必须等当前写入确认，未变快照不重复 fsync。clear/fork 创建的新 Agent 同样注入共享 TaskManager。
  - 重启后原 agent 活跃执行标 lost；不自动重跑副作用。恢复只补记录、未结算统计和待交付结果。
- 此 phase 不提供 peer ListPeers/MessagePeer、CLI 新命令或 TUI `/stop` 面板；Phase3 复用上述 operation、runtime API 和 typed event。

## 结论：统一控制与投递，不统一底层执行器

- Bash 后台进程和 Agent 子 session 可以共用任务引用、状态查询、等待、停止、结果投递和 UI 事件。
- Bash 的进程组、输出 drain 与 Agent 的模型循环、历史、fork-context 应继续由各自执行器管理。
- task completion、peer message 和用户输入可以走共同的输入 admission 与安全边界，但保留来源及唤醒语义。
- 必须拆开三件事：任务结束、结果交付、启动新一轮模型推理。
- steering 只解除主 agent 的等待，不停止 child；真正停止仍使用独立的 interrupt/stop 操作。
- 不建议为这些需求引入通用 workflow engine、任意 DAG 或所有工具的 checkpoint 执行系统。

## 用户的三个目标与当前问题

1. 运行中消息默认 steering，在安全边界一次处理全部待处理消息。
2. 后台 Bash 完成不应总是唤醒主 agent，只复述无意义的收尾结果。
   - 具体案例是主动停止 mock 服务后，主 agent 又运行一轮解释 exit -15。
   - 用户提出 fast model 判定是否需要唤醒。
3. 调查原生 peer 工具与 Agent 异步化，让协作协议和 TUI 展示不再依赖 Bash 命令字符串。
   - 最初是调研目标；用户后续已确认显式消息方式、默认异步和共享任务管理层。
   - “派人”暂按 Pi 理解；“Cloud Run”按语音输入中的 `klaude run` 理解。

## Anthropic 指南支持专用工具，但没有规定异步框架

来源：https://github.com/anthropics/skills/blob/main/skills/claude-api/shared/agent-design.md

- `Designing Your Tool Surface` 明确区分 Bash 的不透明命令字符串与专用工具的 typed arguments。
- 当需要权限边界、专属渲染、审计或调度时，应将相关动作提升为专用工具。
  - klaude 的 peer 协作同时需要路由、展示与调度，符合这一判断依据。
  - 不建议靠解析 `Bash("klaude send ...")` 来重建可靠的协作协议。
- 模型发出工具调用，harness 负责执行、权限与 UX；生命周期和停止规则不能只写在提示中。
- 指南建议保持主 agent 模型稳定，用便宜的独立调用或 subagent 处理轻量工作以保护缓存。
  - 对 shell 完成通知的 fast-model 判定，可独立调用，而不是切换主 agent 的模型。
- PTC 用于在程序中组合工具调用、减少中间数据进入上下文，不等于可恢复的后台任务框架。
- 指南没有给出 steering、task registry、mailbox 或结果确认协议；这些仍需本项目自行定义。
- 不直接套用指南里模型专属的 system-message、tool-search、缓存 API 到所有 provider。
  - 外部工具输出和 peer 消息始终是有来源的数据，不能因此被提升为 system 权限。

## 同行对照：有共同原语，但没有统一执行所有工作的单一模式

以下源码路径相对于 `/Users/panjx/code/coding-agent/`，行号可能随 checkout 改变。

### Kimi：共享任务服务，分离具体执行

- `AgentTaskService` 管理 process、agent、question 等任务的状态、输出、等待与终态通知。
- 任务以 `start(sink)`、`toInfo(base)` 等接口接入，具体工具仍自行提供执行实现。
- `WaitFor` 同时接收运行取消信号与 steer 信号；steer 只结束等待，后台任务继续。
- WaitFor 交付过的结果有通知抑制标记，通知还有 task/status/notification ID 去重。
- 重启后无法确认仍执行的任务标为 `lost`，不假装恢复原进程或原 agent 执行栈。
- Tower peer inbox 是独立的协作协议，不等于子 agent 最终助手答案。
- 证据：
  - `MoonshotAI-kimi-code/packages/agent-core-v2/src/agent/task/types.ts:23`、`:48`。
  - `MoonshotAI-kimi-code/packages/agent-core-v2/src/agent/task/taskService.ts:351`、`:548`。
  - `MoonshotAI-kimi-code/packages/agent-core-v2/src/agent/task/taskService.ts:627`、`:1129`、`:1269`。
  - `MoonshotAI-kimi-code/packages/agent-core-v2/src/agent/tools/task/task-wait/taskWaitTool.ts:187`。
  - `MoonshotAI-kimi-code/packages/agent-core-v2/src/features/tower/towerService.ts:712`。
- 测试：`packages/agent-core-v2/test/agent/task/reconcile.test.ts:104`、`:160`、`:245`。
  - `WaitFor` 有实验 flag，不能将其描述为所有 Kimi 配置默认启用的功能。

### OpenCode：共享 Job 与持久完成标记，按类型恢复

- `Job.Service` 统一 start/get/wait/background/cancel，shell 和 subagent 使用不同执行实现。
- 后台标记包含稳定 notification ID 和按 shell/subagent 区分的 recovery 信息。
- subagent 完成后提取助手文本作为任务报告，再向父 Session 投递 synthetic 消息。
- 结果进入 inbox 和唤醒执行可分离，`resume: false` 表示记录而不立即恢复推理。
- 完成通知 admission 后再确认后台标记；测试覆盖 admission 后、ack 前崩溃的重复投递。
- 证据：
  - `anomalyco-opencode/packages/core/src/job.ts:9`、`:127`、`:171`。
  - `anomalyco-opencode/packages/core/src/session/subagent-completion.ts:21`。
  - `anomalyco-opencode/packages/core/src/session/execution/restart.ts:101`。
- 测试：`anomalyco-opencode/packages/core/test/tool-subagent.test.ts:211`。
- 这是 Session 输入 inbox，不应误称为完整的通用 peer-message 协议。

### Codex V2：执行注册表分开，消息与唤醒在上层汇合

- exec 使用 `UnifiedExecProcessManager/ProcessStore`，agent 使用独立的 `AgentRegistry`。
- V2 的 `spawn_agent/list_agents/send_message/wait_agent` 提供原生协作入口。
- 所查版本的 `send_message` 使用 QueueOnly；`followup_task` 才请求 TriggerTurn。
- child 完成通知明确携带 `trigger_turn=false`，不会仅因完成就自动启动空闲父 agent。
- `wait_agent` 可被 mailbox 或 steering 唤醒；输入随后进入主 turn，child 不因此停止。
- 每个 agent 的 thread/usage 与共享预算分开；不能把父子关系等同于自动重复汇总费用。
- 证据：
  - `openai-codex/codex-rs/core/src/unified_exec/mod.rs:149`。
  - `openai-codex/codex-rs/core/src/agent/registry.rs:20`。
  - `openai-codex/codex-rs/core/src/tools/handlers/multi_agents_v2/send_message.rs:33`。
  - `openai-codex/codex-rs/core/src/agent/control/completion.rs:92`。
  - `openai-codex/codex-rs/core/src/tools/handlers/multi_agents_v2/wait.rs:67`、`:202`。
- 测试：`openai-codex/codex-rs/core/src/session/tests.rs:12685`、`:12776`。
- 这些是 V2 路径，受版本及 feature 配置影响；不能与 V1 的消息语义混用。
- rollout 历史可持久化，但 registry、活跃 wait 和进程句柄不因此自动跨重启恢复。

### Pi：core、durable 与扩展示例必须分开评价

- core agent 有 steering/follow-up 队列及 all 模式，没有查到内建的 ListPeers/MessagePeer 工具。
- durable 包提供 checkpoint 任务、独立 wait cancellation、ownership、requestId 去重和恢复调度。
- durable 的 Bash 工具仍等待 `env.exec()` 完成，并非一套可查询的后台进程管理 API。
- 后台子 agent 是 durable 扩展示例的产品逻辑，不是 core 自带的 peer 服务。
- 示例 reporter 会把子 agent 的最终助手答案重新提交到主 conversation。
  - 文本里的 `no reply needed` 不能阻止一次模型执行，不适合照搬来解决无意义唤醒。
- 恢复 checkpoint 不保证外部副作用 exactly-once；不安全工具仍需以 interrupted 收尾。
- 证据：
  - `badlogic-pi-mono/packages/durable/src/harness/scheduler.ts:288`、`:339`。
  - `badlogic-pi-mono/packages/durable/src/harness/submissions.ts:161`。
  - `badlogic-pi-mono/packages/durable/src/harness/tool.ts:107`。
  - `badlogic-pi-mono/packages/durable/src/tools/bash.ts:82`。
  - `badlogic-pi-mono/packages/durable/test/examples/23-subagent-background.ts:73`、`:108`、`:132`。
- 测试：`badlogic-pi-mono/packages/durable/test/harness-submissions.test.ts:82`、`:115`。
- 可借鉴稳定 ID、等待与任务取消分离；不建议复制完整持久 workflow 系统。

### Hermes 补充：投递确认不是严格 exactly-once

- 异步委派与后台进程有完成队列和客户端各自的通知路径；未确认使用 fast-model relevance gate。
- gateway 有持久 claim/ack 与拒收返还，但实现注释明确存在崩溃后重放的 at-least-once 窗口。
- 显式 steer/stop/list 是子代理控制面，不足以证明任意 peer 双向互发协议。
- 证据：`hermes-agent/gateway/run_notifications.py:1115`、`:1351`、`:1448`。

## klaude 可复用的基础与实际缺口

- Bash 已有进程管理、日志、任务快照、终态事件和重启后 `lost` 处理。
  - `src/klaude_code/tool/shell/task_manager.py:117`、`:179`。
- Agent 已是持久 child session 与独立 actor，并非真正的临时 subprocess。
  - `src/klaude_code/agent/runtime/sub_agent.py:52`、`:121`。
- Agent 工具的同步等待目前同时负责收集结果、metadata、进度及文件变更。
  - `src/klaude_code/agent/runtime/sub_agent.py:132`、`:189`。
  - `src/klaude_code/agent/runtime/agent_ops.py:1467`。
- `agent_tool.md:15` 的 one-shot/discarded/不能续聊，是模型可见约定，不准确反映底层 session 能力。
  - 更正它不能代替新增任务句柄、恢复入口和原生消息接口的实现。
- Bash 完成队列在内存，headless 空闲后直接启动主模型 turn，没有意义判定或独立 inbox ack。
  - `src/klaude_code/server/headless.py:196`、`:241`。
- 现有 `run` 默认只返回 ID；`output` 与等待命令从助手历史取文本，不是相关消息的显式回复。
  - `src/klaude_code/server/routes/headless.py:247`。
  - `src/klaude_code/cli/headless_cmd.py:956`。
- sender 标签只有文本归因，没有结构化 peer message ID、reply-to 和专属 UI 事件。
- `session_id`、operation ID、actor 内 task ID、shell task ID、tool call ID 是不同身份，不应混为一类。

## 建议的最小统一边界

```text
模型工具 / CLI / TUI
  Agent、Bash                  -> 各自执行器 -> 工作状态与结果引用
  任务查询、读取、等待、停止   -> 薄控制接口 -> 按类型路由
  peer 消息 / completion      -> 持久输入队列 -> 唤醒策略 -> step 边界批量消费
                                             -> UI 事件（不必调用模型）
```

- 任务引用统一最小公共字段：类型、稳定 ID、owner、状态、结果引用和支持的动作。
  - Agent 另有可续聊的 session ID；一次 task/run 完成不等于整个 session 被销毁。
  - 不为 shell 添加 send-message，也不把 agent 当成有 OS PID 的进程。
- 投递条目保留稳定 ID、来源、接收会话、任务/运行关联和是否允许唤醒。
  - reply-to 对问题回复有用，但不强迫每条通知都成为 RPC 请求或都必须收到回复。
- 记录、交付与唤醒分开；入队成功不等于模型已消费，UI 已显示也不等于结果已处理。
- 工具层只通过 ToolContext 的窄接口访问控制能力，不能 import agent/app/server。
  - 协议模型位于 protocol，具体调度通过现有 runtime/app wiring 接入；不提前建立大而全管理器。
- 不另造一套与 session registry 冲突的 agent 真值来源；公共任务视图应引用现有运行记录。

## Agent 异步化：默认异步，等待是独立操作

- 用户已选择默认异步：底层 runtime 持有任务，Agent 工具启动后返回稳定引用，不同步等最终报告。
- 读取、等待和停止是独立能力；等待被 steering 解除时，child 继续运行。
- 不再以保留小任务一次调用拿结果为默认方案的主要目标；如需前台优化，后续另行评估。
- 默认异步必须配套可靠的读取/等待/停止、完成投递和未完成任务展示。
  - 不能依赖模型反复 list 轮询，也不能让主 agent 在依赖结果未到时误报完成。
- Agent 工具描述需与能力同时更新：独立 session、任务与 session 的区别、续聊、后台结果投递。
- 保持每个 tool call 只有一个结果。
  - 同步完成就返回最终任务报告；提前返回则给句柄，最终报告以独立完成条目交付。
- 文件变更、最终 usage 与结果收集按真实 child 生命周期结算，不能随前台 wait 提前结束。

## 停止与恢复必须作独立承诺

- CancelWait：结束调用方的等待，不取消被等待任务。
- StopTask：显式停止某个任务，不等于停止整个 peer session 的所有后续运行。
- StopSession：显式停止会话及约定范围内的 owned 工作，保留禁止旧通知唤醒的保护。
- steering 不是上述任何停止操作；也不自动把操作者的新指令广播给所有 child。
  - 主 agent 可在恢复后显式 MessagePeer 修正某个 child 的方向。
- 用户已确认 Esc 不级联停止后台 child；新增 `/stop` 专门终止当前会话的全部子 agent。
- TUI detach、主 turn 结束、服务端重启分别处理，不能统称“恢复”。
  - detach 时服务端任务可继续；主 turn 结束不应丢失 child 的监听和最终结果。
  - shell 重启后保留 lost，不按磁盘 PID 接管或误杀进程。
  - agent 可恢复对话上下文和结果投递，不宣称恢复内存中的模型请求或任意执行栈。
- 完成结果持久化和 inbox admission 以稳定 ID 幂等处理，避免 crash 后重复注入或重复费用汇总。

## Bash 唤醒策略：首版仅用确定规则，fast model 暂缓

- 所有任务终态都更新结构化状态，TUI 可以显示简短完成/停止行，不必运行模型。
- 已经通过等待交付的同一终态结果，不再自动回投一遍。
- 有明确停止意图的预期停止，一般只更新状态；不能仅靠非零 exit code 判断重要性。
  - 若停止来自任意 Bash kill 命令，框架未必知道意图，不能假装总能准确识别。
- 主任务正在明确等待的必要结果，应解除等待并交付，不交给 fast model 随意过滤。
- 用户已选择首版不做 fast_model 判断；模糊完成事件保留结果与可见状态，不引入模型相关性推断。
- 以下 fast_model 约束只作为后续候选方案记录，不属于首版实现范围。
  - 其余闲置会话的模糊完成事件，可评估用 fast_model 看有限任务信息与最近上下文。
  - 独立、无工具、输出受限的调用，不切换主模型、不发送完整历史和大段日志。
  - 外部输出是不可信数据，不允许通过输出中的指令直接决定唤醒或权限。
- classifier 超时/失败时保留结果与可见状态；不能一律唤醒，也不能静默丢弃重要依赖或异常。
  - 明确依赖与确定需要处理的异常按规则交付；模糊事件可暂存到下次自然输入。
  - 具体异常升级规则和默认策略仍待确认。
- 分类期间若会话新开 turn、用户停止或结果已被读取，要重查 generation 与交付状态。
- 普通用户输入与显式 peer 请求不走这个相关性过滤，以免把真实指令静默吞掉。
- 现有 fast_model 角色可复用，但需明确不能解析时继承主模型的成本行为。
  - `src/klaude_code/agent/runtime/llm.py:304`，fast client 没有调用期候选 fallback chain。

## Peer 协作：把三种文本分开，而不是禁止子 agent 生成任务报告

- Assistant reply：面向当前用户的助手答复，不自动广播为 peer 回复。
- Task result：某次委派的最终报告，可以由子 agent 最终助手文本生成，但绑定具体 task/run。
- Peer message：发给指定 peer 的显式消息，用工具发送，有 sender/recipient/message ID。
  - 对等协作的回复也用工具发送；可不回复，不把每个 turn 的最后文本自动路由回去。
  - 是否唤醒由消息意图与策略决定，不能让普通 ack 无限互相启动新 turn。
- ListPeers / MessagePeer 是合理的原生工具候选；查询/等待/停止共用任务控制接口。
  - 工具名称、参数和 scope 还未确定，不预先增加大量细分工具。
  - 列表默认限定当前工作区或明确协作范围，避免把全部历史会话倾倒进模型上下文。
  - sender 身份由 runtime 提供，显示名与客户端标签不能当作授权凭据。
- CLI 继续服务外部脚本及人工使用，原生工具和 CLI 调用同一底层能力。
  - 不必删除 `klaude run`，也不把它当作模型内部唯一协作入口。
- TUI 使用独立 peer 消息卡片与任务状态，不与操作者普通 user message 混排成同一种语义。
  - 精简模式显示发送者、接收者、摘要与状态；展开模式查看正文及任务日志。
  - 从结构化事件重放，不解析 Bash 命令字符串，也不另造一套丢失历史的显示旁路。

## 分阶段实施与验证建议

1. 统一术语及身份关联，定义结果持久化、交付确认与是否唤醒的最小契约。
2. 实现默认批量 steering，独立 CancelWait 与停止路径。
3. Agent 默认后台启动并返回引用，配套独立读取/等待/停止、child 完成收集、去重和恢复。
4. Bash 完成沿同一投递规则处理，消除可确定的重复与预期停止唤醒；首版不加 fast-model 判定。
5. 添加原生 peer 工具及专属 TUI 展示，并修正文案与协作指引。

高杠杆验证场景：

- 主 agent 等多个 child 时收到多条 steering：父恢复、child 不停、工具结果完整配对。
- child 在前台返回与转后台的竞态中完成：句柄和最终结果不丢、不重复交付。
- 完成结果已通过等待读取，迟到的回调不再启动新 turn。
- 主任务已结束后主动停止服务，只更新状态，不产生无意义助手收尾和新费用区块。
- 后台测试失败或明确依赖完成，必要结果仍能到达，不被“降噪”误吞。
- 用户停止/发新消息/读取结果后，旧代次通知不能再唤醒旧任务。
- 完成入队后、ack 前服务端崩溃，恢复后只消费一次；运行恢复边界如实标记。
- 多个 peer 同时提问与回复，reply-to/来源不串线，普通助手文本不被错当 peer 回复。
- compact/expanded、重连、刷新回放都保留协作身份，费用和文件变更不重复汇总。

## 尚待用户决定

- 明确依赖通过哪些等待/订阅入口登记，以及 `klaude wait` 的完成范围。
- peer scope、具体工具面、UI 细节，以及 CLI 的任务控制入口拼写。
- 显式 follow-up 与旧 `--steer` 的兼容方式。
- `/stop` 已确认只针对子 agent；服务端退出及其他彻底关闭操作下的资源清理需要单独设计。

## 架构复核：fable 与 astra 的独立意见

> 2026-10-15：按用户要求安排四个只读评估，两个使用 `fable`，两个使用 `gpt-6-astra`。
> 分别关注生命周期与取消、消息与唤醒、抽象与迁移、用户流程与故障轨迹。
> 以下为主会话核对源码后的综合意见，不把模型共识当作正确性证明。未运行测试。

### 收敛的方向

- 不需要先建立统一执行引擎，保留 ShellTaskManager 与独立 Agent session/actor。
- 不必先默认全异步；前台等待可让出，加显式后台，已经能解决主要阻塞。
- 子 agent 收集器必须与父工具的等待分离，结果和统计不能随等待退出而消失。
- 完成、交付、唤醒和 UI 更新是不同状态，不宜用单个 notified 布尔表达。
- fast model 不负责投递正确性；确定的依赖、停止意图和交付记录应优先于相关性判断。

### 决策一：steering 的边界与响应延迟

- 选项 A：完整工具批次配对后注入；Agent 等待可提前让出，但其他普通工具可能阻塞。
- 选项 B：要求有明确响应时限，因此普通长工具也必须支持后台化或协作式让出。
- 推荐第一阶段 A，明确不保证任意工具期间即时响应；B 是额外的工具执行改造，不是改消息队列即可获得。
- 同批多个 Agent 等待必须都能观察到 steering；不能让第一个 waiter 清掉信号后，后续 waiter 又阻塞。
- 权限等待建议维持阻塞并显示原因，用户可显式撤销后重规划；普通 steering 不充当批准。
- 证据：`src/klaude_code/tool/core/runner.py:166` 先执行顺序工具，再启动并发工具。

### 决策二：Agent 默认异步，以及什么叫任务完成

- 选项 A：默认前台等待，支持显式后台和 steering 时让出；短任务无需额外查询。
- 选项 B：默认立即返回句柄；可组合性更强，但每次都需要等待/读取和可靠任务展示。
- 推荐先 A，保留未来切换 B 的能力；不把底层独立执行与工具必须立即返回混为一谈。
- 必须区分必要依赖与非必要后台工作，否则要么过早宣称完成，要么被常驻服务永远阻止完成。
- 需定义 `klaude wait` 等的是当前推理结束、必要工作完成，还是所有后台任务都结束。
  - 不建议因新增后台 Agent 就静默改变现有 CLI barrier 的公开含义。
- UI 至少区分“已完成”“正在等子任务”“已停止但仍有后台工作”，不只依赖 spinner 开关。
- 证据：`src/klaude_code/server/session_state.py:21` 把 child_task_count 计入 running；
  `src/klaude_code/agent/runtime/agent_ops.py:1467` 的计数生命周期目前绑定 launcher await。
- 费用按真实 child run 归属，父会话可聚合展示，但不能把迟到费用算成无关下一轮的新开销。

### 决策三：用户停止的范围

- 选项 A：保持现有 interrupt 对活跃 child 的级联；后台只是等待方式，不代表独立生存权限。
- 选项 B：显式后台 child 可跨父 interrupt 存活；需要独立 ownership/停止范围与清晰 UI。
- 推荐初期 A，用户若确实需要 B，再显式支持；不能因异步化而偷偷改 Esc 的含义。
- 两种选项都必须保留 steering 只解除等待、StopTask/StopSession 才停止工作的区别。
- 已停止旧 run 的结果可保留，但不能在新用户输入恢复会话后，又当作新 run 的通知自动唤醒。
- 证据：`src/klaude_code/app/runtime_facade.py:375` 在完成回调时读取当前 generation，
  而 `:397` 递增代次、`:401` 恢复通知；仅靠这一机制不等于按原 run 隔离迟到完成。

### 决策四：什么时候允许自动唤醒

- 选项 A：全部完成都唤醒，简单但重现当前噪声；选项 B：全部只记录，安静但可能卡住必要工作。
- 推荐按因果关系分类：必要依赖解除等待；明确预期停止只更新状态；模糊后台完成再决定是否需要判断。
- 等待已交付同一最终结果时抑制重复投递；只查询状态、分页读取部分日志不能一概算完整交付。
- fast model 是否首版加入仍待决定；推荐先验证确定规则能消除多少噪声，再评估新增模型调用成本。
- 若首版就加，必须先定超时/误判降级：保留未读结果与可见状态，不能静默丢弃失败或一律唤醒。
- 暂不把“失败一定重要、成功一定无用”当默认；后台测试失败与预期非零退出需要不同上下文。

### 决策五：恢复承诺与消息确认

- 用户消息不能比现有持久化队列更容易丢失；复用存储机制不等于复用逐 turn 的消费语义。
- 推荐稳定投递 ID、至少一次投递、历史入队后的去重确认；不承诺跨任意副作用 exactly-once。
- “已接收”“已进入历史”“模型已经处理”分别定义，模型处理可重试而工具副作用不应盲目重放。
- 选项 A：重启恢复结果和上下文，活跃工作标 interrupted/lost；选项 B：自动继续工作。
- 推荐 A 为基础，B 必须按具体工具的重放安全性单独启用，不能从“session 存盘”推导出来。
- 证据：`src/klaude_code/agent/agent.py:104` 会先清空并持久化队列，
  `src/klaude_code/session/session.py:339` 同步更新 meta；直接 pop-all 再异步写历史存在丢失窗口。
- 这是确认与恢复契约，不要求引入通用工作流或新的全局 TaskManager。

### 决策六：peer 是显式通信，还是远程请求应答

- 选项 A：MessagePeer 只确认入队，回复是独立消息，允许不回复；选项 B：远程 RPC 风格强制等待回答。
- 推荐 A 为基础，需要问答时用 message ID/reply-to 关联可选等待，不把每条消息都变成 RPC。
- 忙时按用户要求默认 steering；空闲时需区分新请求、匹配中的回复和普通 ack，避免互相无限唤醒。
- TaskResult 可继续来自某次 child run 的最终助手文本，但不等于任意 peer 的助手输出都自动回传。
- 发现范围、投递权限和操作授权是三件事；工作区过滤与显示名不构成授权机制。
- 先明确同一用户下本地 agents 是否属于同一信任域；若要防恶意 peer，拥有 Bash 的同用户进程需要更强隔离。
- 用户确认第三项进入实现后，再定工具面及 UI 卡片，不为未来协议预建复杂基础设施。

### 没有采纳的具体推断

- “只要 wait/stop 返回前设置 notified，就能修好案例”不足以成立。
  - 终态由 monitor 发回调；等待返回时通知可能已进入 headless 队列，改 manager 标记无法撤回上层项。
  - `wait` 只返回任务状态，不返回日志；其执行不等于完整结果已经交付。
  - 用户案例没有证明 stop 经过 ManageShell，因此不能把这一条路径当作唯一根因。
  - 证据：`src/klaude_code/tool/shell/task_manager.py:423`、`:433`、`:518`、`:526`，
    `src/klaude_code/tool/shell/manage_shell_tool.py:97`，`src/klaude_code/server/headless.py:202`。
- “现有 pop_all_follow_up 足以直接做可靠 steering”忽略了先删除后写历史的崩溃窗口。
- “Agent 可以复用 Bash 现成 interrupt-result 钩子转后台”描述不准确。
  - 当前 Bash 钩子生成 aborted 输出；未 detach 的调用取消后会停止进程，不是仅取消等待。
  - 证据：`src/klaude_code/tool/shell/bash_tool.py:138`、`:171`、`:214`。
- “完整 child session 存盘就足以处理异步恢复”忽略了结果是否已消费、迟到 metadata 和副作用重放。
- 不采纳把 late child 费用直接塞进下一轮新任务的简单方案；保留原 run 归属再做聚合展示。
- 有评估认为统一任务视图也属过度设计，另有评估支持薄共享控制面；目前只收敛到共享投递契约。
  - 是否需要统一查询视图，应由实际重复和工具需求决定，不作为 steering 的前置工程。

### 可以由工程实现自行确定的底线

- 每个 tool call 一个结果、来源可追踪、状态可重放、消息去重和停止后禁止旧通知自动复活。
- runtime 负责收发身份，工具结果和 peer 正文不提升权限，steering 不绕过审批。
- 不改变分层约束、不镜像第二套 agent 真值、不复制通用 workflow engine。
- 保留现有持久队列的可靠性；模型 schema 采用各 provider 支持的简单结构，并验证消息配对。
- 先落地可单独验收的小步骤，再决定默认全异步、fast-model 门控和原生 peer 工具。

## 后续对照：后台停止、跨会话消息与 TaskManager

### 停止父 turn 与停止后台工作，在同行中通常分离

- Kimi 前台 child 绑定父工具 signal，后台 child 注册为 detached，不传父 signal。
  - `MoonshotAI-kimi-code/packages/agent-core-v2/src/agent/tools/agent/agentTool.ts:474`、`:500`、`:547`。
  - session 退出另走 stopAllOnExit，是否 keep-alive 决定退出时的处理；不是任意关闭都保证继续。
- OpenCode 后台 subagent 直接返回；前台 block 被中断时才显式 interrupt child 和 cancel job。
  - `anomalyco-opencode/packages/core/src/tool/plugin/subagent.ts:229`、`:234`。
  - 后台 job 有独立 scope；shutdown/restart 另处理恢复，不等于原运行栈跨进程存活。
- Pi durable 示例用 background ownership 边界，使主 agent 的 Esc/idle wait 不进入后台工作。
  - `abort({ background: true })` 才跨越边界停止所有工作；这是示例/框架组合，不是 Pi core 通用默认。
  - `badlogic-pi-mono/packages/durable/test/examples/23-subagent-background.ts:56`、`:73`。
- Claude Code 官方文档区分中断当前操作与停止所有后台子 agent 的独立操作。
  - https://code.claude.com/docs/en/interactive-mode#general-controls
  - 当前文档列出 Esc 中断当前响应/工具调用，ctrl-x ctrl-k 专门停止所有后台 subagent。
  - https://code.claude.com/docs/en/sub-agents#run-subagents-in-foreground-or-background
  - 其当前默认模式也支持后台启动，再通过完成通知报告结果；具体行为受 fork mode/运行环境影响。
- Codex V2 有独立 interrupt-agent/shutdown-tree 操作，但本轮未直接验证所有父 Esc 路径，不能硬说其保证 child 存活。
- 鉴于用户已选择默认异步，新的推荐是：普通 Esc 停当前推理/等待，后台任务继续；StopTask/StopAll 单独明确执行。
  - 这是参考后的建议，不是用户已确认的新语义；退出与彻底停止仍需分别定义。
  - 后台继续的工作必须可见、可寻址、可停止，迟到完成也不能违反用户已设置的停止保护。

### Claude Code 跨会话消息：发送入队不等于收件方永不启动

来源：https://code.claude.com/docs/en/cross-session-messaging

- ListAgents 发现会话，SendMessage 显式发消息；消息只含文本，不自动传对话历史和文件。
- 收件方忙时，在工具调用之间读取，不中断正在运行的工具；空闲时以消息启动一个新 turn。
  - 因此“发送只负责入队”是发送方不等回复，不是把收件方永久保持静默。
  - klaude 建议采用相同接收行为；批量消费规则仍按用户的 steering 要求实现。
- 对方可以再用发送工具回复，没有“最后一条助手输出自动变成回信”的协议要求。
- 收件方显示带来源的一行摘要，展开看正文，适合本项目 compact/expanded 分离。
- 消息不能代用户批准权限、改变权限配置，也不执行正文中的 slash command 或自动展开 @ 附件。
- 入站有 delivered/held/refused 区分，限流、短窗口重复去重与队列上限用于抑制消息循环。
  - 第一版可先做当前本地 scope，不需要复制跨机器传输或全部配置面。
- `notify_when_idle` 是独立可选的一次性订阅；单独订阅不会在被观察会话启动 turn 或花模型 token。
  - idle 通知到达询问方时，其空闲会话仍可能启动新 turn；不能误称它是两端都纯 UI 的通知。
  - 可参考其避免轮询的思路，但首版是否提供该参数尚未确定。

### 同行确实有 TaskManager，区别在统一到哪层

- Kimi `AgentTaskService` 是统一生命周期 registry，覆盖 process/agent 等类型及状态、输出、wait/stop/detach。
  - 同时负责持久化、恢复 reconcile 和通知去重，执行通过各自 Task 实现接入。
  - `MoonshotAI-kimi-code/packages/agent-core-v2/src/agent/task/taskService.ts:213`、`:351`、`:527`。
- OpenCode `Job.Service` 也管理生命周期，不只是完成消息投递。
  - 共同 registry、start/get/wait/block/background/cancel 和按类型恢复；run effect 由调用方提供。
  - `anomalyco-opencode/packages/core/src/job.ts:53`、`:127`、`:171`。
- Codex 保留独立 `ProcessStore` 与 `AgentRegistry`，没有把两者合并成一个任务表。
  - `openai-codex/codex-rs/core/src/unified_exec/mod.rs:150`。
  - `openai-codex/codex-rs/core/src/agent/registry.rs:27`。
- 纠正独立评估中的过度概括：“OpenCode Job 仅相当于投递，不是生命周期”不成立。
- 因此不应把 TaskManager 本身判为过度设计；需要避免的是另造所有执行器或镜像第二套真值。
- 在 Agent 默认异步的前提下，共享任务控制与查询层更有价值。
  - 用任务引用关联已有 shell 记录和 agent session/run，统一读取、等待、停止及通知确认。
  - Bash 进程管理和 Agent 模型执行继续分开；具体类名、存储和模块边界仍待实现设计。

## CLI 语义调整建议：保留命令体系，分清会话、任务和消息

> 以下为核对现有实现后的建议，未实现，也不代表用户已确认所有命令和参数名。

### 可以保留现有会话接口

- `run` 目前就默认后台启动、打印 session ID 并返回，不需要推翻。
- `ps/brief/attach/output` 继续面向会话；`output` 是输出视图，不是某条 peer 消息的回信。
- `--group` 保持会话筛选标签，不悄悄升级为拥有全部后台工作的工作流句柄。
- 保留常用纯文本格式、JSON 已有字段和等待退出码，增量添加运行关联与后台任务状态。
- `respond` 仍是权限/问答响应入口，peer 消息不能代用户调用它批准操作。
- 证据：`src/klaude_code/cli/headless_cmd.py:512`、`:820`、`:877`、`:1050`。

### send、kill 与 /stop 必须对齐新契约

- `send` 默认 step 边界批量投递，不能保留当前“等完整 turn 结束”的忙时默认。
  - 返回入队回执和稳定 message ID，JSON 旧字段可以保留。
  - `--steer` 建议保留为新默认的显式别名，不再走 interrupt-and-restart。
  - 帮助及迁移说明应明确旧打断行为改变；需要中断时使用独立控制命令。
- `kill` 当前公开描述为 Esc 等价命令，建议继续保持对应关系。
  - 改成只停当前推理/等待，后台 child 继续；这是旧级联行为的有意变更，需要说明。
  - 全局 `kill --all` 的选择范围不能用于实现当前会话的 `/stop`。
- CLI 可补显式停止子 agent 的入口，对应 TUI `/stop`。
  - 例如 `klaude stop TARGET --children`，只是候选拼写，尚非现有命令。
  - 范围是目标会话的 owned 子 agent，不包括无关 peer 或独立后台 Bash 服务。
  - 同时取消已受理但尚未启动的子 agent 运行，避免停止后排队工作立即复活。
- 证据：`src/klaude_code/cli/headless_cmd.py:956`、`:1094`。

### wait 不应变成隐藏的远程应答协议

- 当前 `wait` 等到会话离开 queued/running、没有 pending，或进入 waiting_input。
  - `src/klaude_code/cli/headless_cmd.py:472`、`:820`。
- 建议保留会话 barrier 这一类别；明确必要任务尚待处理与主模型正在输出是不同状态。
  - 不因为存在常驻 Bash 就永久等待，也不在后台必要依赖未完成时误报整体完成。
  - session ID、具体 agent run/task ID、shell task ID 保持独立且可关联。
- 等具体后台工作使用共享任务管理层按 task/run 引用等待，不轮询会话猜结果归属。
- `send --wait` 当前是等会话稳定后读最后助手文本，不按 message ID 关联回复。
  - 证据：`src/klaude_code/cli/headless_cmd.py:987`。
  - 为脚本兼容可保留这一外层便利功能，但必须明确它不保证收到这条消息的回答。
  - 原生 MessagePeer 不提供该隐式等待，内部协作也不再依赖它取得所谓对应回复。

### CLI、TUI 和工具共用任务控制能力

- 当前 TUI `/tasks` 只管理 shell list/output/stop，可扩为共享任务视图并保留旧用法。
  - `src/klaude_code/tui/command/tasks_cmd.py:7`、`:31`。
- CLI 可补 `tasks` 类入口，提供 list/output/wait/stop；精确结构仍待确认。
- 命令行读取日志只是查询，不自动表示主 agent 已收到完整结果或某条 peer 消息已被回答。
- 所有入口调用同一控制端口，不解析 `Bash("klaude ...")` 来重建状态或生成协作 UI。
- 验证旧 `run --wait`、`wait --group/--any`、退出码、JSON 与脚本工作流。
- 验证 `kill` 后 child 可继续查询，`/stop` 只影响目标 owner，旧 `/tasks stop SHELL_TASK_ID` 仍可用。