Last Updated: 2026-01-01

# Context — Message + Part Refactor

## Decisions (confirmed)

1. Tool results use typed `ToolResultMessage` fields (not a generic dict).
2. Session persists `HistoryEvent` so resume can replay errors/metadata.
3. Thinking uses two parts: `ThinkingTextPart` + `ThinkingSignaturePart`.
4. Do not persist streaming deltas or tool-call-start signals in history.
5. Turn-level response metadata (usage / stop reason) lives on `AssistantMessage` (step-style).
6. Interrupt is derived from message fields (not persisted as a standalone event):
   - `AssistantMessage.stop_reason == "aborted"`.
   - `ToolResultMessage.status == "aborted"`.
   - `"aborted"` is reserved strictly for user interrupt/task cancellation; tool failures/timeouts are `"error"`.
   - If an interrupt happens locally, force `AssistantMessage.stop_reason = "aborted"`.
7. Provider input always degrades `DeveloperMessage` by attaching it to the preceding `user` or `tool` message.
8. Tool results keep a primary joined text representation (`output_text`), and tool message parts are strictly non-text.
9. System messages are persisted.

## Current architecture touchpoints

### Protocol models

- `src/klaude_code/protocol/model.py`
  - Currently defines `ConversationItem` and item subtypes.
  - Will become home for `Part`, `Message`, and `HistoryEvent`.
- `src/klaude_code/protocol/llm_param.py`
  - `LLMCallParameter.input` currently `list[ConversationItem]`.
  - Should become `list[Message]`.

### Turn execution

- `src/klaude_code/core/turn.py`
  - Consumes LLM client stream (currently yields `ConversationItem`).
  - Aggregates into `TurnResult` and persists reasoning/assistant/tool call items.
  - Will need to:
    - Persist a final assistant message containing ordered parts
    - Persist `usage` and `stop_reason` on the assistant message (instead of a separate metadata event)
    - Extract tool calls from parts for tool execution
    - Persist tool results as `ToolResultMessage` events

Interrupt handling note:

- Current UI replay expects an `events.InterruptEvent` (see `src/klaude_code/ui/modes/repl/renderer.py:149`).
- New design derives that event from `AssistantMessage.stop_reason == "aborted"` and/or `ToolResultMessage.status == "aborted"`.

### Tool execution

- `src/klaude_code/core/tool/tool_runner.py`
  - `run_tool()` returns `ToolResultItem` and persists it.
  - Should switch to persisting `ToolResultMessage`.

### Provider adapters (input)

- `src/klaude_code/llm/openai_compatible/input.py`
- `src/klaude_code/llm/openrouter/input.py`
- `src/klaude_code/llm/anthropic/input.py`
- `src/klaude_code/llm/google/input.py`
- `src/klaude_code/llm/responses/input.py`

These currently depend on `src/klaude_code/llm/input_common.py` grouping logic (`parse_message_groups`). Target state removes that dependency by iterating canonical messages.

Developer message rule:

- Persist `DeveloperMessage` for replay/UI.
- For provider input building, always append developer text/images onto the most recent `user` or `tool` message.

### Provider adapters (output)

- `src/klaude_code/llm/openai_compatible/stream.py` (shared streaming parser)
- `src/klaude_code/llm/anthropic/client.py`
- `src/klaude_code/llm/google/client.py`
- `src/klaude_code/llm/responses/client.py`
- `src/klaude_code/llm/openrouter/client.py` and `src/klaude_code/llm/openrouter/reasoning.py`

These will be responsible for building internal messages/parts.

### Session persistence and replay

- `src/klaude_code/session/codec.py` builds a registry from `ConversationItem` union.
  - Must be rewritten to support `HistoryEvent`.
- `src/klaude_code/session/session.py`:
  - Caches `messages_count` / `user_messages` by scanning item types.
  - `get_history_item()` reconstructs UI events by `isinstance` checks.
  - Must be rewritten to use message roles and part types.

Notes:

- Streaming deltas and tool-call-start signals are runtime-only UI events.
- Persisted history focuses on final messages and replayable error/task metadata.
- Interrupt is replayed as an event but stored as `AssistantMessage.stop_reason` and/or `ToolResultMessage.status`.

## Replay derivation (history -> UI events)

Goal: `src/klaude_code/session/session.py` must emit `events.ReplayEventUnion` in a shape that `src/klaude_code/ui/modes/repl/renderer.py:149` can replay.

Persisted input:

- Ordered `HistoryEvent` list (messages + error/task-metadata events).

Derived output (during replay):

- `events.UserMessageEvent` from each `UserMessage`.
- `events.DeveloperMessageEvent` from each `DeveloperMessage`.
- `events.AssistantMessageEvent` from `AssistantMessage` by concatenating all `TextPart.text` in-order.
- `events.AssistantImageDeltaEvent` from each `ImageFilePart` (replay should display saved images).
- `events.ToolCallEvent` from each `ToolCallPart` (arguments are `arguments_json`).
- `events.ToolResultEvent` from each `ToolResultMessage`:
  - `result` is `ToolResultMessage.output_text`
  - `ui_extra` and `status` are mapped from the typed fields

ToolResultEvent status compatibility:

- UI protocol keeps `ToolResultEvent.status` as `"success"|"error"` (no change to `src/klaude_code/protocol/events.py`).
- Map `ToolResultMessage.status` as:
  - `"success" -> "success"`
  - `"error" -> "error"`
  - `"aborted" -> "error"` (and emit `events.InterruptEvent` after it)

Interrupt replay rule:

- If `AssistantMessage.stop_reason == "aborted"`, emit `events.InterruptEvent` at the end of that turn.
- If `ToolResultMessage.status == "aborted"`, also emit an `events.InterruptEvent` after the tool result.
- No standalone interrupt history event is persisted.

Turn boundary events:

- `events.TurnStartEvent` should continue to be derived from message boundaries (not persisted).
- Replay should keep spacing behavior consistent with the current `Session.need_turn_start()` logic.

System messages:

- System messages are persisted for correctness, but are not rendered in the REPL replay by default.

## Runtime metadata event compatibility

We keep the existing runtime/internal protocol events unchanged (especially `ResponseMetadataEvent`).

- `ResponseMetadataEvent` remains part of `events.Event` (internal event; not displayed in UI replay).
- Since `usage` and `stop_reason` are stored on `AssistantMessage`, `ResponseMetadataEvent` is reconstructed from `AssistantMessage` at runtime.

Recommended reconstruction point:

- In `src/klaude_code/core/turn.py`, when a final `AssistantMessage` is produced for the turn, also emit an `events.ResponseMetadataEvent` whose `metadata` is built from the assistant message.

Alternative reconstruction point:

- In `src/klaude_code/core/task.py`, detect the per-turn assistant message (or a turn result structure) and synthesize `ResponseMetadataEvent` there.

### Export

- `src/klaude_code/session/export.py` renders HTML transcript based on item type checks.
  - Will need a new rendering strategy: message role -> render parts, plus history events.

## Mapping notes by provider

### OpenAI-compatible / OpenRouter (Chat Completions)

- Internal `Message(role=user|developer|assistant|tool)` maps naturally to chat messages.
- `tool_call` part maps to `assistant.tool_calls[]`.
- Tool result maps to `role=tool` message with `tool_call_id`.
- Thinking:
  - OpenAI: can optionally be omitted from content; if preserved, use model-specific fields.
  - OpenRouter: map to `reasoning_details` where possible; otherwise degrade to `<thinking>` text.

- Usage / stop reason:
  - Capture provider usage fields (where available) and store on `AssistantMessage.usage`.
  - Map finish_reason / stop_reason into `AssistantMessage.stop_reason`.

- Developer messages:
  - Always degrade: append to the preceding user/tool message for provider input.

- Tool result text:
  - Use `ToolResultMessage.output_text` as the tool message content.
  - Ignore any text parts (they must not exist by schema).

### Anthropic

- `thinking_text` + `thinking_signature` pairs map to `thinking` blocks.
- `tool_call` part maps to `tool_use` blocks.
- Tool result message maps to `tool_result` blocks.

- Usage / stop reason:
  - Map message stop reason to `AssistantMessage.stop_reason`.
  - Map usage accounting to `AssistantMessage.usage`.

- Developer messages:
  - Always degrade by attaching to the preceding user/tool message.

- Tool result text:
  - Use `ToolResultMessage.output_text` inside the tool_result block.

### Google (Gemini)

- `tool_call` part maps to function_call.
- `thinking_signature` maps to thought_signature.

- Usage / stop reason:
  - Map usage metadata to `AssistantMessage.usage`.
  - Map candidate finish reason to `AssistantMessage.stop_reason`.

- Developer messages:
  - Always degrade by attaching to the preceding user/tool message.

- Tool result text:
  - Use `ToolResultMessage.output_text` when converting tool results to contents.

### OpenAI Responses API

- Expand messages/parts into a flat list:
  - user/developer/assistant messages -> `type=message`
  - tool_call parts -> `type=function_call`
  - tool result messages -> `type=function_call_output`
  - thinking parts -> `type=reasoning` (or equivalent)

- Usage / stop reason:
  - Map response usage into `AssistantMessage.usage`.
  - Map response status / stop info into `AssistantMessage.stop_reason`.

- Tool result text:
  - Use `ToolResultMessage.output_text` when expanding to `function_call_output`.

## Tool result text normalization

Even though `ToolResultMessage` may contain multiple parts, keep the current behavior:

- All tool text is joined into `ToolResultMessage.output_text`.
- Provider mapping and UI should prefer `output_text`.

Strictness rule:

- `ToolResultMessage.parts` must not contain any text parts.

## Testing impact

- `tests/test_model.py` currently validates grouping logic; it will be rewritten to validate message->provider mapping directly.
- `tests/test_codec.py` will switch from `ConversationItem` generators to `HistoryEvent` generators.
- `tests/test_tool_runner.py` will validate that tool execution persists `ToolResultMessage`.

## Constraints / Tooling

- Use `uv` for running: `uv run pytest`, `uv run pyright`, `uv run ruff check --fix .`, `uv run ruff format`.
