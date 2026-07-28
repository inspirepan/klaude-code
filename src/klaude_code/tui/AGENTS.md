# TUI Rendering Notes

## Current Interactive TUI Architecture

During interactive `run_interactive()` sessions, prompt-toolkit owns the bottom
dynamic UI while an agent task is running:

- Rich prints stable scrollback content above the prompt.
- prompt-toolkit renders live output, running status, queued follow-up block,
  and input editor in one bottom layout.
- Interactive sessions default to compact transcript rendering: thinking is kept
  out of the scrollback entirely (the status line reports that the model is
  reasoning plus its char count, and the last few lines of the reasoning scroll
  through a transient preview window below it — see the renderer's thinking live
  tail) and sub-agent internals are represented
  by a batched status/summary view. `Ctrl+O` toggles the process-local expanded
  view at any time — idle or mid-run — by clearing the screen and replaying the
  display's event tape; expanded mode preserves the full transcript rendering —
  a live markdown stream for the main agent and a complete thinking block per
  sub-agent once that block finishes.
- Transcript rebuilds (Ctrl+O toggle, `/refresh`) replay `TUIDisplay._tape`
  (`control/event_tape.py`), NOT `runtime.replay_session_history`. The tape
  records everything the display consumed — including the in-flight turn that
  persisted history does not cover — so a mid-run rebuild reproduces the screen
  and the machine state exactly. Rules:
  - The tape is the single re-render source. Do not add a second replay path
    from persisted history for anything the live display already consumed.
  - `DisplayStateMachine` handlers always run with live semantics; a rebuild
    goes through `transition_rebuild`, which only filters the transient-UI
    commands (`_REBUILD_SUPPRESSED_COMMANDS`: spinner/task-clock/title). Do not
    reintroduce per-handler `is_replay` branches — put state bookkeeping in the
    handler and let the filter drop the UI commands.
  - Toggle/refresh are bus events (`ToggleTranscriptDetailEvent`,
    `RefreshDisplayEvent`) handled inside `consume_envelope`, so a rebuild is
    serialized with live events by construction. Do not call rebuild methods on
    the display from outside that consumer.
  - Mid-run rebuilds end with `renderer.flush_rebuild_tails()`: open
    assistant/thinking streams render their stabilized prefix and stay open so
    live deltas continue them; an active bash or compact-thinking tail is
    re-emitted.
  - Terminal width changes reuse the same path: `ResizeWatcher`
    (`input/resize_watcher.py`) chains onto the prompt-toolkit app's
    `_on_resize`, debounces the SIGWINCH burst, and emits a
    `RefreshDisplayEvent` only when the settled width actually changed
    (height-only resizes never rewrap scrollback). Do not register a separate
    SIGWINCH handler — prompt-toolkit owns the signal and re-binds it per app
    run.
  - The repaint erases scrollback (`2J 3J H`), which yanks a scrolled-up
    reader to the bottom, and the terminal protocol offers no way to query or
    restore a viewport position. So width repaints are timed, not forced:
    immediate only when the user pressed a key recently (they are at the
    prompt, viewport already at the bottom); otherwise parked until the next
    key press — the moment terminals snap to the bottom on their own. Do not
    make the resize repaint unconditional.
- The detail level itself lives in `tui/transcript_detail.py`, not in a bool on
  each layer. Rules when touching compact/expanded behavior:
  - "Does this event print at all" belongs in the `_HIDDEN_IN` table there.
    `DisplayStateMachine._visible` and `TUICommandRenderer._visible` both ask it;
    do not add a fresh `if compact and is_sub_agent` guard beside a display method.
  - "How much does it print" is a `detail: Detail` keyword threaded into the
    component. Do not add a second `compact: bool` convention or a public
    `render_compact_*` twin of an existing renderer; `render_compact_*` is only
    for renderables that have no expanded counterpart at all.
  - `TranscriptDetail` is one object shared by the machine and the renderer;
    `TUIDisplay` owns it. Never give the two layers separate copies -- they would
    drift on toggle and paint a mixed transcript.
  - `compact` in `components/rich/status.py` is the terminal-*width* axis and is
    spelled `narrow`. Keep the two axes textually distinct.
- `MARKDOWN_STREAM_LIVE_REPAINT_ENABLED` is expected to stay `False` for this
  model; do not re-enable Markdown bottom Live to fix spacing or repaint bugs.
- prompt-toolkit must be the only runtime stdin reader. Do not add background
  `os.read(stdin)` monitors. Escape interrupt is implemented as a prompt-toolkit
  key binding, not as a background stdin reader.

### Running status flow

The status data still originates in the existing renderer/status pipeline:

1. `DisplayStateMachine` emits `SpinnerStart` / `SpinnerUpdate` /
   `SpinnerStop` commands.
2. `TUICommandRenderer` builds the Rich status renderable with
   `StackedStatusText` and renders it to styled snapshot fragments. Interactive
   snapshots disable Rich shimmer; prompt-toolkit owns the only status animation.
3. `TUICommandRenderer(status_sink=...)` sends those lines to
   `PromptToolkitInput.set_status_lines()`.
4. `PromptToolkitInput` displays those lines in a prompt-toolkit window and
   adds the lightweight prompt-toolkit spinner prefix. Sub-agent rows reuse the
   same frames with their identity color; completed rows use a static marker.
5. `PromptToolkitInput` periodically asks the renderer to refresh the status
   snapshot so elapsed-time metadata keeps updating while only the spinner is
   animating.

Do not bypass this pipeline with direct prompt-toolkit status strings unless you
also preserve sub-agent coloring/truncation semantics and metadata formatting.

### Queued follow-up input flow

- Busy-time Enter submits a `FollowUpAgentOperation` instead of interrupting or
  starting another task.
- Queued messages are stored on `Agent` and are not immediately written to
  session history or emitted as normal user turns.
- The queue panel is prompt-toolkit dynamic UI, not scrollback. Do not emit
  queued-message `NoticeEvent`s for the queue panel.
- Current task completion drains queued follow-ups FIFO. Each queued message is
  rendered as a normal user turn only when it actually begins execution.
- Plain `Up` on an empty editor with queued messages dequeues all queued
  messages at once, clears the queue, and writes them back into the editor
  separated by standalone `--- split ---` lines. Queue-edit parsing also
  accepts standalone `---` lines. `Alt+Up` / `Esc Up` keeps the same dequeue
  behavior as a fallback. Plain `Up` remains history navigation when the queue
  is empty.

### Live output flow

- Renderer live output, such as bash-mode live tail, should use
  `TUICommandRenderer(stream_sink=...)` while prompt-toolkit owns the bottom UI.
- `PromptToolkitInput.set_stream_lines()` renders the live-output block below
  status and above the queue and input.
- Do not reintroduce `CropAboveLive` for running prompt-owned live output.

### Spacing invariants for the prompt bottom layout

- Bottom-row stability is the core invariant: shrinking the bar without new
  scrollback content repaints it at a higher bottom row and the whole bar
  visibly hops up one line. The renderer therefore holds an ended stream's
  `end_of_stream` signal until its next scrollback write, so the height
  collapse lands in the same redraw that grows the transcript. Growth only
  scrolls the view, which reads as normal streaming.
- Keep one blank row between recent scrollback and the status block at all
  times; the status must never sit flush against transcript content.
- Keep the live-tail block (bash output, thinking preview) directly below
  status when visible.
- Keep status directly above the queue block / input editor.
- Keep one blank row above the queue block and none below it; the queue sits
  directly on the input's top rule.
- Status, queue, and input should be independent blocks; queue updates must not
  clear or replace running status.

## Legacy / Cleanup Notes

These paths are reduced or legacy in the current interactive model:

- `src/klaude_code/tui/components/rich/status.py`
  - Still used. `StackedStatusText`, `ResponsiveDynamicText`, metadata
    truncation, and status-line rendering are used by `TUICommandRenderer` to
    produce prompt-toolkit status snapshots.
  - The old Rich breathing spinner/shimmer is no longer what the user sees in
    the interactive bottom layout while prompt-toolkit owns status, but the file
    still owns important formatting logic.
- `MarkdownStream.live_sink` / `TUICommandRenderer.set_stream_renderable()`
  - Assistant Markdown still passes `set_stream_renderable` as a live sink, but
    normal interactive Markdown live repaint is disabled by
    `MARKDOWN_STREAM_LIVE_REPAINT_ENABLED = False`; stream renderables are
    snapshots for prompt-toolkit `stream_sink`, not Rich bottom Live updates.
  - This is still useful for bash live-tail and any future prompt-owned live
    output, but should not start terminal Live rendering.

Do not reintroduce `src/klaude_code/tui/components/rich/live.py`,
`CropAboveLive`, `_bottom_live`, `_bottom_renderable()`, or related bottom Live
height bookkeeping. The previous Rich bottom Live fallback has been removed;
new running output belongs in the prompt-toolkit bottom layout.

Interactive TUI output is sensitive to Rich version differences and terminal Live behavior. When changing spacing or streaming output, verify both the project environment and the globally installed `klaude` tool environment.

## Rich Version Differences

`uv run ...` and `klaude` may use different Python environments. The project `.venv` can have a different Rich version than the `uv tool install -e --force .` environment under `~/.local/share/uv/tools/klaude-code/`.

Do not assume reinstalling the editable tool also aligns dependency versions. In particular, Rich 14 and Rich 15 differ in how `Console.print(Text(...), end="\n")` handles `Text` values that already end with `\n`: Rich 15 emits the text newline plus the `end` newline, which can create double blank lines in streamed Markdown.

When printing pre-rendered Markdown chunks, keep trailing newlines out of the `Text` payload and pass them via `end` instead. This keeps Rich 14 and Rich 15 behavior consistent.

## Markdown Stream Spacing

`MarkdownStream` splits output into stable scrollback and a live suffix snapshot. Spacing bugs often appear only while streaming, not during replay, because replay renders the full Markdown in one pass.

Keep these invariants:

- Markdown block spacing should produce one visible blank line between Markdown blocks, not two.
- The live suffix should not preserve standalone leading blank lines when the stable prefix already ended at a Markdown block boundary.
- Assistant/thinking message boundaries should still leave one visible blank line before the next rendered block, such as a tool call or metadata line.
- Prompt live output should not add an extra gap between Markdown live content and the status block; keep that separation only for bash live-tail output. The compact-thinking preview also sits flush against the status line, which reads as its header.

## Verification

For spacing changes, test both environments when possible:

```bash
uv run pytest tests/tui/test_markdown_stream.py tests/tui/test_renderer_bottom_live.py tests/tui/test_renderer_spacing.py -q --tb=short
uv run ruff check src/klaude_code/tui src/klaude_code/tui/components/rich tests/tui
```

Also run a real tmux smoke test with the globally installed command, because that exercises the `uv tool` dependency environment:

```bash
tmux new-session -d -s klaude-smoke 'cd /path/to/repo && klaude -m v4-flash:no-thinking'
```

Use prompts that force Markdown streaming boundaries, for example a paragraph followed by a list. Compare live output against `klaude -c` replay only after accounting for the fact that replay does not use the bottom Live stream.
