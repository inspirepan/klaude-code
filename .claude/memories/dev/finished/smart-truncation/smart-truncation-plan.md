# Smart Truncation Strategy Implementation Plan

**Last Updated: 2025-11-25**

## Executive Summary

实现一个智能截断策略，当工具输出超过阈值时：
1. 将完整输出保存到临时文件
2. 向模型展示前后部分内容，并提示中间被截断
3. 在 UI 中展示截断行为和文件保存位置

这将优化上下文使用效率，避免将过长内容一次性放入 context，同时保留模型获取完整信息的能力。

## Current State Analysis

### 现有架构

```
truncation.py
├── TruncationStrategy (ABC)
│   └── truncate(output: str) -> str
├── SimpleTruncationStrategy
│   └── 简单字符截断，只保留前 N 个字符
├── get_truncation_strategy() / set_truncation_strategy()
└── truncate_tool_output()

tool_runner.py
├── run_tool(tool_call, registry) -> ToolResultItem
└── 在返回结果前调用 truncate_tool_output()
```

### 当前限制

1. `SimpleTruncationStrategy` 只保留前 40000 字符，丢失后面的内容
2. 没有保存完整输出的机制
3. 没有向模型提示如何获取被截断的内容
4. UI 层没有展示截断信息

### 关键参数 (constants.py)

- `TOOL_OUTPUT_MAX_LENGTH = 40000` - 当前截断阈值

## Proposed Future State

### 设计决策

**参数策略**：采用缓冲策略
- **截断触发阈值**: `TOOL_OUTPUT_MAX_LENGTH = 40000` 字符
- **展示内容量**: `TOOL_OUTPUT_DISPLAY_HEAD = 10000` 字符 (前部)
- **展示内容量**: `TOOL_OUTPUT_DISPLAY_TAIL = 10000` 字符 (后部)
- **总展示量**: 20000 字符 << 40000 字符

**理由**：
- 即使输出刚好超过 40000，也只展示 20000，为模型处理留出余量
- 避免上下文膨胀，强制模型主动获取需要的细节
- 前后各 10000 字符通常足以理解输出的整体结构和关键信息

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        tool_runner.py                            │
│  run_tool() ─────► SmartTruncationStrategy.truncate()           │
│                              │                                   │
│                              ▼                                   │
│              ┌─────────────────────────────────┐                │
│              │ len(output) > MAX_LENGTH?       │                │
│              └───────────────┬─────────────────┘                │
│                     Yes      │      No                          │
│              ┌───────────────▼───────────────┐                  │
│              │                               │                  │
│   ┌──────────▼──────────┐     ┌──────────────▼────────────┐    │
│   │ 1. Save to tmp file │     │ Return original output    │    │
│   │ 2. Return truncated │     └───────────────────────────┘    │
│   │    with guidance    │                                       │
│   └─────────────────────┘                                       │
└─────────────────────────────────────────────────────────────────┘

Truncated Output Format:
┌─────────────────────────────────────────────────────────────────┐
│ [Output truncated: {N} chars hidden, full output saved to       │
│  /tmp/klaude/xxx.txt. Use Read tool or rg to get details.      │
│  Showing first {HEAD} and last {TAIL} chars below.]            │
│                                                                 │
│ [First 10000 chars of output]                                   │
│                                                                 │
│ ... ({N} characters truncated) ...                              │
│                                                                 │
│ [Last 10000 chars below]                                        │
│ [Last 10000 chars of output]                                    │
└─────────────────────────────────────────────────────────────────┘
```

## Implementation Phases

### Phase 1: Core Truncation Logic

修改 `truncation.py` 和相关常量

1. 添加新常量到 `constants.py`
2. 创建 `SmartTruncationStrategy` 类
3. 添加临时文件保存逻辑

### Phase 2: Tool Runner Integration

修改 `tool_runner.py` 传递必要的上下文

1. 修改 `truncate_tool_output` 接口，支持传入 tool_call_name 和 tool_call_id
2. 更新 `run_tool` 调用

### Phase 3: Protocol & Event Updates

修改 `events.py` 和 `model.py` 支持截断信息

1. 添加 `TruncationUIExtra` 类型
2. 更新 `ToolResultUIExtra` 支持截断信息

### Phase 4: UI Rendering

修改 `tools.py` 展示截断信息

1. 添加截断信息渲染函数
2. 在 tool result 渲染中集成

## Detailed Tasks

### Phase 1: Core Truncation Logic [Effort: M]

**Task 1.1: Add new constants**
- File: `src/klaude_code/config/constants.py`
- Add:
  ```python
  TOOL_OUTPUT_DISPLAY_HEAD = 10000
  TOOL_OUTPUT_DISPLAY_TAIL = 10000
  TOOL_OUTPUT_TRUNCATION_DIR = "/tmp/klaude"
  ```
- Acceptance: Constants accessible from truncation.py

**Task 1.2: Create SmartTruncationStrategy class**
- File: `src/klaude_code/core/tool/truncation.py`
- Implement:
  - `__init__(self, max_length, head_chars, tail_chars, truncation_dir)`
  - `truncate(self, output: str, tool_name: str | None, call_id: str | None) -> TruncationResult`
  - File saving logic with proper error handling
  - Directory creation if not exists
  - File naming: `{tool_name}-{call_id}-{timestamp}.txt`
- Acceptance: Can truncate and save files correctly

**Task 1.3: Define TruncationResult dataclass**
- File: `src/klaude_code/core/tool/truncation.py`
- Include:
  - `output: str` - truncated output for model
  - `was_truncated: bool`
  - `saved_file_path: str | None`
  - `original_length: int`
  - `truncated_length: int`
- Acceptance: All truncation metadata captured

### Phase 2: Tool Runner Integration [Effort: S]

**Task 2.1: Update truncate_tool_output signature**
- File: `src/klaude_code/core/tool/truncation.py`
- Change: `truncate_tool_output(output, tool_name, call_id) -> TruncationResult`
- Acceptance: New signature works with existing code

**Task 2.2: Update run_tool to use new truncation**
- File: `src/klaude_code/core/tool/tool_runner.py`
- Pass tool_call.name and tool_call.call_id to truncation
- Capture TruncationResult and set ui_extra on ToolResultItem
- Acceptance: ToolResultItem contains truncation info

### Phase 3: Protocol & Event Updates [Effort: S]

**Task 3.1: Add TruncationUIExtra to model.py**
- File: `src/klaude_code/protocol/model.py`
- Add:
  ```python
  class TruncationUIExtra(BaseModel):
      saved_file_path: str
      original_length: int
      truncated_length: int
  ```
- Acceptance: New model defined

**Task 3.2: Update ToolResultUIExtra**
- File: `src/klaude_code/protocol/model.py`
- Add `TRUNCATION = "truncation"` to ToolResultUIExtraType
- Add `truncation: TruncationUIExtra | None = None` to ToolResultUIExtra
- Acceptance: ToolResultUIExtra can hold truncation info

### Phase 4: UI Rendering [Effort: S]

**Task 4.1: Add truncation rendering function**
- File: `src/klaude_code/ui/renderers/tools.py`
- Implement `render_truncation_info(ui_extra: TruncationUIExtra) -> RenderableType`
- Show: file path, original size, truncated size
- Acceptance: Truncation info displayed nicely

**Task 4.2: Integrate into tool result rendering**
- File: `src/klaude_code/ui/renderers/tools.py` (or caller)
- Check for truncation ui_extra and render if present
- Acceptance: Users see truncation info in terminal

## Risk Assessment and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| /tmp/klaude 目录权限问题 | Medium | Low | 使用 os.makedirs with exist_ok, 捕获 PermissionError |
| 磁盘空间不足 | Low | Low | 捕获 IOError, 降级到简单截断 |
| 临时文件堆积 | Low | Medium | 考虑添加清理机制 (可作为后续优化) |
| 模型不理解截断提示 | Medium | Low | 提示信息清晰明确，包含具体文件路径和建议命令 |

## Success Metrics

1. **功能正确性**: 超过 40000 字符的输出正确保存到临时文件
2. **输出格式正确**: 模型收到前后各 10000 字符 + 截断提示
3. **UI 展示正确**: 用户能在终端看到截断信息和文件路径
4. **无回归**: 现有测试全部通过

## Required Resources and Dependencies

- 无外部依赖
- 使用标准库: `pathlib`, `os`
- 修改文件:
  - `src/klaude_code/config/constants.py`
  - `src/klaude_code/core/tool/truncation.py`
  - `src/klaude_code/core/tool/tool_runner.py`
  - `src/klaude_code/protocol/model.py`
  - `src/klaude_code/ui/renderers/tools.py`

## Design Decisions (Confirmed)

1. **Temp file cleanup**: Rely on system /tmp auto-cleanup, no active cleanup needed.

2. **File naming**: `{tool_name}-{call_id}-{timestamp}.txt` for uniqueness.

3. **Message language**: Use English for consistency with codebase.

4. **Truncation message position**: Place file info at the BEGINNING of output (not middle) so model won't miss it.
