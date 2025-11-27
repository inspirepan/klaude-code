# Smart Truncation - Context Document

**Last Updated: 2025-11-25**

## Key Files

### Primary Files to Modify

| File | Purpose | Changes Needed |
|------|---------|----------------|
| `src/klaude_code/config/constants.py` | Configuration constants | Add TOOL_OUTPUT_DISPLAY_HEAD, TOOL_OUTPUT_DISPLAY_TAIL, TOOL_OUTPUT_TRUNCATION_DIR |
| `src/klaude_code/core/tool/truncation.py` | Truncation strategy | Add SmartTruncationStrategy, TruncationResult |
| `src/klaude_code/core/tool/tool_runner.py` | Tool execution | Pass tool name/id to truncation, handle TruncationResult |
| `src/klaude_code/protocol/model.py` | Data models | Add TruncationUIExtra, update ToolResultUIExtra |
| `src/klaude_code/ui/renderers/tools.py` | UI rendering | Add truncation info rendering |

### Reference Files

| File | Purpose |
|------|---------|
| `src/klaude_code/core/tool/tool_abc.py` | Tool abstract base class |
| `src/klaude_code/core/tool/tool_context.py` | Tool execution context |
| `src/klaude_code/protocol/events.py` | Event definitions (ToolResultEvent) |

## Key Decisions

### 1. Truncation Parameters

**Decision**: Use buffer strategy with fixed display limits

```python
TOOL_OUTPUT_MAX_LENGTH = 40000      # Trigger threshold
TOOL_OUTPUT_DISPLAY_HEAD = 10000    # Show first N chars
TOOL_OUTPUT_DISPLAY_TAIL = 10000    # Show last N chars
```

**Rationale**:
- Even outputs just over 40000 chars only show 20000 to model
- Prevents context bloat
- Forces model to actively seek needed details
- 10000 chars typically sufficient to understand structure

### 2. File Naming Convention

**Decision**: `{tool_name}-{call_id}-{timestamp}.txt`

**Example**: `Bash-call_abc123-1732521600.txt`

**Rationale**:
- `call_id` is unique per tool call
- Tool name helps identify content type
- Timestamp adds extra uniqueness guarantee

### 3. Truncation Message Format

**Key**: File info at BEGINNING so model won't miss it. Repeat context before last section.

```
[Output truncated: {N} chars hidden, full output saved to /tmp/klaude/{filename}. Use Read tool or rg to get details. Showing first {HEAD} and last {TAIL} chars below.]

[First 10000 chars]

... ({N} characters truncated) ...

[Last 10000 chars below]
[Last 10000 chars]
```

### 4. Error Handling Strategy

**Decision**: Graceful degradation

- If file write fails -> Fall back to simple truncation (head only)
- If directory creation fails -> Fall back to simple truncation
- Always return valid output to model

### 5. Temp File Cleanup

**Decision**: Rely on system /tmp auto-cleanup

- No active cleanup mechanism needed
- /tmp is typically cleaned on reboot or by system policies

## Dependencies

### Internal Dependencies

- `TruncationStrategy` ABC must remain compatible
- `ToolResultItem.ui_extra` field used for passing truncation info
- `ToolResultUIExtra` and `ToolResultUIExtraType` extended

### External Dependencies

- None (uses standard library only)

## Architecture Notes

### Data Flow

```
tool_runner.run_tool()
    ↓
SmartTruncationStrategy.truncate(output, tool_name, call_id)
    ↓
    ├── len(output) <= MAX_LENGTH → return TruncationResult(was_truncated=False)
    │
    └── len(output) > MAX_LENGTH
        ├── Save to /tmp/klaude/{tool_name}-{call_id}.txt
        ├── Create truncated output with head + tail + message
        └── return TruncationResult(was_truncated=True, saved_file_path=...)
    ↓
tool_runner sets ui_extra.truncation if was_truncated
    ↓
Event emitted with ui_extra
    ↓
UI renderer checks for truncation and displays info
```

### Interface Changes

#### truncation.py

```python
# New
@dataclass
class TruncationResult:
    output: str
    was_truncated: bool
    saved_file_path: str | None = None
    original_length: int = 0
    truncated_length: int = 0

class SmartTruncationStrategy(TruncationStrategy):
    def truncate(self, output: str, tool_name: str | None = None, 
                 call_id: str | None = None) -> TruncationResult: ...

# Updated
def truncate_tool_output(output: str, tool_name: str | None = None,
                         call_id: str | None = None) -> TruncationResult: ...
```

#### model.py

```python
# New
class TruncationUIExtra(BaseModel):
    saved_file_path: str
    original_length: int
    truncated_length: int

# Updated ToolResultUIExtraType
class ToolResultUIExtraType(str, Enum):
    # ... existing ...
    TRUNCATION = "truncation"

# Updated ToolResultUIExtra
class ToolResultUIExtra(BaseModel):
    # ... existing ...
    truncation: TruncationUIExtra | None = None
```

## Testing Notes

### Unit Tests Needed

1. `test_smart_truncation_no_truncate` - Output under limit
2. `test_smart_truncation_creates_file` - File created correctly
3. `test_smart_truncation_output_format` - Correct head/tail/message
4. `test_smart_truncation_file_write_failure` - Graceful fallback
5. `test_tool_runner_with_truncation` - Integration test

### Manual Testing

1. Run a command that produces > 40000 chars output (e.g., `cat large_file.txt`)
2. Verify file created in `/tmp/klaude/`
3. Verify model receives truncated output with guidance
4. Verify UI shows truncation info
