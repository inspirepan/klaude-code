# TUI 执行期输入与 follow-up 队列

> 状态：已实现。本文记录当前行为和维护约束，不再作为分阶段实施计划。
> 更细的终端渲染约束见 `src/klaude_code/tui/AGENTS.md`。

## 用户行为

- Agent 运行期间输入框保持可见、可编辑。
- Busy 状态下按 Enter 会提交 `FollowUpAgentOperation`，不会中断当前任务。
- Follow-up 按 FIFO 顺序显示和执行；只在真正开始执行时才成为普通 user turn。
- 队列非空且编辑器为空时，按 Up 会一次取回全部消息，使用独立的
  `--- split ---` 行分隔，供用户统一修改。`Alt+Up` / `Esc Up` 保留相同的回退行为。
- 编辑后重新提交时，生成的 `--- split ---` 行会把内容拆回多条 follow-up。解析器在
  队列编辑模式下也兼容独立的 `---` 行；普通提交只把显式 `--- split ---` 识别为分隔符。
- Ctrl+C / Escape 通过 prompt-toolkit 的按键绑定中断当前 operation。prompt-toolkit 是
  运行期唯一的 stdin reader。

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

1. `tui/runner.py` 在 active operation 存在时把输入转换为 `FollowUpAgentOperation`。
2. `Agent` 保存内存队列，并通过 `Session.set_follow_up_queue()` 同步到 session meta。
3. `PromptToolkitInput.set_pending_messages()` 根据队列快照更新底部 panel。
4. 当前 task 完成后，runner 从队首取出一条并启动下一轮 agent task。
5. 该消息此时才写入 history 并渲染为普通 user turn。
6. 队列完全 drain 后，才调度 prompt suggestion。

未执行的 follow-up 位于 session meta 的 `follow_up_queue`，不在 `events.jsonl` 的会话
历史中。恢复 session 时可以重建 queue panel；已经开始执行的消息只在历史中出现一次。

## 必须保持的约束

- Follow-up 不得取消当前任务，也不得提前 emit 普通 `UserMessageEvent`。
- 队列持久化采用 delete-wins 语义，避免旧的异步 history flush 把已清空队列写回来。
- 当前任务成功、失败或被中断后，都必须继续处理仍然有效的队列。
- `/new` 等改变 session 的命令不得让旧 session 的队列泄漏到新 session。
- Queue panel 是动态 UI，不要用 scrollback `NoticeEvent` 模拟。
- 输入法、方向键和普通 Escape 序列不得触发重复 interrupt。

## 第一版非目标

- Active task 中途 steering 注入。
- Busy 时排队任意会改变 session 状态的 slash command。
- 恢复 Markdown Rich Live repaint。

如果以后增加 steering，应使用独立语义：`followUp` 在当前 task 完整结束后注入，
`steer` 在 turn boundary、下一次 LLM call 前注入，不要复用同一个队列。

## 验证

核心自动化覆盖：

```bash
uv run pytest \
  tests/tui/test_prompt_toolkit_input.py \
  tests/tui/test_tui_runner_esc_regression.py \
  tests/session/test_session.py \
  tests/agent/test_prompt_suggestion.py \
  -q --tb=short
```

终端行为变更还应在 tmux 中做 smoke test：运行一个持续输出的任务，在 busy 期间输入并
提交多条 follow-up，验证 status、queue、input 同时可见，任务按 FIFO drain，并在
`klaude -c` replay 中确认每条 user message 只出现一次。
