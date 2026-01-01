Last Updated: 2026-01-01

# Tasks — Message + Part Refactor

## Phase 1 — Protocol models

- [ ] (M) Define `Part` union (`text`, `image_url`, `image_file`, `thinking_text`, `thinking_signature`, `tool_call`).
  - Acceptance: parts are discriminated and JSON-serializable.
- [ ] (M) Define `Message` union by role (`system`, `developer`, `user`, `assistant`, `tool`).
  - Acceptance: each message validates with strict pyright.
- [ ] (M) Define `HistoryEvent` union containing `Message` plus non-message events needed for replay.
  - Acceptance: encoder/decoder can round-trip at least one message and one non-message event (e.g. interrupt/error/task metadata).
- [ ] (S) Define `ToolResultMessage` with typed fields (`ui_extra`, `side_effects`, `task_metadata`).
  - Acceptance: tool runner can populate without dict hacks.
- [ ] (S) Add `AssistantMessage.usage` and `AssistantMessage.stop_reason` (step-style per-turn metadata).
  - Acceptance: provider clients can set usage/stop reason; `ResponseMetadataEvent` is reconstructed from `AssistantMessage` at runtime (not persisted).
- [ ] (S) Define interrupt derivation rule:
  - `AssistantMessage.stop_reason == "aborted"` implies replayed interrupt.
  - `ToolResultMessage.status == "aborted"` implies replayed interrupt.
  - Reserve `"aborted"` for user interrupt/task cancellation only.
  - Force `AssistantMessage.stop_reason = "aborted"` on local interrupt.
  - Acceptance: replay still emits an interrupt UI event without persisting an interrupt history event.
- [ ] (S) Add `ToolResultMessage.output_text` (joined tool text) normalization rule.
  - Acceptance: UI/provider mapping uses `output_text` as primary.
- [ ] (S) Enforce strict tool message parts: `ToolResultMessage.parts` contains non-text parts only.
  - Acceptance: all tool text lives in `output_text`.

- [ ] (S) Keep UI protocol unchanged for tool status.
  - Acceptance: `events.ToolResultEvent.status` remains `"success"|"error"`; internal `"aborted"` is represented as `"error"` + `events.InterruptEvent`.

## Phase 1.5 — System message persistence

- [ ] (M) Persist system messages in `HistoryEvent` and define provider mapping.
  - Acceptance: resume/replay can reconstruct system context deterministically.

## Phase 2 — Core turn boundary

- [ ] (M) Change `LLMCallParameter.input` to `list[Message]`.
  - Acceptance: all LLM clients compile and can build payloads.
- [ ] (M) Update `core/turn.py` to extract tool calls from assistant message parts.
  - Acceptance: multi-tool turn still works.

## Phase 3 — Provider input adapters

- [ ] (M) Rewrite `llm/openai_compatible/input.py` to consume messages/parts (no grouping).
- [ ] (M) Rewrite `llm/openrouter/input.py` to consume messages/parts (no grouping).
- [ ] (M) Rewrite `llm/anthropic/input.py` to consume messages/parts.
- [ ] (M) Rewrite `llm/google/input.py` to consume messages/parts.
- [ ] (M) Rewrite `llm/responses/input.py` to expand messages/parts into Responses input.
- [ ] (S) Implement developer message degradation rule in all input adapters.
  - Acceptance: developer messages are appended to the preceding user/tool message.

## Phase 4 — Provider output adapters

- [ ] (L) Refactor `llm/openai_compatible/stream.py` to accumulate parts and emit final assistant message (including usage/stop_reason).
- [ ] (M) Refactor `llm/anthropic/client.py` to output messages/parts.
- [ ] (M) Refactor `llm/google/client.py` to output messages/parts.
- [ ] (M) Refactor `llm/responses/client.py` to output messages/parts.
- [ ] (M) Refactor OpenRouter reasoning handling to output thinking parts.
- [ ] (M) Ensure all providers map per-turn usage and stop reason onto `AssistantMessage`.

## Phase 5 — Tool execution + persistence

- [ ] (M) Update tool runner to persist `ToolResultMessage` events.
- [ ] (S) Update side effects and todo propagation to read from `ToolResultMessage`.

## Phase 6 — Session + export

- [ ] (M) Rewrite `session/codec.py` for `HistoryEvent`.
- [ ] (L) Rewrite `session/session.py` replay logic from messages/parts.
- [ ] (L) Rewrite `session/export.py` transcript rendering from messages/parts.
- [ ] (M) Update fork/session commands relying on item type scanning.

## Phase 7 — Cleanup + tests

- [ ] (S) Remove/deprecate `llm/input_common.parse_message_groups`.
- [ ] (L) Update tests:
  - codec round-trip
  - provider payload mapping
  - tool runner
  - session replay/export
- [ ] (M) Run and fix: `uv run ruff check --fix .`, `uv run ruff format`, `uv run pyright`, `uv run pytest`.
