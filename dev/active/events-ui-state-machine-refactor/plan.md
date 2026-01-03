# Events + REPL State Machine Refactor Plan

Last Updated: 2026-01-03

## Executive Summary

This project will perform a breaking, “clean-slate” refactor of the protocol event system and the REPL UI state machine.

Goals:

- Introduce a hierarchical event class structure under `src/klaude_code/protocol/events/` (package, not a single file).
- Redesign streaming event boundaries to be explicit (`Start/Delta/End`) so UI never guesses stage boundaries.
- Replace the current REPL stage/stream handling (`StageManager` + ad-hoc buffering rules) with a simplified state machine that emits render commands.
- Preserve current sub-agent UX behavior: sub-agent sessions do not stream assistant text to the main output.
- Rename the “final assistant message” event from `AssistantMessageEvent` to `ResponseCompleteEvent` (new semantics: final snapshot event).
  - `ResponseCompleteEvent` includes `response_id` and `thinking_text`.

Spec lock:

- Canonical event spec is recorded in `dev/active/events-ui-state-machine-refactor/context.md`.

Non-goals:

- Backward compatibility with existing event names/fields.
- Implementing `ToolCallDelta` streaming for tool arguments.

## Current State Analysis

### Events

Current events are defined in `src/klaude_code/protocol/events.py` as a collection of unrelated `BaseModel` classes plus union types.

Issues:

- No shared base event type; many events share fields (`session_id`, `response_id`) but not consistently.
- Streaming boundaries are implicit: UI infers when thinking/text “starts/ends” based on heuristics.
- There is overlap in stage/state handling across layers:
  - LLM parsing maintains internal stream stage (`openai_compatible/stream.py`).
  - Turn layer emits deltas and final message without explicit `Start/End`.
  - UI stage manager handles finalize logic (thinking/assistant) and must guess boundaries.

### REPL UI

Current REPL display pipeline:

- `DisplayEventHandler` handles protocol events, buffers thinking/assistant markdown streams, updates spinner state, and uses `StageManager` for lifecycle transitions.
- Stage transitions are partly inferred (e.g. empty deltas), which creates fragility.

Sub-agent behavior is partially special-cased:

- Sub-agent sessions generally do not stream assistant text; some sub-agent thinking is reduced to a header.
- Styling and quote behavior is managed per-session by `REPLRenderer.session_map`.

## Proposed Future State

### 1) Protocol Events Package

Move from a flat `events.py` to a package with explicit categorization:

- `src/klaude_code/protocol/events/base.py`
- `src/klaude_code/protocol/events/lifecycle.py`
- `src/klaude_code/protocol/events/streaming.py`
- `src/klaude_code/protocol/events/tools.py`
- `src/klaude_code/protocol/events/metadata.py`
- `src/klaude_code/protocol/events/system.py`
- `src/klaude_code/protocol/events/chat.py`
- `src/klaude_code/protocol/events/__init__.py` (re-export public API)

Key event boundary design:

- Thinking: `ThinkingStartEvent` / `ThinkingDeltaEvent` / `ThinkingEndEvent`
- Assistant text: `AssistantTextStartEvent` / `AssistantTextDeltaEvent` / `AssistantTextEndEvent`
- Images: `AssistantImageDeltaEvent`
- Tool start signal (name only): `ToolCallStartEvent` (no ToolCallDelta)
- Final snapshot: `ResponseCompleteEvent` (replaces `AssistantMessageEvent`)

Constraints:

- All events carry `session_id`.
- Streaming “End” events are pure boundaries (do not require content).
- `ResponseCompleteEvent` is the canonical final snapshot for replay and external consumers.

### 2) Turn Event Emission

Update `TurnExecutor` so it:

- Emits `ThinkingStartEvent` on first thinking delta; emits `ThinkingEndEvent` on leaving thinking stage.
- Emits `AssistantTextStartEvent` on first assistant text delta; emits `AssistantTextEndEvent` when model response ends or when tools begin.
- Emits `ToolCallStartEvent` from LLM `ToolCallStartItem` (name + id).
- Emits `ResponseCompleteEvent` when final `message.AssistantMessage` arrives.
- Emits `UsageEvent` (replacement for `ResponseMetadataEvent`) when usage is available.

This removes UI heuristics and makes UI a deterministic state machine.

### 3) REPL UI Simplified State Machine

Replace current `StageManager` usage with:

- `ui/state/display_state.py`: `DisplayState` enum (IDLE/THINKING/STREAMING_TEXT/TOOL_EXECUTING/ERROR)
- `ui/state/state_machine.py`: `DisplayStateMachine.transition(event) -> list[RenderCommand]`
- `ui/renderer/command_renderer.py`: executes render commands against `REPLRenderer`

Sub-agent handling:

- Maintain a per-session machine table keyed by `session_id`.
- Main session uses full markdown streaming.
- Sub-agent sessions do not stream assistant text (preserve current behavior).

## Implementation Phases

### Phase 0: Spec Lock-in (S)

- Finalize event names, fields, and invariants.
- Decide how `EndEvent` uses `session_id` (locked: use sentinel `"__app__"` for global shutdown).

Acceptance criteria:

- A written spec in `dev/active/events-ui-state-machine-refactor/context.md`.

### Phase 1: Protocol Events Package (L)

- Create new `protocol/events/` package and move all event models into categorized modules.
- Provide a clean public surface via `protocol/events/__init__.py`.
- Replace `AssistantMessageEvent` with `ResponseCompleteEvent`.
- Update `protocol/__init__.py` re-export if needed.

Acceptance criteria:

- `uv run pyright` passes.
- No remaining imports from `klaude_code.protocol.events.py` (file removed).

### Phase 2: Core Emission Updates (L)

- Update `TurnExecutor` to emit explicit `Start/End` boundaries.
- Update `TaskExecutor` to type-match on new event classes (rename `ResponseMetadataEvent` -> `UsageEvent`, etc.).
- Ensure cancellation persists partial assistant text as before.

Acceptance criteria:

- Streaming runs without UI boundary heuristics.
- Cancellation still persists partial assistant output.

### Phase 3: Session Replay Updates (M)

- Update `Session.get_history_item()` to emit the new event types for replay.
- Ensure replay produces `ResponseCompleteEvent` (snapshot), and uses `Thinking*` boundaries if required.

Acceptance criteria:

- REPL replay output remains correct.
- Tests covering replay and sub-agent replay continue to pass (or are updated).

### Phase 4: REPL State Machine Rewrite (XL)

- Introduce `DisplayController` (routes events by `session_id`).
- Implement `DisplayStateMachine` (per session) producing `RenderCommand`s.
- Implement `CommandRenderer` and adapt `REPLRenderer` usage.
- Remove `StageManager` and old stage transitions.
- Preserve sub-agent suppression of assistant text streaming.

Acceptance criteria:

- No `StageManager` usage in REPL.
- Main session: thinking and assistant markdown stream correctly; tool calls/results render correctly.
- Sub-agent: no assistant text streaming; minimal signals (thinking header if configured, errors).

### Phase 5: Other Displays + Tests (M)

- Update `ExecDisplay`, `StreamJsonDisplay`, and `DebugEventDisplay` for renamed events.
- Update tests that reference old event classes.

Acceptance criteria:

- `uv run pytest` passes.

### Phase 6: Cleanup + Tooling Validation (S)

- Remove dead code paths.
- Run `uv run ruff format` and `uv run ruff check --fix .`.
- Run `uv run pyright` and `uv run pytest`.

Acceptance criteria:

- Repo is green on formatting, type checks, and tests.

## Detailed Tasks (with Acceptance Criteria)

See `dev/active/events-ui-state-machine-refactor/tasks.md`.

## Risk Assessment & Mitigations

### Risk: Mixed-session interleaving breaks UI streaming

Mitigation:

- Use per-session machines and a controller router.
- Only allow main session to own the live markdown streaming area.

### Risk: Boundary events emitted inconsistently across providers

Mitigation:

- Emit boundaries in `TurnExecutor` based on observed `message.*Delta` items, not on provider-specific internals.
- Keep LLM parsing free to evolve; it only needs to output deltas + final `AssistantMessage`.

### Risk: Replay differs from live

Mitigation:

- Define `ResponseCompleteEvent` as the canonical snapshot.
- Keep replay rendering based primarily on snapshot events.

## Success Metrics

- REPL event handler complexity reduced (fewer mutable states, no heuristic transitions).
- No duplicated stage machines across layers (UI does not infer boundaries).
- Sub-agent UI behavior preserved.
- Tests and type checks pass.

## Resources / Dependencies

- Requires coordinated edits across: protocol events, core turn/task, session replay, UI repl.
- Validation commands:
  - `uv run ruff format`
  - `uv run ruff check --fix .`
  - `uv run pyright`
  - `uv run pytest`