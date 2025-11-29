# Tool Call Start Event - Context & Key Files

Last Updated: 2025-11-29

## Key Files

### Model Layer
- `src/klaude_code/protocol/model.py` - Add ToolCallStartItem here
- `src/klaude_code/protocol/events.py` - TurnToolCallStartEvent already exists (line 41-48)

### LLM Clients
- `src/klaude_code/llm/anthropic/client.py`
  - Line 144-151: `BetaRawContentBlockStartEvent` with `BetaToolUseBlock` - **EMIT HERE**
- `src/klaude_code/llm/openai_compatible/client.py`
  - Line 176-185: Tool call delta handling - detect new tool by index change with name
  - `BasicToolCallAccumulator` tracks tool calls by index
- `src/klaude_code/llm/openrouter/client.py`
  - Line 164-173: Same pattern as OpenAI Compatible
- `src/klaude_code/llm/responses/client.py`
  - Need to handle `ResponseOutputItemAddedEvent` for `ResponseFunctionToolCall`
  - Currently unhandled (logs "[Unhandled stream event]")

### Tool Call Accumulator
- `src/klaude_code/llm/openai_compatible/tool_call_accumulator.py`
  - `BasicToolCallAccumulator`: accumulates chunks, returns full ToolCallItem on get()
  - May need to emit start event when first chunk with new index arrives

### Core Layer
- `src/klaude_code/core/turn.py`
  - Line 180-181: `model.ToolCallItem` handling - add ToolCallStartItem handling here

### UI Layer
- `src/klaude_code/ui/modes/repl/event_handler.py`
  - Line 67-68: `TurnToolCallStartEvent` handler is `pass`
  - Line 178-183: `_on_todo_change` updates spinner
  - Line 115-117: `_on_turn_start` - could reset spinner here

## Stream Event Patterns by Protocol

### Anthropic Protocol
```
BetaRawContentBlockStartEvent(BetaToolUseBlock(name="Bash", id="xxx"))  <- EMIT START HERE
BetaRawContentBlockDeltaEvent(BetaInputJSONDelta(partial_json='{"com'))
BetaRawContentBlockDeltaEvent(BetaInputJSONDelta(partial_json='mand'))
BetaRawContentBlockDeltaEvent(BetaInputJSONDelta(partial_json='": "pwd"}'))
BetaRawContentBlockStopEvent  <- yield ToolCallItem
```

### OpenAI Compatible Protocol
```
chunk: index=0, id='xxx', name='Bash', arguments=''  <- EMIT START HERE (new index + name)
chunk: index=0, id=None, name=None, arguments='{"comm'
chunk: index=0, id=None, name=None, arguments='and": "'
chunk: index=0, id=None, name=None, arguments='pwd"}'
stream end  <- yield ToolCallItem
```

### Responses Protocol
```
ResponseOutputItemAddedEvent(ResponseFunctionToolCall(name="xxx", ...))  <- EMIT START HERE
ResponseFunctionCallArgumentsDeltaEvent(delta='{"comm')
ResponseFunctionCallArgumentsDeltaEvent(delta='and": "pwd"}')
ResponseOutputItemDoneEvent(ResponseFunctionToolCall(...))  <- yield ToolCallItem
```

## Key Decisions

1. **ToolCallStartItem NOT persisted**: This is a transient streaming signal, not part of conversation history
2. **TurnToolCallStartEvent already exists**: Just need to emit it from turn.py
3. **Spinner priority**: Tool call start should update spinner, but todo_change can override it

## Spinner Text State Flow

```
TaskStart -> "Thinking ..."
TurnStart -> Reset to "Thinking ..." or active todo
ToolCallStart -> "Calling {ToolName} ..."
TodoChange -> Update to active todo (if any)
ToolCallStart (next tool) -> "Calling {ToolName} ..."
TurnEnd -> Keep current
TurnStart (next turn) -> Reset
TaskFinish -> Stop spinner
```
