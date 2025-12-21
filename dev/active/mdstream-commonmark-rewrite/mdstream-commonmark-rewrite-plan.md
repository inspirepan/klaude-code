Last Updated: 2025-12-22

# MDStream (Rich) 重写：基于 MarkdownIt(commonmark) 的块级流式渲染

## Executive Summary

目标：完全重写 `src/klaude_code/ui/rich/markdown.py` 的 `MarkdownStream`，从“按行切分 + 全量重渲染”的策略切换为“按块分段 + 稳定区增量追加 + Live 区持续重绘最后未完成块”的策略。

核心原则：

- Stable 区：只输出已经完成的 Markdown block（永不回滚 / 永不重绘）。
- Live 区：只显示最后一个可能变化的 block（持续重绘）。
- 分块判定：使用 `MarkdownIt("commonmark")` 的 token stream（尤其是 `token.level == 0` 且 `token.map`）来确定 block 边界，而不是按行/空行猜测。

收益：

- 解决按行窗口策略导致的抖动、错位、代码块闭合前后跳动等问题。
- 终端 scrollback 体验更好：历史内容是真正“打印出来”的，而不是 Live 反复重画。
- 架构更干净：解析（MarkdownIt）与渲染（Rich Markdown）解耦。

## Current State Analysis

当前实现（`src/klaude_code/ui/rich/markdown.py`）的关键特征：

- 每次 `update(text)` 都会对「截至目前的全文」进行渲染，然后再按行拆分为 stable/live 两段。
- 使用 `live_window` 保留尾部行在 Live 中重绘，其他行直接 `console.print()`。

已知缺陷（来自现象与设计推断）：

- Markdown 的“语义边界”不是行：例如 fenced code block、列表、引用、表格等，会因为尾部内容变化导致前面“某些行”的渲染结构发生变化。
- 以行作为稳定性判据会误把仍可能变化的内容打印到 stable 区；一旦打印，无法撤销，造成视觉错乱。
- 全量渲染 + 行切分会引入不必要的 CPU/IO 开销，并增加 Live 重绘区域（容易造成抖动）。

## Proposed Future State

### A. 两段式渲染模型

- Stable source：所有已完成 block 的源文本（以“行”切片，但切片边界来自 block map）。
- Live source：最后一个未完成 block 的源文本。

渲染策略：

- Stable：把“新增的 stable 源文本片段”渲染后，追加打印到 `console`（scrollback）。
- Live：把 live 源文本渲染为 renderable，并在 `Live`（建议使用 `CropAboveLive`）中反复 `update()`。

### B. 用 MarkdownIt(commonmark) 做 block 边界判定

按 Textual 的思路提取 token 的行映射信息（不接管渲染，仅用于分割）：

1. `tokens = MarkdownIt("commonmark").parse(full_text)`
2. 选出 `top_level = [t for t in tokens if t.level == 0 and t.map is not None]`
3. 若 `len(top_level) < 2`：`stable_line = 0`
4. 否则：`stable_line = top_level[-1].map[0]`（最后一个顶层 block 的起始行）
5. Stable = `lines[:stable_line]`，Live = `lines[stable_line:]`
6. 约束：`stable_line` 必须单调递增（避免回退造成“已打印内容”与逻辑状态不一致）。

### C. Live 区裁剪与显示

使用项目现有的 `src/klaude_code/ui/rich/live.py` 的 `CropAboveLive`：

- Live renderable 始终只显示底部区域（裁剪上方溢出）。
- 不再需要 `live_window` 的“按行保留固定高度”。

### D. Mark / margin / spinner

- `mark`：只在整条消息的“第一条非空渲染行”出现一次；当 stable_line > 0 后，Live 区不得重复出现 mark。
- `left_margin/right_margin`：继续以“有效宽度”渲染（`console.width - margins`），并在渲染后添加缩进。
- `spinner`：仅在 Live 区显示；`final=True` 时去掉 spinner 并 stop Live。

## Implementation Phases

### Phase 1 — 分块与状态机（M）

- 设计一个纯逻辑组件：给定 `full_text`，返回 `stable_line`。
- `stable_line` 必须单调递增；对 token.map 缺失/异常做降级。

Acceptance Criteria:

- 对段落、列表、引用、fenced code（未闭合/闭合）等输入，stable_line 行为符合“最后一个 block 在 live”。

### Phase 2 — MarkdownStream 重写（L）

- 将 `MarkdownStream.update()` 改为：
  - 计算 stable/live 分界
  - 增量打印 stable 新增部分
  - Live 只渲染 live source 并更新
- 将 Live 实现切换为 `CropAboveLive`（或至少可配置）。

Acceptance Criteria:

- stable 区不会被重绘；Live 区只包含最后一个 block。
- `final=True` 后 Live stop，输出落盘一致。

### Phase 3 — 渲染一致性与帧捕获测试（L）

- 新增测试用的“帧捕获”机制：每次 update 产出可比较的 ANSI（或 Text）输出。
- 核心断言：对每一帧 `text_i`：
  - `render(full=text_i)` 与 `stable_accumulated + live_frame_i` 在 ANSI 文本层面等价（允许 spinner 差异，通过标准化移除）。
  - stable_accumulated 只允许 append，不允许修改历史部分。

Acceptance Criteria:

- pytest 中用多组 chunk 输入验证一致性。

### Phase 4 — 抖动/重绘区域验证（Optional, XL）

- 通过 ANSI 回放（例如 pyte）统计每帧屏幕差异行数，验证重绘集中在底部 Live 区。

Acceptance Criteria:

- diff 行数的分布明显集中在尾部区域；历史区域保持稳定。

## Detailed Tasks

1. 调研现有调用点与生命周期（S）
   - 确认 `MarkdownStream.update()` 的调用频率与 `final=True` 语义。
   - Acceptance: 不改动上层协议，仅替换内部实现。

2. 引入 `markdown-it-py` 作为直接依赖（S）
   - `uv add markdown-it-py`
   - Acceptance: 项目可导入 `from markdown_it import MarkdownIt`。

3. 实现 `stable_line` 计算器（M）
   - 独立函数，易测。
   - Acceptance: 覆盖主要 Markdown 结构，stable_line 单调。

4. 重写 `MarkdownStream` 的打印/重绘管线（L）
   - Stable 增量打印、Live 重绘。
   - Acceptance: 手工运行 REPL 流式输出时无明显闪烁，代码块闭合不乱跳。

5. 测试：分块逻辑（M）
   - 按 chunk 驱动稳定边界。
   - Acceptance: 全通过。

6. 测试：帧一致性（L）
   - 捕获每次 update 的“stable 增量 + live frame”。
   - Acceptance: 全通过。

7. 性能与节流（M）
   - 保留现有的“最小刷新间隔”或改为更简单的节流策略。
   - Acceptance: 高频 chunk 输入下 CPU 不飙升，刷新不掉帧。

## Risk Assessment & Mitigation

- Risk: `token.map` 缺失或不可靠（某些 token 类型 / 输入态）。
  - Mitigation: 若无法得到顶层 map，回退到保守策略：`stable_line = 0`（全部在 Live），保证正确性优先。

- Risk: commonmark 分块与 Rich Markdown 的渲染语义不完全一致。
  - Mitigation: MarkdownIt 只用于“边界”，不用于渲染；并用帧一致性测试兜底。

- Risk: mark/spinner 在 stable/live 之间重复或丢失。
  - Mitigation: 明确规则：mark 只在 start_line==0 的第一次非空渲染行出现；spinner 只在 Live。

## Success Metrics

- 视觉：历史内容不抖动；只在 Live 尾部变化。
- 正确性：中间帧渲染与全量渲染等价（按 ANSI 文本比较）。
- 维护性：`MarkdownStream` 代码结构清晰，解析/渲染职责分离。

## Required Resources / Dependencies

- Python package: `markdown-it-py`
- 测试：`pytest`（已存在）
- Optional：`pyte`（如需 ANSI 回放测试）
