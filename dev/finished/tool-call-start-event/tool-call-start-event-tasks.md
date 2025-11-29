# Tool Call Start Event - Task Checklist

Last Updated: 2025-11-29

## Phase 1: Model Layer Changes

- [ ] **1.1** Add `ToolCallStartItem` to `model.py`
  - Fields: `response_id: str | None`, `call_id: str`, `name: str`
  - Add to `ConversationItem` union type
  - DO NOT add to session.py `_TypeMap` (not persisted)

## Phase 2: LLM Client Updates

- [ ] **2.1** Update Anthropic Client (`llm/anthropic/client.py`)
  - In `BetaRawContentBlockStartEvent` for `BetaToolUseBlock`
  - Yield `ToolCallStartItem(response_id=response_id, call_id=block.id, name=block.name)`
  - Before existing logic that sets `current_tool_name`, etc.

- [ ] **2.2** Update OpenAI Compatible Client (`llm/openai_compatible/client.py`)
  - Track emitted start events by index: `emitted_tool_start_indices: set[int]`
  - When `delta.tool_calls` has chunk with new index not in set AND has name:
    - Yield `ToolCallStartItem`
    - Add index to set

- [ ] **2.3** Update OpenRouter Client (`llm/openrouter/client.py`)
  - Same logic as 2.2

- [ ] **2.4** Update Responses Client (`llm/responses/client.py`)
  - Add case for `responses.ResponseOutputItemAddedEvent`
  - When `event.item` is `ResponseFunctionToolCall`:
    - Yield `ToolCallStartItem(response_id=response_id, call_id=item.call_id, name=item.name)`

## Phase 3: Event Pipeline Integration

- [ ] **3.1** Update Turn Executor (`core/turn.py`)
  - Add case for `model.ToolCallStartItem` in stream processing (around line 180)
  - Yield `events.TurnToolCallStartEvent(session_id=ctx.session_id, response_id=item.response_id, tool_call_id=item.call_id, tool_name=item.name, arguments="")`
  - Do NOT append to history

## Phase 4: UI Event Handler

- [ ] **4.1** Implement `_on_tool_call_start` handler (`ui/modes/repl/event_handler.py`)
  - Replace `pass` with handler method call
  - Method: `self.renderer.spinner_update(f"Calling {event.tool_name} ...")`
  - Check `is_sub_agent_session` first to skip sub-agent sessions

- [ ] **4.2** Update `_on_turn_start` to reset spinner text
  - After `display_turn_start`, call `self.renderer.spinner_update("Thinking ...")`
  - Or use active todo if available (optional enhancement)

## Phase 5: Verification

- [ ] **5.1** Run type checker
  - `uv run pyright`

- [ ] **5.2** Run tests
  - `uv run pytest`

- [ ] **5.3** Manual testing
  - Test with Anthropic model
  - Test with OpenAI model
  - Test with OpenRouter model (if available)
  - Verify spinner shows "Calling {ToolName} ..." before tool execution
  - Verify spinner resets on new turn

## Notes

- ToolCallStartItem is for streaming feedback only, not persisted
- TurnToolCallStartEvent already defined, just needs to be emitted
- Be careful with sub-agent sessions (should skip spinner updates)
