# TUI Rendering Notes

## Current Interactive TUI Architecture

During interactive `run_interactive()` sessions, prompt-toolkit owns the bottom
dynamic UI while an agent task is running:

- Rich prints stable scrollback content above the prompt.
- prompt-toolkit renders the running status block, queued follow-up block, and
  input editor in one bottom layout.
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
   `StackedStatusText` and renders it to plain text snapshot lines.
3. `TUICommandRenderer(status_sink=...)` sends those lines to
   `PromptToolkitInput.set_status_lines()`.
4. `PromptToolkitInput` displays those lines in a prompt-toolkit window and
   adds the lightweight prompt-toolkit spinner prefix.

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
- `Alt+Up` / `Esc Up` dequeues all queued messages at once, clears the queue,
  and writes them back into the editor separated by blank lines. Plain `Up`
  remains history navigation.

### Spacing invariants for the prompt bottom layout

- Keep one blank row between recent scrollback and the status block when status
  is visible.
- Keep one blank row between status and the queue block / input editor.
- Keep one blank row below the queue block when queued messages are visible.
- Status, queue, and input should be independent blocks; queue updates must not
  clear or replace running status.

## Legacy / Cleanup Notes

These paths are reduced or legacy in the current interactive model, but not all
of them are removable yet:

- `src/klaude_code/tui/components/rich/status.py`
  - Still used. `StackedStatusText`, `ResponsiveDynamicText`, metadata
    truncation, and status-line rendering are used by `TUICommandRenderer` to
    produce prompt-toolkit status snapshots.
  - The old Rich breathing spinner/shimmer is no longer what the user sees in
    the interactive bottom layout while prompt-toolkit owns status, but the file
    still owns important formatting logic.
- `src/klaude_code/tui/components/rich/live.py`
  - `CropAboveLive` is no longer the normal running-task bottom UI owner during
    interactive prompts.
  - It is still referenced by `TUICommandRenderer` for non-suspended bottom Live
    paths and bash live-tail/status behavior, so do not delete it without first
    removing or replacing those renderer paths and tests.
  - `SingleLine` currently has no production references; it is only covered by
    tests and is a cleanup candidate.
- `MarkdownStream.live_sink` / `TUICommandRenderer.set_stream_renderable()`
  - Assistant Markdown still passes `set_stream_renderable` as a live sink, but
    normal interactive Markdown live repaint is disabled by
    `MARKDOWN_STREAM_LIVE_REPAINT_ENABLED = False`, and prompt-toolkit
    suspension ignores stream renderables while the prompt owns the bottom UI.
  - This is a cleanup candidate, but remove it only after auditing replay,
    bash live-tail, image rendering, and renderer spacing tests.
- `TUICommandRenderer._bottom_live`, `_bottom_renderable()`, and related bottom
  Live height bookkeeping
  - Not the normal owner of running status/input anymore.
  - Still supports non-suspended renderer behavior and existing tests. Treat as
    legacy-but-live code until replaced deliberately.

When deleting any of the above, update the tests that intentionally exercise the
old Rich Live behavior and run a real tmux smoke test. The absence of the normal
interactive path using a component is not enough proof that no non-interactive,
replay, or fallback path still needs it.

Interactive TUI output is sensitive to Rich version differences and terminal Live behavior. When changing spacing or streaming output, verify both the project environment and the globally installed `klaude` tool environment.

## Rich Version Differences

`uv run ...` and `klaude` may use different Python environments. The project `.venv` can have a different Rich version than the `uv tool install -e --force .` environment under `~/.local/share/uv/tools/klaude-code/`.

Do not assume reinstalling the editable tool also aligns dependency versions. In particular, Rich 14 and Rich 15 differ in how `Console.print(Text(...), end="\n")` handles `Text` values that already end with `\n`: Rich 15 emits the text newline plus the `end` newline, which can create double blank lines in streamed Markdown.

When printing pre-rendered Markdown chunks, keep trailing newlines out of the `Text` payload and pass them via `end` instead. This keeps Rich 14 and Rich 15 behavior consistent.

## Markdown Stream Spacing

`MarkdownStream` splits output into stable scrollback and a bottom Live region. Spacing bugs often appear only while streaming, not during replay, because replay renders the full Markdown in one pass.

Keep these invariants:

- Markdown block spacing should produce one visible blank line between Markdown blocks, not two.
- The live suffix should not preserve standalone leading blank lines when the stable prefix already ended at a Markdown block boundary.
- Assistant/thinking message boundaries should still leave one visible blank line before the next rendered block, such as a tool call or metadata line.
- Bottom Live should not add an extra gap between Markdown live content and the spinner; keep that separation only for bash live-tail output.

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
