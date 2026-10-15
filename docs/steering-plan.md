# 默认 steering：当前实现与历史调查

> 状态：四个 Phase 已实现并完成分阶段 review 与最终自动化验收；未提交、未重载现有服务。内置 skills 子模块旧指引待独立发布。
> 调查日期：2026-10-15。下文行号对应调查时的本地源码，不代表上游所有版本。
> 异步任务与协作框架的进一步调查见 `docs/async-tools-and-agent-collaboration-plan.md`。

## 最新已确认决策

- Agent 默认异步启动并返回引用，等待与停止作为独立能力；替代早期默认前台等待建议。
- 首版不使用 fast model 判断后台结果的重要性；明确依赖解除等待，预期停止只更新状态。
- 重启恢复上下文、结果及待处理投递，不自动重放可能有副作用的执行。
- Peer 发送只负责入队，不等待回复；参考 Claude Code cross-session messaging 的显式工具通信。
- Esc 停当前推理或等待，后台 child 继续；新增 `/stop` 终止当前会话的全部子 agent。
- 原生协作按 Claude Code 显式消息方式设计，做轻量共享任务管理层统一查询、等待、停止和交付确认。
- CLI 已保留外部脚本工作流并新增 owner-scoped tasks/stop；原生工具优先用于内部编排，具体接口见下一节。
- 下文早期调查、用户最初需求和其他仓库参考原样保留，不代表现状；若与顶部实现摘要冲突，以摘要、实际接口和框架文档 Phase 接入点为准。

## 当前实现：安全边界消费整批，等待与停止分开

- TUI busy 提交和 peer send 持久化入队，在工具结果完整配对后的安全 step 边界按 FIFO 一次 admission 全部快照；保留逐条 ID、来源与图片，同批进入下一次模型请求。
  - `Agent.inject_pending_inputs()` 与 `TaskExecutor` 覆盖下一请求、重试/压缩和结束判断；idle drain 启动新 task 时也消费整批，不再逐条 task-end follow-up。
  - `follow_up_queue` / `FollowUpAgentOperation` 保留内部命名；不再提供与默认 steering 不同的 task-end-only 投递语义。
  - history flush 成功后才移除持久队列副本并 emit 消息，稳定 ID 用于重启/重试去重；不取消普通工具或流式输出，不承诺任意长工具期间即时消费。
- `Agent` 默认 async，返回 task/session 引用；`ManageTasks` 的 `list/output/wait/stop` 管理 owned Agent/Bash，依赖结果必须 wait/output，不轮询 list。
  - steering 使 wait 正常返回 interrupted-wait/still-running，child 继续；wait 超时也不停止执行。
  - dependency 完成解除对应等待；无关 background shell completion 不解除它。后台完成只更新状态，不启动 idle parent turn；忙碌父 agent 可在安全边界接收报告，首版不使用 fast model 判断重要性。
- 原生协作为 `ListPeers({})` 与 `MessagePeer({target, body, reply_to?})`，CLI 是外部 agent、脚本、人工及无原生工具时的 fallback。
  - `send TARGET TEXT [--from LABEL] [--message-id ID] [--reply-to ID] [--steer]` 和 `run --session` 都是 peer 数据；`--steer` 是默认安全投递兼容别名，`--from` 仅显示标签。
  - receipt 只表示 durable accepted/queued，不表示已读或回复；回复必须显式发消息，助手收尾不自动转发。`send --wait` 仅等 session settled 后读最新 output，非相关消息 RPC。
- Esc / `kill TARGET` 仅中断 root 当前推理或等待；TUI `/stop`、`klaude stop TARGET [--children]` 仅停 owned 子 agent（含 queued），不停止 root、独立 Bash 或 peer。
  - `klaude tasks list TARGET`、`output TARGET TASK_ID`、`wait TARGET TASK_ID`、`stop TARGET TASK_ID`；均支持 `--json`，output/wait 支持 `--offset/--limit`，wait 支持 `--timeout SECS`（退出 124，不停止任务）。
  - TUI `/tasks` 接同一任务控制；ps/brief 单列后台 agent 计数，session wait 不等同于所有后台 Bash 的 barrier。
- 用户输入、`source=peer_message`、`source=task_completion` 保留来源区别；后两者是不可信数据，不是操作者授权。不能跨 peer 代答审批/问题或绕过被拒绝的权限，需交回操作者。
- recovery 恢复历史、结果、待处理投递，无法恢复的活跃执行标 `lost`，不自动重跑副作用；稳定 delivery ID 和持久化 history 后 ack 防止重复交付/结算，CLI/TUI 查询与部分结果页不确认模型完整消费。

## Phase4 验收与交付边界

- 当前 runtime tool description、system strategy 和 `klaude agents --prime` 是新契约；内置 `klaude-config` 的旧指引不能反向覆盖它们。
- skills 位于独立 `src/klaude_code/skill/assets` 子模块，旧指引需后续独立 commit/push/release 再更新父 pointer；本轮未获提交权限，不改子模块、不 vendor/copy/loader 覆盖，skill 加载不变。
- 最终通过格式检查、lint/typecheck/import-linter、3361 项 Python 非 network 测试、194 项 Web 测试及 Web 类型检查；构建与打包资产校验通过。
- 集成测试覆盖真实原生工具及 runtime/headless 链路；renderer capture 与 CLI PTY smoke 通过。未测真实模型、network 或完整人工 TUI 操作，未重载正在运行的服务。
- 下文“尚未实现”“待确认”“当前行为”均属于调查时记录：默认 async、不用 fast model、peer 显式消息、CLI tasks/stop、`--steer` 兼容语义已确认，不再作为待用户决定事项。

## 以下为历史调查与早期方案（2026-10-15，非当前接口）

## 已明确的需求

- 运行中消息默认采用 steering，包括 `klaude send` 发给其他实例的消息和 TUI 用户提交。
- 在每个 step 之间的合适时机插入消息，不再等当前完整任务结束。
- 每次消费时，一次取出当前全部待处理消息，而不是每条消息单独运行一轮。
- 特别处理同步 sub-agent 阻塞主 agent 的情况，不能仍然无限等子 agent 完成。
- 更新 TUI 文案，使其与 steering 的新行为一致。
- 当前先保存调查和计划，不开始实现；第二、三个需求见文末及后续框架调查文档。

## 建议语义：安全边界批量注入，steering 与 interrupt 分开

- 空闲时发送消息：正常启动任务。
- 运行中发送消息：持久化进入 steering 队列，在安全边界批量消费。
- 保留每条消息的顺序、身份、来源和图片，送入同一次模型请求，不简单拼成一个字符串。
- 正常 steering 不取消正在进行的模型输出，不强杀普通工具。
- 显式 interrupt/Esc 停当前推理或等待，不级联停止后台 child；`/stop` 专门停止子 agent。
- 上述是调查后的建议，不应将尚未讨论的细节视为用户已确认的要求。

```text
接收消息 -> 持久化入队 -> 通知等待处
当前 step 完成，工具结果配对完整
  一次取出全部待处理消息
  按顺序追加用户消息
  继续下一次模型请求
没有待处理消息，且任务已完成 -> 结束
```

## klaude 当前行为及关键入口

- `klaude send` 默认 follow-up，`--steer` 默认关闭。
  - `src/klaude_code/cli/headless_cmd.py:956`、`:999`。
  - HTTP 请求默认 `steer=False`，服务端按该字段分流。
  - `src/klaude_code/server/routes/headless.py:630`、`:670`。
- 现有 `--steer` 是“中断当前任务，再启动新 turn”，不是向活动任务注入消息。
  - `src/klaude_code/server/headless.py:796`、`:858`。
  - interrupt 会级联停止仍活跃的子 session。
  - `src/klaude_code/agent/runtime/dispatcher.py:328`。
- TUI 忙时提交 `FollowUpAgentOperation`，输入提示为 `Queue a follow-up`。
  - `src/klaude_code/tui/runner.py:763`。
  - `src/klaude_code/tui/input/prompt_toolkit.py:534`。
- follow-up 队列按 FIFO 逐条启动任务，已经支持持久化、恢复及消费确认。
  - `src/klaude_code/agent/agent.py:85`、`:127`。
  - `src/klaude_code/server/headless.py:285`。
- 一个 step 包含模型输出和随后工具执行，全部结束后才发出 `StepEndEvent`。
  - `src/klaude_code/agent/step.py:225`。
  - 外层任务循环与结束判断位于 `src/klaude_code/agent/task.py:666`、`:923`。
- sub-agent 已运行在独立 session，但 Agent 工具同步等待最终结果。
  - `src/klaude_code/agent/runtime/sub_agent.py:121`。
  - `src/klaude_code/tool/agent_tool.py:233`。
  - 结果监听、metadata 和文件变更汇总仍绑在此次等待的生命周期上。
- 既有说明见 `docs/tui-queued-input-plan.md`，其“steering 非目标”将因本需求改变。
  - 该文档要求区分 steering 与 follow-up；若保留显式 follow-up，不应混用消费语义。
  - 可以复用持久化机制，但不能把两类消息不加区分地提前消费。

## 其他仓库的源码调查

以下路径相对于 `/Users/panjx/code/coding-agent/`，调查未修改这些仓库，也未运行其测试。

### Pi：可参考安全边界和 all 模式

- steering 在 assistant 输出和工具批次结束后检查；follow-up 在任务本来要停止时检查。
- 两种队列默认均为 `one-at-a-time`；配置为 `all` 才会一次消费全部消息。
- 同一 assistant 消息的工具批次先执行完、追加结果，再注入 steering。
- 核心 agent loop 中未发现可直接对照的内建同步 sub-agent 等待路径。
- 关键源码：
  - `badlogic-pi-mono/packages/agent/src/agent.ts:143`、`:247`。
  - `badlogic-pi-mono/packages/agent/src/agent-loop.ts:175`、`:258`、`:295`。
- 边界测试：
  - `badlogic-pi-mono/packages/agent/test/agent.test.ts:823`、`:1042`。
  - `badlogic-pi-mono/packages/agent/test/agent-loop.test.ts:791`、`:1458`。

### Codex：可参考输入唤醒等待，而不停止子 agent

- TUI 活动 turn 中的提交作为 steering，core 追加 pending input 并发出活动通知。
- 允许接收输入时批量取出 pending 项，不允许时保留。
- `wait_agent` 等待协作事件、steering 或超时；steering 使其正常返回等待被新输入打断。
- `spawn_agent` 和 `wait_agent` 分离，并非 klaude 当前的同步 Agent 工具形态。
- 关键源码：
  - `openai-codex/codex-rs/core/src/session/input_queue.rs:368`、`:400`。
  - `openai-codex/codex-rs/core/src/tools/handlers/multi_agents_v2/wait.rs:67`、`:202`。
  - `openai-codex/codex-rs/core/src/tools/handlers/multi_agents_v2/spawn.rs:94`。
- 边界测试：`openai-codex/codex-rs/core/tests/suite/pending_input.rs:700`、`:1409`。
  - 覆盖 steering 唤醒子 agent 等待，以及工具 drain 期间保留多条输入和真实工具输出。

### Kimi：单独的 steering 信号可以解除等待

- steer 会触发活动 step 的 steering 信号，将输入合入活动 turn。
- 多条 steer 可合并应用，不是每条单独启动新任务。
- `WaitFor` 区分 steering 与真正取消：前者正常返回，后台任务继续运行。
- 关键源码：
  - `MoonshotAI-kimi-code/packages/agent-core-v2/src/agent/loop/loopService.ts:1310`。
  - `MoonshotAI-kimi-code/packages/agent-core-v2/src/agent/tools/task/task-wait/taskWaitTool.ts:187`。
- 边界测试：`MoonshotAI-kimi-code/packages/agent-core-v2/test/agent/task/tools/task-tools.test.ts:1175`、`:1227`。

### OpenCode 与 Hermes：等工具边界仍可能被同步工具阻塞

- OpenCode 使用持久 inbox，区分 step 边界的 steer 与空闲后处理的 queue。
  - 所查 runner 路径未显示新 steer 会自动取消正在执行的同步子代理工具。
  - `anomalyco-opencode/packages/core/src/session/runner/llm.ts:57`、`:109`。
  - `anomalyco-opencode/packages/core/src/session/execution.ts:150`。
  - queue 边界测试：`anomalyco-opencode/packages/core/test/session-runner.test.ts:1432`。
  - 没有找到单独证明 sub-agent 阻塞行为的测试；此结论来自控制流调查。
- Hermes 将多条 steer 合并进 pending 缓冲，在工具批次结束后的下一次请求前消费。
  - steer 不强杀工具；同步前台子代理不返回时，消息仍可能被阻塞。
  - `/redirect` 在模型请求和工具执行期间的行为不同，不能与普通 steer 混为一谈。
  - `hermes-agent/agent/interrupt_control.py:267`。
  - `hermes-agent/agent/turn_iteration_prep.py:175`、`:284`。

## 拟实施范围

1. 实现 steering 队列与安全消费边界。
   - 批量取走队列快照，历史落盘后确认消费，恢复时按消息身份去重。
   - 在任务结束前检查待处理消息，覆盖最后一步与运行转空闲的竞态。
   - 压缩和重试期间收到的消息，在后续请求前也要有明确消费机会。
2. 解除同步 sub-agent 等待，但保留其运行与结果收集。
   - 等待“子 agent 完成”和“steering 到达”；后者使 Agent 工具提前正常返回。
   - 返回仍运行状态和 session ID，完整配对原 tool call，不伪造子 agent 已完成。
   - runtime 继续监听最终结果；完成后向父会话投递独立的内部完成通知。
   - 不为已经返回的 Agent 工具再追加第二个 tool result。
   - 按实际 child 生命周期维护状态、费用与文件变更，不随等待结束而提前结算。
   - 完成通知需要去重、恢复和显式停止保护；不能只留在内存回调里。
3. 统一 CLI、服务端与 TUI 入口。
   - 默认运行中消息走 steering；现有 `--steer` 不再沿用中断重启路径。
   - CLI 帮助和回执改成安全边界投递，不再承诺当前完整 turn 结束后才投递。
   - TUI 输入提示建议改为 `Steer the agent`，待处理区说明安全边界送达。
   - 保留未消费消息的撤回编辑；消费后再从待处理区移除并显示正常用户消息。
4. 补充针对行为边界的测试，并同步旧文档和模型可见的 CLI 使用指引。

## 验证重点与尚待确定的细节

- 多条消息全部进入下一次请求，FIFO 顺序、来源和图片不丢失。
- 最后一步、压缩、重试、空闲切换、并行发送时不漏消息、不重复消费。
- 一个或多个同步 sub-agent 等待中收到 steering：主 agent 恢复，child 继续，结果只投递一次。
- 工具调用与结果保持配对；子 agent 费用和文件变更不漏记、不重复记。
- TUI 待处理区、撤回编辑、重连回放及服务端重启后的状态一致。
- 显式停止不会被迟到的内部完成通知自动唤醒。
- 普通长工具不被强杀，因此不支持提前让出的工具仍可能延迟消息送达。
- 显式 follow-up 是否继续提供、旧 `--steer` 的兼容方式、权限交互等待时的行为，实施前再确定。
- 当前没有实现代码，未运行测试；上述方案应与后续两个需求一起评估。

## 需求二：避免后台 Bash 完成后无意义地重新唤醒主 agent

- 不调用 ManageShell，Bash 超过默认前台等待窗口也会自动转后台。
- 用户案例：mock 前端被主动停止，后台完成通知又启动一轮主 agent，只解释这不是错误。
- 用户希望考虑使用 fast model 判断是否有必要唤醒，而不是每次完成都运行主模型。
- 调查确认：`ShellTaskManager` 发布后台终态回调，headless 在空闲后直接提交主 agent turn。
  - `src/klaude_code/tool/shell/bash_tool.py:173`。
  - `src/klaude_code/tool/shell/task_manager.py:179`。
  - `src/klaude_code/server/headless.py:202`、`:241`。
- 建议区分“状态更新、结果入队、启动推理”；显式停止、已交付结果等先按确定规则处理。
- fast model 仅用于模糊场景；不应把取消正常回调等同于隐藏任务状态或丢弃结果。
- 具体唤醒策略与异常降级仍为待确认设计，不是已实现行为。

## 需求三：调查原生 peer 协作，分开助手答复与协作消息

- 这是调查需求，不代表必须立即实现新工具或替换 CLI。
- 用户倾向 ListPeers / MessagePeer 一类原生工具，支持可见的协作和显式工具回复。
- peer 可以选择不回复；不应把每条助手输出自动当作发给另一个 agent 的消息。
- 调查确认：`klaude run` 默认只返回 session ID，不自动推送后续助手输出。
- 但 `output`、`run --wait`、`send --wait` 等会读取助手文本作为会话结果，没有独立回复协议。
  - `src/klaude_code/server/routes/headless.py:247`。
  - `src/klaude_code/cli/headless_cmd.py:956`。
- 现有 sender 标签只有文本归因，没有独立 message ID / reply-to / inbox。
- “派人”暂按 Pi 理解；Pi core 未发现内建 peer 工具，durable 包有自定义后台 subagent 示例。
- 用户追加调查：评估异步工具统一框架、Agent 工具异步化和 steering 后子任务继续运行。
- 用户提供的通用设计参考：
  - https://github.com/anthropics/skills/blob/main/skills/claude-api/shared/agent-design.md
- 详细源码对照、边界和分阶段建议见 `docs/async-tools-and-agent-collaboration-plan.md`。