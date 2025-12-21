Last Updated: 2025-12-22

# Context: MDStream(commonmark) 重写

## Key Files

- `src/klaude_code/ui/rich/markdown.py`：当前 `MarkdownStream` 实现与 Rich Markdown 自定义元素（NoInsetMarkdown/ThinkingMarkdown）。
- `src/klaude_code/ui/rich/live.py`：`CropAboveLive`，可用于 Live 区“只显示底部”而非固定行窗口。
- `src/klaude_code/ui/modes/repl/event_handler.py`：`MarkdownStream` 的主要调用点（assistant/thinking streaming）。
- `src/klaude_code/ui/renderers/*`：相关 markdown theme / code theme 的来源。
- `tests/`：新增测试的放置位置。

## Decisions

- 解析器：使用 `MarkdownIt("commonmark")`。
- 职责划分：
  - MarkdownIt 仅用于“确定 stable/live 的 block 边界”。
  - Rich Markdown 继续负责最终渲染（保留现有样式与元素）。
- 渲染模型：Stable 增量追加打印；Live 只重绘最后一个 block。

## External Reference

- Textual 的实现参考：`/Users/inspirepan/code/GITHUB/Textualize-textual/src/textual/widgets/_markdown.py`
  - 重点思想：MarkdownIt token 的 `map` 用于增量/分块处理。

## Constraints / Non-goals

- 不考虑兼容性（个人项目），允许内部 API 变更。
- 不追求“最少改动”；以“最干净的架构”优先。

## Testing Notes

建议新增两类测试：

1. 纯逻辑：stable_line 计算（chunk 驱动，stable_line 单调）。
2. 帧一致性：每帧 stable_accumulated + live_frame 等价于 full_render（ANSI 文本层面）。

Optional：ANSI 回放测试（pyte）验证重绘区域集中在 Live 尾部。

## Commands

- `uv run pytest -k markdown_stream`
- `uv run ruff check --fix .`
- `uv run ruff format`
- `uv run pyright`
