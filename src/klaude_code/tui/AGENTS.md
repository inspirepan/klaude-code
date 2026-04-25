# TUI Rendering Notes

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
