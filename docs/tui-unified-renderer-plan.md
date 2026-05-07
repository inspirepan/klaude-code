# TUI 统一渲染器消除底部抖动计划

## 目标

彻底消除 agent 运行期间消息区追加内容时，底部 status、queued follow-up、input editor 偶发抖动的问题。

根因是当前 interactive TUI 存在 split ownership：

- Rich 负责向普通终端 scrollback 追加稳定消息内容。
- prompt-toolkit 负责重绘底部动态区域，包括 live output、running status、queue panel 和 input editor。

当 Rich 输出导致终端滚动时，prompt-toolkit 底部区域可能先被终端滚动挤动，再在下一次 invalidate 中重画回来。彻底解决需要让 interactive 可见区域由一个 renderer 统一拥有。

## 硬约束

- 不使用 terminal alternate screen：禁止进入 `\x1b[?1049h` / 退出 `\x1b[?1049l`。
- interactive TUI 必须留在 main screen buffer，保留用户普通终端 scrollback。
- 可以使用 synchronized output：`\x1b[?2026h` ... `\x1b[?2026l`，它只让一批输出原子显示，不是备用屏幕。
- 常规 interactive redraw 不清 scrollback；不要把 `\x1b[3J` 作为 routine redraw 的一部分。
- 如果 prompt-toolkit 仍作为编辑层，必须继续保持它是唯一 stdin reader；不要增加后台 `os.read(stdin)` 监听器。
- 不要 reintroduce Rich bottom Live、`CropAboveLive` 或旧的 bottom Live 高度 bookkeeping。

## 总体方向

引入一个统一 interactive renderer，让它负责当前可见 viewport：

```text
logical screen lines =
  chat / stable messages
  live output
  running status
  queued follow-ups
  input editor
  footer-like metadata
```

每次状态变化时：

1. 读取 terminal width / height。
2. 把完整 logical screen 渲染成 lines。
3. 根据 height 计算当前 visible viewport。
4. 与上一帧 lines / viewport 比较。
5. 用 cursor move、clear line、line diff 写出变化。
6. 用 synchronized output 包裹整批更新。
7. 把硬件光标恢复到 input editor 的真实位置。

参考方向是 `badlogic-pi-mono` 的 TUI：chat、status、editor、footer 都属于同一棵 render tree，renderer 追踪 viewport 和硬件光标，并在必要时 clear-on-shrink。

## 阶段 1：冻结当前行为契约

### 实现目标

先明确 unified renderer 需要保留哪些能力，避免重构过程中丢行为：

- stable scrollback：user、assistant、tool、bash、metadata、sub-agent 输出。
- running status：主 agent、sub-agent、spinner、elapsed time、token/cost metadata、interrupt hint。
- live output：bash live tail 和未来 prompt-owned live output。
- queued follow-up panel：展示、编辑、清空、FIFO drain。
- input editor：多行输入、history、completion、paste marker、image marker、model/thinking picker。
- interrupt：Escape / Ctrl+C 的现有语义。
- terminal resize、宽字符、ANSI style、光标定位。

### 产物

- `InteractiveViewportState` 或等价状态模型草案。
- 现有 prompt bottom layout 的快照/单元测试，覆盖 status、queue、running separator、metadata 行分类。
- 一个 tmux smoke checklist，用来复现底部抖动和验证后续修复。

## 阶段 2：把消息追加改成 state update

### 实现目标

在 interactive unified mode 下，`TUICommandRenderer` 不再直接把消息 print 到 stdout，而是把 render command 转成 logical message lines。

### 做法

- 保留 Rich 作为格式化引擎，把 renderable 渲染成 ANSI/plain lines。
- `RenderUserMessage`、`AppendAssistant`、`RenderToolResult`、`RenderBashCommandEnd` 等命令更新 viewport state。
- replay、非 interactive 路径继续沿用现有 Rich direct print，降低迁移风险。
- streaming assistant 内容可以先继续分 stable prefix / live suffix，但输出 owner 必须是 unified renderer。

### 通过标准

- agent 运行中新增消息不会直接写 stdout。
- 所有可见内容都能从 viewport state 重建。
- replay 和非 interactive 输出不受影响。

## 阶段 3：实现 main-screen viewport diff renderer

### 实现目标

建立一个只操作 main screen buffer 的 terminal renderer。

### 渲染策略

- first render：写出当前 logical screen，不清 scrollback。
- width change：全量重绘当前可见屏幕。
- height change：重新计算 viewport 并全量重绘当前可见屏幕。
- changed line above previous viewport：全量重绘当前可见屏幕。
- normal update：移动到第一条变化行，只清理并重写变化行。
- content shrink：clear-on-shrink，避免底部旧行残留，但不清 scrollback。
- append-only update：尽量走差分追加路径。

### 终端控制约束

- 允许使用 cursor movement、carriage return、clear line、clear visible screen。
- 允许使用 synchronized output。
- 禁止使用 alternate screen。
- 常规路径不使用 clear scrollback。

### 通过标准

- 单元测试覆盖 append、shrink、resize、change-above-viewport、cursor restore。
- 宽字符和 ANSI style 的 visible width 计算稳定。
- 普通终端 scrollback 仍保留历史内容。

## 阶段 4：决定 prompt-toolkit 的角色

有两个路线，可以先做过渡路线，再逐步收敛。

### 路线 A：prompt-toolkit 作为编辑层，屏幕由 unified renderer 拥有

prompt-toolkit 继续负责 buffer、history、key bindings、completion 数据和 stdin，但不要让它重绘底部 layout。

需要从 prompt-toolkit 提取：

- buffer text；
- cursor position；
- completion state；
- selection / picker state；
- placeholder / suggestion state。

风险：prompt-toolkit 不天然是 headless editor，completion menu、IME 和光标定位会比较难。

### 路线 B：替换 prompt-toolkit 编辑层

自建 input buffer、history、keybindings、completion、picker、paste/image marker 处理。

优点是架构最干净；缺点是迁移范围最大。

推荐顺序：先尝试路线 A 获取统一屏幕 ownership，再评估是否逐步走向路线 B。

## 阶段 5：最小可行 unified running mode

### 实现目标

只覆盖最容易抖动的 agent running 场景：

- agent 正在运行；
- messages append；
- status visible；
- input active；
- queued follow-up 可见。

初版可以暂时 fallback 的能力：

- completion menu；
- model picker；
- thinking picker；
- AskUserQuestion selector；
- 复杂 overlay；
- 图片渲染。

### tmux 验收

启动 interactive session，提交一个持续输出的任务，并在运行中输入 follow-up：

```bash
tmux new-session -d -s klaude-unified 'cd /Users/panjx/code/GITHUB/klaude-code && uv run klaude -m v4-flash:no-thinking'
tmux send-keys -t klaude-unified 'Run a bash loop that prints one line per second for 10 seconds, then summarize it.' Enter
tmux send-keys -t klaude-unified 'follow up: explain whether the prompt stayed stable while output appended'
tmux capture-pane -pt klaude-unified -S -160
```

通过标准：

- input editor 不上下跳动。
- status 更新不挤动 input。
- queued follow-up 面板变化不清掉 status。
- 消息持续追加时底部区域没有可见闪烁或错位。
- 终端 scrollback 仍包含之前的可滚动历史。

## 阶段 6：迁移 overlays 和高级交互

逐个迁移或适配：

1. queued message edit。
2. completion menu。
3. model picker。
4. thinking picker。
5. AskUserQuestion selector。
6. bash live tail。
7. image / paste placeholder。

每迁移一个能力，都补一个高层 smoke test 或 focused unit test。

## 阶段 7：移除双渲染路径

当 unified renderer 覆盖 interactive running 场景后，清理旧路径：

- 删除 prompt-toolkit bottom windows 中的 status、stream、queue、running separator ownership。
- `TUICommandRenderer(status_sink=...)` 改成更新 unified viewport state。
- `TUICommandRenderer(stream_sink=...)` 改成更新 unified viewport state。
- Rich 保留为 renderable formatting，不再在 interactive running 路径直接拥有 stdout。
- 保留 prompt-toolkit 单 stdin reader 约束，直到编辑层被明确替换。

## 主要风险

- prompt-toolkit headless 化可能比预期复杂。
- IME、宽字符、ANSI width、terminal resize 和硬件光标恢复容易出现边缘问题。
- Rich renderable 到 lines 的转换必须稳定处理换行、截断和 style。
- main screen buffer 下的 viewport 管理比 alternate screen 更难，但这是保留 scrollback 的必要代价。

## 一句话结论

彻底消除抖动，需要停止 Rich 和 prompt-toolkit 分别写屏幕的模式，改成一个不使用备用屏幕的 unified renderer 统一拥有可见 viewport，并通过 line diff、clear-on-shrink 和 synchronized output 在 main screen buffer 中原子更新。