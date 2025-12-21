Last Updated: 2025-12-22

# Tasks: MDStream(commonmark) 重写

## Setup

- [ ] 确认 `markdown-it-py` 是否已作为直接依赖；若没有，执行 `uv add markdown-it-py`

## Implementation

- [ ] 设计并实现 stable/live 分界的纯逻辑函数（stable_line 单调递增）
- [ ] 重写 `src/klaude_code/ui/rich/markdown.py` 的 `MarkdownStream`：Stable 增量打印 + Live 重绘最后 block
- [ ] Live 区切换为 `CropAboveLive`（或提供可替换 Live 类）
- [ ] 明确并实现 `mark` / margin / spinner 的显示规则

## Tests

- [ ] 新增测试：分块边界（段落、列表、引用、fence 未闭合/闭合等）
- [ ] 新增测试：帧一致性（full_render vs stable_accumulated+live_frame）
- [ ] （可选）新增 ANSI 回放测试：重绘区域集中在 Live 尾部

## Validation

- [ ] `uv run pytest`
- [ ] `uv run ruff check --fix .`
- [ ] `uv run ruff format`
- [ ] `uv run pyright`
