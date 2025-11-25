# Smart Truncation - Task Checklist

**Last Updated: 2025-11-25**

## Phase 1: Core Truncation Logic [Effort: M]

- [ ] **1.1** Add new constants to `constants.py`
  - [ ] Add `TOOL_OUTPUT_DISPLAY_HEAD = 10000`
  - [ ] Add `TOOL_OUTPUT_DISPLAY_TAIL = 10000`
  - [ ] Add `TOOL_OUTPUT_TRUNCATION_DIR = "/tmp/klaude"`
  
- [ ] **1.2** Define TruncationResult dataclass in `truncation.py`
  - [ ] Add `output: str`
  - [ ] Add `was_truncated: bool`
  - [ ] Add `saved_file_path: str | None`
  - [ ] Add `original_length: int`
  - [ ] Add `truncated_length: int`

- [ ] **1.3** Create SmartTruncationStrategy class in `truncation.py`
  - [ ] Implement `__init__` with configurable parameters
  - [ ] Implement file saving logic
  - [ ] Implement directory creation with error handling
  - [ ] Implement `truncate` method returning TruncationResult
  - [ ] Add graceful fallback for file write failures

- [ ] **1.4** Update default strategy and helper function
  - [ ] Change default to SmartTruncationStrategy
  - [ ] Update `truncate_tool_output` signature

## Phase 2: Tool Runner Integration [Effort: S]

- [ ] **2.1** Update `tool_runner.py`
  - [ ] Import TruncationResult
  - [ ] Pass tool_call.name and tool_call.call_id to truncation
  - [ ] Handle TruncationResult
  - [ ] Set ui_extra on ToolResultItem when truncated

## Phase 3: Protocol Updates [Effort: S]

- [ ] **3.1** Add TruncationUIExtra to `model.py`
  - [ ] Define TruncationUIExtra class with fields
  - [ ] Add TRUNCATION to ToolResultUIExtraType enum
  - [ ] Add truncation field to ToolResultUIExtra

## Phase 4: UI Rendering [Effort: S]

- [ ] **4.1** Add truncation rendering in `tools.py`
  - [ ] Import TruncationUIExtra
  - [ ] Implement `render_truncation_info` function
  - [ ] Style with appropriate theme keys

- [ ] **4.2** Integrate into tool result flow
  - [ ] Check for truncation ui_extra in result rendering
  - [ ] Display truncation info when present

## Phase 5: Testing & Verification

- [ ] **5.1** Manual testing
  - [ ] Test with output > 40000 chars
  - [ ] Verify file creation in /tmp/klaude/
  - [ ] Verify truncated output format
  - [ ] Verify UI display

- [ ] **5.2** Run existing tests
  - [ ] `uv run pytest` passes
  - [ ] `uv run pyright` passes

---

## Progress Tracking

| Phase | Status | Completed Tasks | Total Tasks |
|-------|--------|-----------------|-------------|
| Phase 1 | Not Started | 0 | 4 |
| Phase 2 | Not Started | 0 | 1 |
| Phase 3 | Not Started | 0 | 1 |
| Phase 4 | Not Started | 0 | 2 |
| Phase 5 | Not Started | 0 | 2 |

**Overall Progress**: 0 / 10 tasks completed
