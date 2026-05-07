# TUI 执行期输入框与消息排队方案

## 目标

在 agent 运行期间继续展示输入框。用户在 agent 忙碌时提交的消息不再中断当前任务，而是进入 follow-up 队列。队列展示在输入框上方；当输入框为空时按 Up，可以取回最后一条已排队消息并放回编辑器继续修改。

## 基线决策

关闭 Markdown live repaint：将 `MARKDOWN_STREAM_LIVE_REPAINT_ENABLED` 设为 `False`。

这是整体方案的前置条件，不单独作为一个验证阶段。关闭后，执行期动态 UI 只保留一个 owner：

- prompt-toolkit 负责底部常驻动态区域：status、queued messages、input。
- Rich 只负责向 stdout 打印稳定的 scrollback 内容。
- 正常 agent running 路径不再依赖 `CropAboveLive`。

## 阶段 1：agent 运行时保持 prompt-toolkit 输入框活跃

### 实现目标

把 TUI runner 从阻塞式 REPL 改成并发模型：

- `PromptToolkitInput.iter_inputs()` 在 agent task 活跃时仍持续运行。
- idle 时提交消息，仍按现状启动 agent task。
- runner 记录 active operation wait task，但不在 input loop 内直接 await 到任务结束。
- Rich 的稳定输出继续通过 prompt-toolkit `patch_stdout(raw=True)` 打到输入框上方。
- 运行期间暂停 Rich progress UI：`SpinnerStart`、`SpinnerUpdate`、`set_stream_renderable(...)` 不得重新启动 `CropAboveLive` 或 bottom live，避免 status 与输入框抢底部区域。
- 移除运行期后台 ESC stdin monitor。prompt-toolkit 活跃时必须独占 stdin，不能再有线程用 `os.read(stdin)` 读取按键。
- 阶段 1 只保留 Ctrl+C / SIGINT interrupt。运行中按 Escape 暂不作为 interrupt；后续若恢复，必须实现为 prompt-toolkit key binding。

### 可见成果

agent 正在运行时，prompt 仍可见、可编辑。执行期间按键输入不会打乱 Rich 输出，也不会让 prompt 消失。这个阶段可以先不真正排队；busy-time Enter 只要能被 TUI 捕获即可，真正队列在阶段 3 引入。

阶段 1 中，运行期 status 可以暂时不显示。不要为了保留 status 重新启用 Rich Live；status 的正式恢复放到阶段 2。

### tmux 验证

启动项目环境：

```bash
tmux new-session -d -s klaude-phase1 'cd /Users/panjx/code/GITHUB/klaude-code && uv run klaude -m v4-flash:no-thinking'
```

提交一个长任务：

```bash
tmux send-keys -t klaude-phase1 'Run a bash command that prints one line per second for 8 seconds, then summarize the output.' Enter
```

任务运行时向输入框打字，不按 Enter：

```bash
tmux send-keys -t klaude-phase1 'typing while busy should stay in the prompt'
```

抓取 pane：

```bash
tmux capture-pane -pt klaude-phase1 -S -120
```

通过标准：

- agent 仍在运行时，输入区能看到刚输入的文本。
- agent 输出继续出现在 prompt 上方。
- prompt 没有被擦掉、重复绘制，或和 Rich 输出互相穿插。
- `esc to interrupt` 这类 Rich status 不会和 input prompt 拼在同一行。
- 中文输入法提交文本不会丢字节或变成 `??续` 这类损坏文本。
- 普通打字没有明显卡顿。

interrupt 检查：

```bash
tmux send-keys -t klaude-phase1 C-c
tmux capture-pane -pt klaude-phase1 -S -80
```

通过标准：

- running task 按现有 TUI 语义被取消或中断。
- interrupt 结束后 prompt 仍可继续使用。
- 阶段 1 只要求 Ctrl+C interrupt 可用；Escape interrupt 暂不验收。

后台 stdin reader 检查：

```bash
tmux send-keys -t klaude-phase1 '继续输入中文'
tmux capture-pane -pt klaude-phase1 -S -80
```

通过标准：

- 输入框中显示完整的 `继续输入中文`。
- agent 不会因为普通输入或中文输入法提交而出现 `Interrupted by user`。

## 阶段 2：把运行中 status 迁移到 prompt-toolkit

### 实现目标

用 prompt-toolkit status 替代执行期 Rich Live status：

- `SpinnerStart`、`SpinnerStop`、`SpinnerUpdate` 更新一个 status snapshot，而不是启动 `CropAboveLive`。
- `PromptToolkitInput` 在输入框上方用 prompt-toolkit window 渲染 status snapshot。
- spinner 动画通过 prompt-toolkit invalidate 驱动，不再由 Rich Live 驱动。
- metadata 和 status lines 保留现在 Rich status 展示的关键信息。
- 重新提供 `esc to interrupt` 提示时，该提示必须属于 prompt-toolkit status/input layout，而不是 Rich bottom Live。
- 如需恢复 Escape interrupt，必须添加 prompt-toolkit key binding，在 input app 内触发 interrupt operation；禁止恢复后台 ESC stdin monitor。

### 可见成果

agent 运行期间，输入框上方出现 status line，并随 model/tool/status metadata 更新。更新过程不使用 Rich Live，也不破坏输入框。

### tmux 验证

启动新 session：

```bash
tmux new-session -d -s klaude-phase2 'cd /Users/panjx/code/GITHUB/klaude-code && uv run klaude -m v4-flash:no-thinking'
```

提交一个会触发 tool call 和 status 更新的任务：

```bash
tmux send-keys -t klaude-phase2 'Use the Bash tool to run: for i in 1 2 3 4 5; do echo status-$i; sleep 1; done. Then summarize it.' Enter
```

执行期间抓取：

```bash
sleep 2
tmux capture-pane -pt klaude-phase2 -S -100
```

通过标准：

- task running 时，输入框上方能看到 status line。
- tool/status metadata 更新不会在底部制造多余空白。
- status 更新时输入光标仍可用。
- 正常 running 路径看不到 `CropAboveLive` 式的底部 Live 行为。
- `esc to interrupt` 与 input prompt 分属不同 prompt-toolkit 行，不会拼接成一行。
- 如果阶段 2 恢复 Escape interrupt，按 Escape 只触发一次 interrupt；普通输入、中文输入法、方向键不会触发 interrupt。

任务结束后抓取：

```bash
sleep 8
tmux capture-pane -pt klaude-phase2 -S -120
```

通过标准：

- status line 干净消失，或回到 idle 状态。
- 最终输出位于 prompt 上方 scrollback。
- prompt 已准备好接受下一条输入。

## 阶段 3：busy 时提交消息进入 follow-up 队列

### 实现目标

在 agent/runtime 层增加 follow-up queue：

- busy-time Enter 提交 follow-up operation，而不是 interrupt 当前任务。
- follow-up 消息按 FIFO 顺序保存。
- 已排队消息不立即写入 session history。
- 已排队消息不立即 emit 普通 `UserMessageEvent`。
- 队列变化通过 UI event 或 display hook 通知 TUI 更新 queue panel。

### 可见成果

agent 正在运行时继续提交消息，会把消息加入队列。当前 active task 不会被取消或打断。

### tmux 验证

启动新 session：

```bash
tmux new-session -d -s klaude-phase3 'cd /Users/panjx/code/GITHUB/klaude-code && uv run klaude -m v4-flash:no-thinking'
```

提交长任务：

```bash
tmux send-keys -t klaude-phase3 'Run a bash loop for 8 seconds, printing tick-1 through tick-8, then summarize the output.' Enter
```

busy 时提交两条消息：

```bash
tmux send-keys -t klaude-phase3 'follow up one: after that, explain whether queued input worked' Enter
tmux send-keys -t klaude-phase3 'follow up two: then list the order of tasks you handled' Enter
```

第一轮任务完成前抓取：

```bash
tmux capture-pane -pt klaude-phase3 -S -120
```

通过标准：

- running task 继续运行，没有被 cancel 或 interrupt。
- 两条 follow-up 消息可见为 queued messages。
- queued messages 尚未作为普通 conversation turn 出现。

等待全部处理完后再次抓取：

```bash
sleep 20
tmux capture-pane -pt klaude-phase3 -S -200
```

通过标准：

- 原始任务先完成。
- `follow up one` 先于 `follow up two` 执行。
- 每条 follow-up 只在真正开始执行时渲染为普通 user turn。
- 所有 follow-up 处理完后 queue panel 为空。

## 阶段 4：在输入框上方渲染 queued messages

### 实现目标

在 prompt-toolkit layout 中增加 queue panel：

- panel 按队列顺序渲染 follow-up 消息。
- 长消息按终端宽度截断。
- 多行消息展示摘要，避免撑爆输入区。
- queue panel 由 queue snapshot 变化驱动刷新。

### 可见成果

当队列非空时，queued messages 始终显示在输入框上方。队列清空后，panel 自动消失。

### tmux 验证

启动新 session：

```bash
tmux new-session -d -s klaude-phase4 'cd /Users/panjx/code/GITHUB/klaude-code && uv run klaude -m v4-flash:no-thinking'
```

提交长任务和多条 follow-up：

```bash
tmux send-keys -t klaude-phase4 'Run a bash loop for 10 seconds, printing one line per second, then summarize it.' Enter
tmux send-keys -t klaude-phase4 'first queued message' Enter
tmux send-keys -t klaude-phase4 'second queued message with a longer body that should be truncated if the terminal is narrow' Enter
tmux send-keys -t klaude-phase4 'third queued message' Enter
```

busy 时抓取：

```bash
tmux capture-pane -pt klaude-phase4 -S -120
```

通过标准：

- queue panel 出现在输入框上方。
- 消息按 FIFO 顺序展示。
- 输入框仍在 panel 下方可编辑。
- 长 queued message 不破坏布局。

调整 pane 尺寸后再次抓取：

```bash
tmux resize-pane -t klaude-phase4 -x 80 -y 30
tmux capture-pane -pt klaude-phase4 -S -120
```

通过标准：

- queue panel 仍适配终端宽度。
- input 和 status 仍可见。

## 阶段 5：Up 键取回全部 queued messages

### 实现目标

在普通 history navigation 之前增加一个高优先级 Up binding：

- 只在 input buffer 为空时生效。
- 只在 completion/search overlay 未激活时生效。
- 从 follow-up queue 弹出全部消息。
- 把这些消息用空行分隔后填回 input buffer，供用户编辑。
- queue 为空时，Up 保持现有 history 行为。

### 可见成果

当队列非空且输入框为空时，按 Up 会把全部 queued messages 从队列中移除，并用空行分隔后恢复到编辑器里。

### tmux 验证

启动新 session：

```bash
tmux new-session -d -s klaude-phase5 'cd /Users/panjx/code/GITHUB/klaude-code && uv run klaude -m v4-flash:no-thinking'
```

busy 时排两条消息：

```bash
tmux send-keys -t klaude-phase5 'Run a bash loop for 10 seconds, printing one line per second, then summarize it.' Enter
tmux send-keys -t klaude-phase5 'queued one' Enter
tmux send-keys -t klaude-phase5 'queued two to edit' Enter
```

输入框为空时按 Up：

```bash
tmux send-keys -t klaude-phase5 Up
tmux capture-pane -pt klaude-phase5 -S -120
```

通过标准：

- `queued one` 和 `queued two to edit` 都出现在 input buffer 中，并用空行分隔。
- queue panel 清空。

编辑后重新提交：

```bash
tmux send-keys -t klaude-phase5 ' edited' Enter
tmux capture-pane -pt klaude-phase5 -S -120
```

通过标准：

- edited message 重新进入队列。

history fallback 检查：

```bash
tmux send-keys -t klaude-phase5 Up
tmux send-keys -t klaude-phase5 C-u
```

通过标准：

- 当 queue 为空时，Up 仍按原逻辑浏览 prompt history。

## 阶段 6：每个 task 完成后 drain follow-up queue

### 实现目标

把 follow-up queue 接入 agent task 执行：

- active task 完整结束后，取出一条 follow-up message。
- queued message 只有在开始执行时，才 emit/render 为普通 user message。
- queued message 只有在开始执行时，才 append 到 session history。
- 自动启动下一段 agent task。
- 重复以上过程，直到 queue 为空。
- prompt suggestion 只在整个 follow-up chain 结束后再调度。

### 可见成果

agent 在当前任务完成后，自动逐条处理 queued messages。用户不需要再次按 Enter。

### tmux 验证

启动新 session：

```bash
tmux new-session -d -s klaude-phase6 'cd /Users/panjx/code/GITHUB/klaude-code && uv run klaude -m v4-flash:no-thinking'
```

提交一个任务和两条 follow-up：

```bash
tmux send-keys -t klaude-phase6 'Run a short bash loop, then say original task done.' Enter
tmux send-keys -t klaude-phase6 'follow up A: say A done' Enter
tmux send-keys -t klaude-phase6 'follow up B: say B done' Enter
```

等待并抓取：

```bash
sleep 25
tmux capture-pane -pt klaude-phase6 -S -240
```

通过标准：

- 可见执行顺序为 original task、follow up A、follow up B。
- 每条 queued message 都只出现一次 user turn。
- 没有 queued message 被跳过。
- queued message 不会在前一个 task 完成前出现。
- final prompt suggestion 如果存在，只在 follow up B 完成后出现。

replay 检查：

```bash
tmux send-keys -t klaude-phase6 C-c
klaude -c
```

通过标准：

- replay 中每条 user message 只出现一次。
- replay 顺序与实际执行顺序一致。

## 阶段 7：验证全局安装的 klaude 环境

### 实现目标

确认设计在项目虚拟环境之外也成立。全局安装的 `klaude` 可能使用不同依赖环境，所以 TUI 变更需要单独 smoke test。

### tmux 验证

启动全局命令：

```bash
tmux new-session -d -s klaude-global-queue 'cd /Users/panjx/code/GITHUB/klaude-code && klaude -m v4-flash:no-thinking'
```

重复主流程：

```bash
tmux send-keys -t klaude-global-queue 'Run a bash loop for 8 seconds, then summarize it.' Enter
tmux send-keys -t klaude-global-queue 'global follow up one' Enter
tmux send-keys -t klaude-global-queue 'global follow up two' Enter
sleep 20
tmux capture-pane -pt klaude-global-queue -S -240
```

通过标准：

- agent running 时 input 仍可见。
- status 和 queue panel 渲染正常。
- follow-up 按顺序 drain。
- 全局环境中没有出现 Rich Live 相关 spacing 回归。

## 第一版非目标

- active task 中途 steering 注入。
- busy 时排队任意会改变 session 状态的 slash command。
- 保留执行期 Markdown live repaint。
- 正常 running 路径继续复用 `CropAboveLive`。

## 后续扩展：steering

follow-up queue 稳定后，再增加 `steer` 作为独立队列：

- `followUp`：当前 task 完整结束后注入。
- `steer`：在 turn boundary、下一次 LLM call 前注入。

第一版实现应预留 API 空间，但不实现 steering。
