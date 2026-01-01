Last Updated: 2026-01-01

# Message + Part Refactor Plan

## Executive Summary

This plan migrates klaude-code’s internal conversation representation from a flat `ConversationItem` union ("items") to a canonical `Message + Part` model, closer to most provider APIs (Chat Completions, Anthropic Messages, Gemini contents). Each provider adapter in `src/klaude_code/llm/*/input.py` converts internal messages to provider requests, and each `src/klaude_code/llm/*/client.py` converts provider responses back into internal messages.

Key decisions (confirmed):

1. Tool results are represented as a typed `ToolResultMessage` with dedicated fields (type-safe), not a generic meta dict.
2. Session persists a `HistoryEvent` stream (not only messages) to replay errors/metadata on resume.
3. Thinking is represented as two parts: `ThinkingTextPart` and `ThinkingSignaturePart` (signature/encrypted content), preserving ordering.
4. We do not persist streaming deltas or tool-call-start signals in history.
5. Turn-level response metadata (usage / stop reason) is stored on `AssistantMessage` (step-style).
   - `ResponseMetadataEvent` remains part of the runtime protocol and is reconstructed from `AssistantMessage` to keep existing pipelines working.
6. Interrupt is not a standalone history event:
   - `AssistantMessage.stop_reason == "aborted"` is the canonical interrupt marker.
   - Tool interruption is represented by `ToolResultMessage.status == "aborted"`.
   - Replay derives an `events.InterruptEvent` from these fields.
   - `"aborted"` is reserved strictly for user interrupt/task cancellation. Tool failures/timeouts are `"error"`.
   - When an interrupt happens locally (e.g. Ctrl+C), force `AssistantMessage.stop_reason = "aborted"` even if the provider did not report it.
7. Provider input always degrades `DeveloperMessage` by attaching it to the preceding `user` or `tool` message.
8. Tool results keep a primary joined text representation (current behavior):
   - `ToolResultMessage.output_text` is the single source of truth for tool text.
   - `ToolResultMessage.parts` is strictly non-text.
9. System messages are persisted to history.

Non-goals:

- Backward compatibility for on-disk sessions (we can break it).
- Maintaining the existing `MessageItem` / `ConversationItem` structure.

## Current State Analysis

### Current internal model

- `ConversationItem` is a wide union in `src/klaude_code/protocol/model.py`, mixing:
  - Message-like items: `UserMessageItem`, `AssistantMessageItem`, `DeveloperMessageItem`, `ToolCallItem`, `ToolResultItem`, reasoning items.
  - Event-like items: `StartItem`, `InterruptItem`, `StreamErrorItem`, `ResponseMetadataItem`, `TaskMetadataItem`, streaming deltas.

### Current provider input conversion

- Many providers require message grouping, so `src/klaude_code/llm/input_common.py` implements `parse_message_groups()` to aggregate flat items into `UserGroup/AssistantGroup/ToolGroup`.
- Provider-specific `llm/*/input.py` then turns groups into provider requests.

Pain points:

- Internal shape is "Responses-like", but most providers are "messages + parts".
- A lot of logic exists only to re-create message boundaries (grouping rules) that would be implicit in a message-first model.

### Current provider output conversion

- Provider clients emit many item types (assistant text, tool call items, reasoning items, metadata items), and `src/klaude_code/core/turn.py` aggregates them into a turn result.

## Proposed Future State

### Core canonical model

Introduce three layers:

1. `Part` (discriminated union by `type`)
2. `Message` (discriminated union by `role`)
3. `HistoryEvent` (discriminated union by `type`, includes `Message` plus non-message events)

### Final schema (draft for review)

This section defines the target internal schema precisely. It is intended to be the single source of truth for implementation.

#### Common fields

All messages share these fields:

- `id: str | None`
- `created_at: datetime`
- `response_id: str | None` (LLM response identifier when available)

All parts share:

- `type: str` (discriminator)

#### Part union

| Part | `type` | Fields | Notes |
|---|---|---|---|
| `TextPart` | `"text"` | `text: str` | May appear in `UserMessage`, `DeveloperMessage`, `AssistantMessage` |
| `ImageURLPart` | `"image_url"` | `url: str`, `id: str | None` | URL or data URL |
| `ImageFilePart` | `"image_file"` | `file_path: str`, `mime_type: str | None`, `byte_size: int | None`, `sha256: str | None` | Assistant-generated artifacts |
| `ThinkingTextPart` | `"thinking_text"` | `id: str | None`, `text: str`, `model_id: str | None` | Display uses only `text` |
| `ThinkingSignaturePart` | `"thinking_signature"` | `id: str | None`, `signature: str`, `model_id: str | None`, `format: str | None` | Pairs with the nearest preceding `ThinkingTextPart` by order |
| `ToolCallPart` | `"tool_call"` | `call_id: str`, `tool_name: str`, `arguments_json: str` | `arguments_json` is stored as raw JSON string |

Thinking pairing rule (confirmed):

- A `ThinkingSignaturePart` consumes the nearest preceding `ThinkingTextPart` in the same `AssistantMessage`.
- If there is no preceding `ThinkingTextPart`, keep the signature part but do not display it; provider mapping may degrade.

#### Message union

All messages contain `role: "system"|"developer"|"user"|"assistant"|"tool"`.

| Message | `role` | Fields | Notes |
|---|---|---|---|
| `SystemMessage` | `"system"` | `parts: list[TextPart]` | Persisted. Recommended restriction: only `TextPart` for portability |
| `DeveloperMessage` | `"developer"` | `parts: list[Part]`, plus UI-only fields (e.g. `command_output`, `at_files`, etc.) | Persisted for replay; provider input degrades it |
| `UserMessage` | `"user"` | `parts: list[Part]` | |
| `AssistantMessage` | `"assistant"` | `parts: list[Part]`, `usage: model.Usage | None`, `stop_reason: StopReason | None` | Exactly one assistant message per LLM call |
| `ToolResultMessage` | `"tool"` | `call_id: str`, `tool_name: str`, `status: ToolStatus`, `output_text: str`, `parts: list[Part]`, `ui_extra: ToolResultUIExtra | None`, `side_effects: list[ToolSideEffect] | None`, `task_metadata: TaskMetadata | None` | `parts` is strictly non-text (see below) |

StopReason (confirmed):

- `"stop" | "length" | "tool_use" | "error" | "aborted"`

ToolStatus (confirmed):

- `"success" | "error" | "aborted"`

UI protocol mapping note:

- Keep `events.ToolResultEvent.status` unchanged (`"success"|"error"`).
- When emitting/replaying tool results, map internal `"aborted"` to `events.ToolResultEvent.status == "error"` and emit a separate `events.InterruptEvent`.

Interrupt rules (confirmed):

- `AssistantMessage.stop_reason == "aborted"` is the canonical interrupt marker.
- `ToolResultMessage.status == "aborted"` is the tool cancellation marker.
- `"aborted"` is reserved strictly for user interrupt/task cancellation; tool failures/timeouts are `"error"`.
- If an interrupt happens locally (e.g. Ctrl+C), force `AssistantMessage.stop_reason = "aborted"` even if the provider did not report it.

Tool result text strictness (confirmed):

- `ToolResultMessage.parts` must not contain `TextPart`.
- All tool text is stored in `ToolResultMessage.output_text`.

#### HistoryEvent union

History is persisted as an ordered list of `HistoryEvent`.

Must include:

- All messages above (`SystemMessage`, `DeveloperMessage`, `UserMessage`, `AssistantMessage`, `ToolResultMessage`).
- Task-level metadata events needed for replay (e.g. existing `TaskMetadataItem`).
- Error events needed for replay (e.g. existing `StreamErrorItem`, or a dedicated `ErrorHistoryEvent`).

Must not include:

- Streaming deltas.
- Tool-call-start signals.
- Standalone interrupt events (derived during replay).
- `ResponseMetadataEvent` (runtime-only; derived from `AssistantMessage`).

### LLM boundary

- `LLMCallParameter.input` becomes `list[Message]` (not `HistoryEvent`).
- Provider adapters:
  - `llm/*/input.py`: `list[Message] -> provider request`
  - `llm/*/client.py`: provider stream -> `HistoryEvent` stream (final messages + errors/task metadata)

### Streaming and UI

Streaming signals are runtime-only (not persisted in session history):

- Assistant text deltas (for streaming render)
- Thinking deltas (for streaming render)
- Tool call start signals (for spinner/status)

On turn completion, persist final messages (assistant message + tool result messages) plus error/task metadata events.

### Developer messages and provider input

Persist `DeveloperMessage` in history for UI replay, but always degrade it for provider input:

- For provider request building, append developer text/images as parts to the most recent `user` or `tool` message.
- This preserves the current behavior from `llm/input_common.py` where developer items attach to previous user/tool groups.

Degrade rule (confirmed):

- All providers degrade `DeveloperMessage` by attaching it to the preceding `user`/`tool` message.
- Only `DeveloperMessage.parts` are used (text + images). UI-only fields are never sent to providers.

Recommended normalization:

- When degrading, append developer `TextPart.text` with a trailing newline (`"\n"`) to preserve the current readability behavior.

### System message persistence
We persist system messages:

- Store `SystemMessage` in `HistoryEvent`.
- Provider adapters may either:
  - Convert `SystemMessage` into provider-native system/instructions fields, or
  - Derive `LLMCallParameter.system` from persisted system messages.

## Implementation Phases

Effort legend: S (0.5–1d), M (1–2d), L (2–4d), XL (4d+)

### Phase 1 — Define new protocol models (M)

Tasks:

1. Add `Part` union and `Message` union in `src/klaude_code/protocol/model.py`.
   - Acceptance: pyright passes for new types; existing code compiles after stepwise updates.
2. Add `HistoryEvent` union (decision #2).
   - Acceptance: a minimal encoder/decoder can round-trip a message event and an error/interrupt event.
3. Add `ToolResultMessage` with typed fields (decision #1).
   - Acceptance: tool runner can construct it without using dict meta.
4. Add thinking parts (decision #3).
   - Acceptance: can represent (text, signature) pairs in-order.
5. Add `AssistantMessage.usage` and `AssistantMessage.stop_reason` (decision #5).
   - Acceptance: provider clients can set these fields; `ResponseMetadataEvent` is emitted by reconstructing a `ResponseMetadataItem` from `AssistantMessage` (not persisted).

### Phase 2 — Update task/turn boundary types (M)

Tasks:

1. Change `LLMCallParameter.input` to `list[Message]`.
   - Acceptance: all clients build payloads from messages.
2. Update `core/turn.py` to consume `HistoryEvent` stream from clients but build `TurnResult` primarily from final assistant message + tool calls extracted from parts.
   - Acceptance: turn can execute tools based on `tool_call` parts.
3. Update replay derivation rules for interrupt:
   - Acceptance: when `AssistantMessage.stop_reason == "aborted"` (or a tool message has `status == "aborted"`), replay emits an `events.InterruptEvent` at the correct point.

### Phase 3 — Provider input adapters (M–L)

Tasks:

1. Rewrite `llm/openai_compatible/input.py` to iterate messages and convert parts.
   - Acceptance: no dependency on `parse_message_groups()`.
2. Rewrite `llm/openrouter/input.py` similarly (with cache_control and reasoning_details mapping).
3. Rewrite `llm/anthropic/input.py` to map parts to Anthropic blocks:
   - `thinking_text` + `thinking_signature` -> thinking blocks
   - `tool_call` -> tool_use blocks
   - tool result messages -> tool_result blocks
4. Rewrite `llm/google/input.py` to map to `types.Content` parts + function calls.
5. Rewrite `llm/responses/input.py` by expanding messages/parts into Responses input items.

Acceptance:

- Developer messages are always appended to the most recent user/tool message for provider input.

### Phase 4 — Provider output adapters (L)

Tasks:

1. OpenAI-compatible stream processing:
   - Update `llm/openai_compatible/stream.py` to accumulate parts (thinking deltas -> thinking parts, tool calls -> tool_call parts, assistant text -> text parts, images -> image_file parts).
   - Emit streaming delta events for UI, but persist final assistant message as one `AssistantMessage` with parts.
2. Anthropic streaming:
   - Emit thinking deltas and assistant deltas; produce final assistant message with parts.
   - Convert tool_use blocks to tool_call parts.
3. Google streaming:
   - Convert thought + thought_signature to thinking parts.
   - Convert function calls to tool_call parts.
4. Responses streaming:
   - Convert output items into assistant message parts and tool_call parts.
5. Ensure per-turn response metadata is stored on `AssistantMessage` (`usage` + `stop_reason`), not as a standalone history event.

Acceptance:

- `ToolResultMessage.output_text` matches the joined text representation used by UI/provider mapping.

Acceptance:

- Running a full turn yields:
  - one persisted assistant message (parts + usage + stop_reason)
  - zero or more tool call parts
  - optional error/task metadata events

### Phase 5 — Tool execution + persistence (M)

Tasks:

1. Update `ToolABC` contract:
   - Prefer keeping tool implementations returning a structured result payload that tool runner wraps into `ToolResultMessage`.
2. Update `core/tool/tool_runner.py`:
   - Inputs: tool_call part data
   - Outputs: `ToolResultMessage` history event persisted in session
3. Update `core/tool/tool_context` and side effects propagation to read from `ToolResultMessage` fields.

### Phase 6 — Session codec, replay, export, commands (L)

Tasks:

1. Update `session/codec.py` to encode/decode `HistoryEvent`.
2. Update `session/session.py`:
   - Store `history: list[HistoryEvent]`
   - Reconstruct UI events from messages/parts and metadata/error events.
3. Update `session/export.py` to render messages and tool results based on parts.
4. Update `command/fork_session_cmd.py` to find fork points based on user messages.

### Phase 7 — Remove old grouping logic + fix tests (M–L)

Tasks:

1. Delete or deprecate `llm/input_common.parse_message_groups()` and its tests.
2. Rewrite tests to operate on Message/Part:
   - codec round-trip
   - provider input adapters
   - tool runner
   - session replay/export

## Risk Assessment & Mitigations

### Risk: streaming ordering bugs

- Thinking/tool_calls/assistant text can interleave in provider streams.
- Mitigation:
  - Represent everything as ordered parts in a single assistant message.
  - Keep delta events separate for UI; do not attempt to persist deltas.

### Risk: image representation mismatch

- User images are URLs/data URLs; assistant images are files.
- Mitigation:
  - Use two image part variants: `image_url` and `image_file`.
  - Keep conversion helpers in one place.

### Risk: tool result UX regressions

- Current UI relies on `ui_extra` and side effects.
- Mitigation:
  - Keep them as typed fields on `ToolResultMessage` (decision #1).

## Success Metrics

- `llm/input_common.py` grouping logic is no longer required for any provider.
- Provider adapters are strictly "Message <-> provider" with no item aggregation layer.
- CLI can run a full multi-turn tool loop (tool calls + results) without errors.
- `uv run pytest` and `uv run pyright` pass.

## Dependencies / Prerequisites

- Python 3.13+, Pydantic models, strict pyright.
- Keep changes minimal and consistent with existing style.
- Use `uv` for any tooling commands.
