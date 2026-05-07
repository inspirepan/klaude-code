# TUI unified renderer todolist

## Goal

消除 agent running 期间消息追加时，底部 status、queued follow-up、input editor 偶发抖动的问题。

当前根因是 interactive TUI 存在 split ownership：

- Rich 直接向 main screen scrollback 追加稳定消息内容。
- prompt-toolkit 重绘底部动态区域，包括 live output、running status、queue panel 和 input editor。

当 Rich 输出导致终端滚动时，prompt-toolkit 底部区域可能先被终端滚动挤动，再在下一次 invalidate 中重画回来。最终目标是让 interactive 可见区域由一个 renderer 统一拥有。

## Non-goals

- 不删除 Rich。Rich 继续作为格式化引擎，用来把 renderable / Markdown / panel / table 渲染成 ANSI 或 logical lines。
- 不一次性重写所有 `tui/components/`。大多数组件仍然返回 `RenderableType`，迁移重点是输出边界。
- 不把 interactive TUI 放进 alternate screen。
- 不为了快速止血重新引入 Rich bottom Live。

## Hard constraints

- [ ] 不使用 terminal alternate screen：禁止进入 `\x1b[?1049h` / 退出 `\x1b[?1049l`。
- [ ] interactive TUI 留在 main screen buffer，保留普通终端 scrollback。
- [ ] 可以使用 synchronized output：`\x1b[?2026h` ... `\x1b[?2026l`。
- [ ] 常规 redraw 不清 scrollback；不要把 `\x1b[3J` 作为 routine redraw 的一部分。
- [ ] prompt-toolkit 如果仍作为编辑层，必须继续保持它是唯一 stdin reader。
- [ ] 不增加后台 `os.read(stdin)` 监听器。
- [ ] 不 reintroduce Rich bottom Live、`CropAboveLive` 或旧的 bottom Live 高度 bookkeeping。

## Target architecture

```text
RenderCommand
  -> TUICommandRenderer
  -> TUIOutputSink
       legacy mode: Rich Console.print() directly
       unified mode: Rich renderable -> logical/ANSI lines -> InteractiveViewportState
  -> UnifiedViewportRenderer
       messages
       live output
       running status
       queued follow-ups
       input editor
       footer-like metadata
  -> terminal main screen diff paint
```

Rich 的角色从屏幕 owner 降级为 formatter：

```text
RenderableType / Markdown / Text / Panel
  -> Rich formatting
  -> ANSI/logical lines
  -> viewport state
  -> unified renderer owns terminal writes
```

## Compatibility strategy

- [ ] 引入 dual-mode output sink，而不是一次性改所有组件。
  - [ ] `DirectTerminalSink`：当前行为，继续 `Console.print()`。
  - [ ] `ViewportSink`：把 Rich renderable 转成 lines，追加到 viewport state。
- [ ] replay / non-interactive / debug fallback 继续走 `DirectTerminalSink`。
- [ ] interactive unified mode 才启用 `ViewportSink`。
- [ ] 保留现有 `c_user_input.render_user_input()`、`c_tools.render_tool_result()`、`c_welcome.render_welcome()` 等 renderable 生成逻辑。
- [ ] 先收口所有直接写屏幕的出口，再逐步切换 sink。
- [ ] `patch_stdout(raw=True)` 只作为短期缓解，不作为 unified renderer 的核心方案。

## Current output surfaces to migrate

### Stable scrollback / message output

- [ ] `TUICommandRenderer.print()`
  - 当前：`self.console.print(...)`。
  - 目标：委托给 output sink。
- [ ] `TUICommandRenderer` 内少量直接 `self.console.print(...)`
  - 例如 compaction / handoff / rewind 的 `Rule`、`Text`、`Panel` 输出。
  - 目标：统一改成 sink 或收口到 `self.print()`。
- [ ] `MarkdownStream` stable chunk
  - 当前：`self.console.print(Text.from_ansi(stable_text), end=end)`。
  - 目标：改成 `stable_sink(stable_text, end)` 或 equivalent，避免直接写 stdout。
- [ ] `display_image()` / kitty image raw output
  - 当前：直接向 terminal 写 Kitty image protocol。
  - 目标：先保留 legacy fallback；unified mode 下定义 image block placeholder / raw passthrough 策略。
- [ ] sub-agent quote output
  - 当前：`session_print_context()` 影响 `self.print()` 包 `Quote(...)`。
  - 目标：保留 quote renderable，再由 sink 处理。

### Dynamic bottom output

- [ ] status lines
  - 当前：`StackedStatusText` -> Rich `render_lines()` -> `status_sink` -> prompt-toolkit bottom bar。
  - 目标：`state.status_lines`。
- [ ] stream lines / bash live tail
  - 当前：renderable -> Rich `render_lines()` -> `stream_sink` -> prompt-toolkit bottom bar。
  - 目标：`state.live_output_lines`。
- [ ] queued follow-up panel
  - 当前：`PromptBottomBar` 内 prompt-toolkit fragments。
  - 目标：`state.queued_followups`，由 unified renderer 画。
- [ ] running separator
  - 当前：`PromptBottomBar._get_running_separator_fragments()`。
  - 目标：viewport layout 的 separator line。
- [ ] input editor
  - 当前：prompt-toolkit owns rendering and stdin。
  - 目标：至少在 running mode 下由 unified renderer 显示 input state；prompt-toolkit 可继续保留 buffer/keybindings/stdin。

## Phase 0: document and preserve current contracts

- [ ] 明确 unified renderer 必须保留的能力：
  - [ ] user / assistant / tool / bash / metadata / sub-agent 输出。
  - [ ] running status：主 agent、sub-agent、spinner、elapsed time、token/cost metadata、interrupt hint。
  - [ ] live output：bash live tail 和未来 prompt-owned live output。
  - [ ] queued follow-up panel：展示、编辑、清空、FIFO drain。
  - [ ] input editor：多行输入、history、completion、paste marker、image marker、model/thinking picker。
  - [ ] interrupt：Escape / Ctrl+C 的现有语义。
  - [ ] terminal resize、宽字符、ANSI style、硬件光标定位。
- [ ] 增加或更新 prompt bottom layout snapshot tests：
  - [ ] status block。
  - [ ] metadata line classification。
  - [ ] running separator。
  - [ ] queue block。
  - [ ] stream + status spacing。
- [ ] 记录 tmux smoke checklist：
  - [ ] 持续输出命令。
  - [ ] running 中输入 follow-up。
  - [ ] resize terminal。
  - [ ] interrupt 后恢复 prefill。

## Phase 1: introduce viewport state model

- [ ] 定义 `InteractiveViewportState` 或等价模型。
- [ ] state 至少包含：
  - [ ] stable message blocks。
  - [ ] assistant live suffix / thinking live suffix。
  - [ ] bash live output lines。
  - [ ] status lines + metadata kind。
  - [ ] running separator label。
  - [ ] queued follow-up messages。
  - [ ] input editor snapshot。
  - [ ] footer / metadata lines。
- [ ] 定义 message block identity：
  - [ ] session id。
  - [ ] block kind。
  - [ ] stable lines。
  - [ ] optional ANSI / style metadata。
- [ ] 明确 append-only、replace-live、clear-live、shrink 的 state operation。
- [ ] 单元测试 state operation：
  - [ ] append message。
  - [ ] replace live suffix。
  - [ ] clear stream。
  - [ ] queue update。
  - [ ] status metadata classification。

## Phase 2: add output sinks behind TUICommandRenderer

- [ ] 新增 output sink interface，例如：

```python
class TUIOutputSink:
    def print_renderable(self, renderable: RenderableType, *, end: str = "\n") -> None: ...
    def print_blank_line(self) -> None: ...
    def set_stream_renderable(self, renderable: RenderableType | None) -> None: ...
    def set_status_lines(self, lines: tuple[PromptStatusLine, ...], separator_text: str | None) -> None: ...
```

- [ ] 实现 `DirectTerminalSink`，行为与当前 `TUICommandRenderer` 一致。
- [ ] 实现初版 `ViewportSink`，只写 state，不 paint terminal。
- [ ] `TUICommandRenderer.print()` 改成调用 sink。
- [ ] 收口直接 `self.console.print(...)` 的路径：
  - [ ] welcome。
  - [ ] compaction。
  - [ ] handoff。
  - [ ] rewind。
  - [ ] fork cache hit rate。
  - [ ] error / interrupt。
- [ ] 保留 replay fast path：replay 默认 `DirectTerminalSink`。
- [ ] 测试：现有 renderer spacing tests 在 legacy sink 下不变。

## Phase 3: migrate MarkdownStream stable output

- [ ] 给 `MarkdownStream` 增加 stable output callback。
- [ ] stable callback 接收已渲染 ANSI chunk，避免丢 Rich Markdown formatting。
- [ ] live callback 继续支持现有 `live_sink` 语义。
- [ ] legacy mode callback 内部仍然 `Console.print(Text.from_ansi(...), end=end)`。
- [ ] unified mode callback 把 stable chunk 追加到 `InteractiveViewportState`。
- [ ] 保留 Rich 14 / Rich 15 newline 兼容策略。
- [ ] 测试：
  - [ ] paragraph -> list streaming spacing。
  - [ ] code fence streaming。
  - [ ] final flush。
  - [ ] replay output 不变。

## Phase 4: implement main-screen viewport renderer

- [ ] 定义 logical screen layout：

```text
stable messages
assistant/thinking live suffix
bash live output
status lines
running separator
queued follow-ups
input editor
footer-like metadata
```

- [ ] 读取 terminal width / height。
- [ ] 把完整 logical screen 渲染成 lines。
- [ ] 根据 height 计算 visible viewport。
- [ ] 保存上一帧 lines / viewport / cursor position。
- [ ] 实现 diff paint：
  - [ ] first render：写出当前 logical screen，不清 scrollback。
  - [ ] append-only update：优先走追加路径。
  - [ ] normal update：移动到第一条变化行，清理并重写变化行。
  - [ ] content shrink：clear-on-shrink，避免底部旧行残留。
  - [ ] width change：全量重绘当前 visible screen。
  - [ ] height change：重算 viewport 并全量重绘当前 visible screen。
  - [ ] changed line above previous viewport：全量重绘当前 visible screen。
- [ ] 用 synchronized output 包裹每批 terminal writes。
- [ ] 恢复硬件光标到 input editor 真实位置。
- [ ] 单元测试：
  - [ ] append。
  - [ ] shrink。
  - [ ] resize。
  - [ ] change above viewport。
  - [ ] cursor restore。
  - [ ] ANSI visible width。
  - [ ] CJK / wide char width。

## Phase 5: decide prompt-toolkit role

### Route A: prompt-toolkit as headless-ish editor

- [ ] prompt-toolkit 继续负责 stdin、buffer、history、keybindings、completion data。
- [ ] 禁止 prompt-toolkit 绘制 running bottom layout。
- [ ] 从 prompt-toolkit 提取 editor snapshot：
  - [ ] buffer text。
  - [ ] cursor position。
  - [ ] selection state。
  - [ ] placeholder / suggestion state。
  - [ ] completion state。
  - [ ] picker open state。
- [ ] unified renderer 绘制 input editor 和底部动态区域。
- [ ] 风险验证：IME、completion menu、cursor mapping。

### Route B: replace prompt-toolkit editor layer

- [ ] 自建 input buffer。
- [ ] 自建 history navigation。
- [ ] 自建 keybindings。
- [ ] 自建 completion / picker / paste / image marker handling。
- [ ] 只有在 Route A 成本失控时再走这条路。

推荐顺序：先 Route A，取得统一屏幕 ownership，再评估是否逐步走向 Route B。

## Phase 6: minimum viable unified running mode

先只覆盖最容易抖动的 running 场景。

- [ ] agent 正在运行。
- [ ] prompt active。
- [ ] messages append。
- [ ] status visible。
- [ ] queued follow-up 可见。
- [ ] bash live tail 可见。

允许暂时 fallback：

- [ ] completion menu。
- [ ] model picker。
- [ ] thinking picker。
- [ ] AskUserQuestion selector。
- [ ] complex overlays。
- [ ] image rendering。

tmux smoke：

```bash
tmux new-session -d -s klaude-unified 'cd /Users/panjx/code/GITHUB/klaude-code && uv run klaude -m v4-flash:no-thinking'
tmux send-keys -t klaude-unified 'Run a bash loop that prints one line per second for 10 seconds, then summarize it.' Enter
tmux send-keys -t klaude-unified 'follow up: explain whether the prompt stayed stable while output appended'
tmux capture-pane -pt klaude-unified -S -160
```

验收：

- [ ] input editor 不上下跳动。
- [ ] status 更新不挤动 input。
- [ ] queued follow-up 面板变化不清掉 status。
- [ ] 消息持续追加时底部区域没有可见闪烁或错位。
- [ ] terminal scrollback 仍包含之前的可滚动历史。
- [ ] Escape / Ctrl+C interrupt 语义不变。

## Phase 7: migrate overlays and advanced interactions

- [ ] queued message edit。
- [ ] completion menu。
- [ ] model picker。
- [ ] thinking picker。
- [ ] AskUserQuestion selector。
- [ ] bash live tail full behavior。
- [ ] image / paste placeholder。
- [ ] interrupt prefill restoration。
- [ ] terminal resize while picker is open。

每迁移一个能力：

- [ ] 加一个 focused unit test 或 high-level smoke test。
- [ ] 确认 prompt-toolkit 仍是唯一 stdin reader，除非该阶段明确替换 editor layer。
- [ ] 确认不进入 alternate screen。

## Phase 8: remove split-ownership legacy paths

- [ ] 删除 prompt-toolkit bottom windows 中的 status ownership。
- [ ] 删除 prompt-toolkit bottom windows 中的 stream ownership。
- [ ] 删除 prompt-toolkit bottom windows 中的 queue ownership。
- [ ] `TUICommandRenderer(status_sink=...)` 改成更新 viewport state。
- [ ] `TUICommandRenderer(stream_sink=...)` 改成更新 viewport state。
- [ ] Rich 保留为 renderable formatter，不再在 interactive running 路径直接拥有 stdout。
- [ ] 保留 non-interactive / replay direct Rich print path。
- [ ] 清理过渡 feature flags 和 dead code。

## Validation checklist

- [ ] Unit tests：
  - [ ] viewport state operations。
  - [ ] renderer diff operations。
  - [ ] status line rendering。
  - [ ] MarkdownStream stable/live split。
  - [ ] CJK / ANSI width。
- [ ] Existing tests：
  - [ ] `uv run pytest tests/tui/test_markdown_stream.py tests/tui/test_renderer_bottom_live.py tests/tui/test_renderer_spacing.py -q --tb=short`
  - [ ] `uv run pytest tests/tui/test_prompt_toolkit_input.py -q --tb=short`
  - [ ] `uv run ruff check src/klaude_code/tui src/klaude_code/tui/components/rich tests/tui`
- [ ] tmux smoke：
  - [ ] long bash output。
  - [ ] streaming Markdown paragraph + list。
  - [ ] queued follow-up while running。
  - [ ] interrupt while running。
  - [ ] resize during output。
- [ ] Compare replay vs live output where applicable。

## Known risks

- [ ] prompt-toolkit headless 化可能比预期复杂。
- [ ] IME、宽字符、ANSI width、terminal resize 和硬件光标恢复容易出现边缘问题。
- [ ] Rich renderable 到 lines 的转换必须稳定处理换行、截断和 style。
- [ ] main screen buffer 下的 viewport 管理比 alternate screen 更难。
- [ ] Kitty image protocol 这类 raw terminal output 需要单独策略。
- [ ] synchronized output 不是所有终端都表现一致，需要 fallback。

## One-sentence summary

unified renderer 不要求重写所有 Rich 组件；它要求把 Rich direct stdout 输出收口成可插拔 sink，让 interactive mode 中的消息、live output、status、queue 和 input 都进入同一个 viewport state，再由一个 main-screen renderer 统一 diff/paint。
