# TUI 执行期输入与批量 steering 队列

> 状态：已实现。本文记录当前行为和维护约束，不再作为分阶段实施计划。
> 更细的终端渲染约束见 `src/klaude_code/tui/AGENTS.md`。
> 当前 `FollowUpAgentOperation` / `follow_up_queue` 是沿用的内部命名，语义已改为安全边界批量 steering，不是 task 结束后逐条执行。

## 用户行为

- Agent 运行期间输入框保持可见、可编辑。
- Busy 状态下按 Enter 会提交 `FollowUpAgentOperation`，不会中断当前任务。
- 待处理消息按 FIFO 显示，在下一安全 step 边界一次消费当时的全部队列快照；每条保留身份、来源和图片，进入同一次模型请求，不拼成单条字符串。
- 消费先完成当前 step 的工具结果配对，再确认历史落盘、清除持久队列并显示消息；不取消流式输出或强杀普通工具。
- Busy 提示为 `Steer the agent`，待处理区显示 `Steering (...) · next safe step · ↑ to edit.`。
- 队列非空且编辑器为空时，按 Up 会一次取回全部消息，使用独立的
  `--- split ---` 行分隔，供用户统一修改。`alt-up` / `Esc Up` 保留相同的回退行为。
- 编辑后重新提交时，生成的 `--- split ---` 行会把内容拆回多条 follow-up。解析器在
  队列编辑模式下也兼容独立的 `---` 行；普通提交只把显式 `--- split ---` 识别为分隔符。
- ctrl-c / Escape 通过 prompt-toolkit 的按键绑定中断当前 operation。prompt-toolkit 是
  运行期唯一的 stdin reader。
- Esc 只中断 root 当前推理或等待，后台 child 继续；`/stop` 单独停止 owned 子 agent，`/tasks` 管理 owned Agent/Bash 的 list/output/wait/stop。

## 运行模型

交互式 TUI 的底部动态区域只有一个 owner：prompt-toolkit。

```text
Rich stable scrollback
        ↓
prompt-toolkit live stream
prompt-toolkit status
prompt-toolkit follow-up queue
prompt-toolkit input editor
```

- Rich 只向输入框上方输出稳定 scrollback。
- `TUICommandRenderer` 通过 `status_sink` 和 `stream_sink` 把快照交给
  `PromptToolkitInput`。
- `MARKDOWN_STREAM_LIVE_REPAINT_ENABLED` 保持 `False`；不要恢复 Rich bottom Live、
  `CropAboveLive` 或后台 stdin monitor。
- Status、queue 和 input 是相互独立的 block；更新队列不能清空 status。

## 队列生命周期

1. TUI runner 在 active operation 存在时通过 WebSocket 提交 `FollowUpAgentOperation`，排队与消费发生在 server。
2. `Agent.follow_up()` 保存带稳定 ID 的队列，通过 `Session.set_follow_up_queue()` 持久化并设置输入活动信号。
3. `PromptToolkitInput.set_pending_messages()` 根据队列快照更新底部 panel。
4. `TaskExecutor` 在下一请求前和结束判断前调用 `Agent.inject_pending_inputs()`，以 FIFO 快照批量 admission；覆盖重试、压缩及最后一步。
5. batch 在一次 history 写入中保留各条消息，等待 flush 确认后才移除持久队列副本并发出消息事件；途中新输入留给下一批。
6. idle 或当前 task 已退出时，由 `HeadlessRuntime` 调度既有 drain/并发 slot 路径，新 task 在首个边界消费整批，不为每条各启动一轮。
7. 队列完全 drain 后，才调度 prompt suggestion。

未执行的 follow-up 位于 session meta 的 `follow_up_queue`，不在 `events.jsonl` 的会话
历史中。admission 期间先保留持久队列副本，历史确认后清除；恢复按稳定 ID 去重，避免 flush/清队列之间崩溃造成重复。恢复 session 时可以重建 queue panel。

用户输入、`source=peer_message` 与 `source=task_completion` 不混为同类授权：peer 有结构化发送者与 receipt，后台报告单独显示，都不能代替操作者批准。`ListPeers` / `MessagePeer` 用于原生协作，最后一条助手输出不自动成为 peer 回复。

## 必须保持的约束

- Steering 不得取消当前任务，也不得在 history flush 确认前 emit 普通 `UserMessageEvent`。
- 队列持久化采用 delete-wins 语义，避免旧的异步 history flush 把已清空队列写回来。
- 任务结束检查与 idle drain 不得漏掉仍有效的 batch；显式 interrupt、失败 latch 和重试遵守 server 调度策略，不靠无条件唤醒恢复执行。
- `ManageTasks wait` 可因 steering 正常返回 interrupted-wait/still-running，底层 child 继续；目标 dependency 完成才解除对应等待，无关后台 shell completion 不解除它。
- 后台完成只更新状态，不启动 idle parent turn；报告可在忙碌父 agent 的安全边界交付，稳定 ID 与 durable ack 防重。CLI/TUI 读取及部分结果页不确认模型完整消费。
- `/new` 等改变 session 的命令不得让旧 session 的队列泄漏到新 session。
- Queue panel 是动态 UI，不要用 scrollback `NoticeEvent` 模拟。
- 输入法、方向键和普通 Escape 序列不得触发重复 interrupt。

## 当前非目标

- Busy 时排队任意会改变 session 状态的 slash command。
- 恢复 Markdown Rich Live repaint。
- 强杀普通长工具以承诺任意时刻即时 steering。

默认输入统一使用批量 steering；旧 `follow_up` 命名不再代表独立的 task-end-only 模式。CLI `send --steer` 也是默认安全投递的兼容别名，不是中断重启。

## 验证

相关自动化检查入口（不是本轮已运行结果）：

```bash
uv run pytest \
  tests/tui/test_prompt_toolkit_input.py \
  tests/agent/test_agent_task.py \
  tests/agent/test_background_tasks.py \
  tests/server/test_headless_unit.py \
  tests/server/test_peer_messages.py \
  tests/tui/test_tui_runner_esc_regression.py \
  tests/session/test_session.py \
  tests/agent/test_prompt_suggestion.py \
  -q --tb=short
```

终端行为变更还应在 tmux 中做 smoke test：运行一个持续输出的任务，在 busy 期间输入并
提交多条消息，验证 status、queue、input 同时可见，安全边界按 FIFO batch 消费，并在
`klaude -c` replay 中确认每条 user message 只出现一次。

本轮只同步文档和 prime guide，相关格式/CLI 检查单独报告；上述自动化、重启/重连与终端 smoke 的最终结论由主会话补充。内置 `klaude-config` 旧指引需后续独立 skills 子模块发布；当前 tool description / system strategy / prime guide 优先，skill 加载行为不变。
