# Tool Call Start Event Implementation Plan

Last Updated: 2025-11-29

## Executive Summary

Implement a `ToolCallStartItem` model item that signals when the LLM starts streaming a tool call (when the tool name is first known). This enables the UI to display "Calling XXX ..." in the spinner text, providing real-time feedback before the tool call is fully received and executed.

## Current State Analysis

### Existing Architecture

1. **LLM Protocol Layer** (`src/klaude_code/llm/`):
   - Anthropic: `BetaRawContentBlockStartEvent` with `BetaToolUseBlock` provides tool name at stream start
   - OpenAI Compatible: First chunk with `index` change contains `id` and `name`
   - OpenRouter: Same as OpenAI Compatible
   - Responses: `ResponseOutputItemAddedEvent` provides tool name at start

2. **Model Layer** (`src/klaude_code/protocol/model.py`):
   - `ToolCallItem`: Full tool call (name + arguments)
   - No `ToolCallStartItem` exists yet

3. **Event Layer** (`src/klaude_code/protocol/events.py`):
   - `TurnToolCallStartEvent` already exists but is not being emitted
   - Currently just `pass` in event handler

4. **Turn Executor** (`src/klaude_code/core/turn.py`):
   - Receives `model.ToolCallItem` from LLM client
   - Does not receive any "start" signal for tool calls

5. **Event Handler** (`src/klaude_code/ui/modes/repl/event_handler.py`):
   - `_on_todo_change`: Updates spinner text with active todo
   - `_on_turn_start`: Could reset spinner text
   - `TurnToolCallStartEvent` handler is empty (`pass`)

### Data Flow

```
LLM Stream -> LLM Client -> model.ConversationItem -> TurnExecutor -> events.Event -> UI EventHandler
```

## Proposed Solution

### Option A: Add ToolCallStartItem to model layer (Recommended)

Add a new `ToolCallStartItem` in `model.py` that LLM clients yield when they first receive tool name. This is cleaner and follows the existing pattern.

### Option B: Emit TurnToolCallStartEvent directly from turn.py

Less clean because it would require modifying TurnExecutor to understand partial tool call states.

**Decision: Option A** - Add `ToolCallStartItem` to maintain consistency with the model layer pattern.

## Implementation Phases

### Phase 1: Model Layer Changes

#### Task 1.1: Add ToolCallStartItem (Effort: S)
- Add `ToolCallStartItem` class to `model.py`
- Fields: `response_id`, `call_id`, `name`
- Add to `ConversationItem` union type
- **Acceptance Criteria**: Model compiles, type checks pass

### Phase 2: LLM Client Updates

#### Task 2.1: Update Anthropic Client (Effort: S)
- In `BetaRawContentBlockStartEvent` handler for `BetaToolUseBlock`
- Yield `ToolCallStartItem` with tool name and call_id
- **Acceptance Criteria**: Debug log shows ToolCallStartItem before ToolCallItem

#### Task 2.2: Update OpenAI Compatible Client (Effort: M)
- Detect when a new tool call starts (index change with name present)
- Yield `ToolCallStartItem` immediately
- Need to track which indices have already emitted start events
- **Acceptance Criteria**: Debug log shows ToolCallStartItem before ToolCallItem

#### Task 2.3: Update OpenRouter Client (Effort: M)
- Same logic as OpenAI Compatible
- **Acceptance Criteria**: Debug log shows ToolCallStartItem before ToolCallItem

#### Task 2.4: Update Responses Client (Effort: S)
- Handle `ResponseOutputItemAddedEvent` for function calls
- Yield `ToolCallStartItem` with tool name
- **Acceptance Criteria**: Debug log shows ToolCallStartItem before ToolCallItem

### Phase 3: Event Pipeline Integration

#### Task 3.1: Update Turn Executor (Effort: S)
- Handle `ToolCallStartItem` in the stream processing
- Yield `TurnToolCallStartEvent` (already defined)
- **Acceptance Criteria**: Event handler receives TurnToolCallStartEvent

### Phase 4: UI Event Handler

#### Task 4.1: Implement _on_tool_call_start Handler (Effort: S)
- Update spinner text to "Calling {tool_name} ..."
- **Acceptance Criteria**: Spinner shows tool name when streaming starts

#### Task 4.2: Reset Spinner on TurnStart (Effort: S)
- In `_on_turn_start`, reset spinner to "Thinking ..." or active todo
- Ensures previous "Calling XXX" is cleared for new turn
- **Acceptance Criteria**: Spinner resets properly between turns

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Model serialization break | Low | High | ToolCallStartItem not persisted to history |
| Stream ordering issues | Medium | Medium | Only yield start before first delta |
| Todo change overrides spinner | Low | Low | Todo change already handles this |

## Success Metrics

1. Spinner shows "Calling {ToolName} ..." within 100ms of tool call stream starting
2. No regression in existing tool call behavior
3. Type checks pass (`pyright`)
4. Existing tests pass

## Dependencies

- No external dependencies
- Internal: `model.py`, `events.py`, all LLM clients, `turn.py`, `event_handler.py`

## Notes

- `ToolCallStartItem` should NOT be persisted to conversation history (it's a transient stream signal)
- Consider whether to add to `_TypeMap` in session.py (probably not needed)
