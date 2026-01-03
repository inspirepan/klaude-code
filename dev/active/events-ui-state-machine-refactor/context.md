# Context: Events + REPL State Machine Refactor

Last Updated: 2026-01-03

This file is the single source of truth for the “clean-slate” design decisions.

The next implementation session can rely on this file after clearing chat context.

## Scope

Breaking refactor of:

- Protocol event definitions (replace `src/klaude_code/protocol/events.py` with a hierarchical package).
- Core event emission semantics (explicit streaming boundaries, no UI heuristics).
- REPL UI implementation (simplified state machine + render commands).

No compatibility guarantees.

## Locked Decisions (Complete List)

### A) Streaming tool calls

- No `ToolCallDelta`.
- Tool call streaming only emits a start signal containing tool name (and tool call id when available).
- Tool arguments are not streamed.

### B) `session_id` on all events

- Every protocol event model includes `session_id: str`.
- A global shutdown signal uses a sentinel session id:
  - `EndEvent.session_id == "__app__"`

### C) Sub-agent UI behavior

- Preserve existing behavior:
  - Sub-agent sessions do not stream assistant text output to the main terminal.
  - Sub-agent thinking may be reduced to a header (current behavior for e.g. ImageGen).
- Sub-agents may run concurrently and their events will interleave on a shared event queue.
- REPL UI must therefore maintain a per-session state table keyed by `session_id`.

### D) Final response event rename and semantics

- Rename `AssistantMessageEvent` -> `ResponseCompleteEvent`.
- `ResponseCompleteEvent` is the canonical “final snapshot” for replay and external consumers.
- `ResponseCompleteEvent` fields are locked:
  - `session_id: str`
  - `response_id: str | None`
  - `content: str` (final assistant text)
  - `thinking_text: str | None` (final snapshot of thinking when available)

### E) Explicit streaming boundaries

- Thinking and assistant text streaming boundaries are explicit in protocol events.
- UI must never infer boundaries via heuristics (e.g. “empty delta”).

## Event Specification (Canonical)

### Base model(s)

All protocol events are Pydantic models.

```
# protocol/events/base.py
class Event(BaseModel):
    """Base event."""

    session_id: str
    timestamp: float = Field(default_factory=time.time)


class ResponseEvent(Event):
    """Event associated with a single model response."""

    response_id: str | None = None
```

Notes:

- `response_id` is present on all response-scoped events to simplify correlation.
- Events that are not response-scoped use only `Event`.

### Lifecycle events

```
# protocol/events/lifecycle.py
class TaskStartEvent(Event):
    sub_agent_state: model.SubAgentState | None = None

class TaskFinishEvent(Event):
    task_result: str
    has_structured_output: bool = False

class TurnStartEvent(Event):
    pass

class TurnEndEvent(Event):
    pass
```

### Streaming events (explicit boundaries)

```
# protocol/events/streaming.py

class ThinkingStartEvent(ResponseEvent):
    pass

class ThinkingDeltaEvent(ResponseEvent):
    content: str

class ThinkingEndEvent(ResponseEvent):
    pass

class AssistantTextStartEvent(ResponseEvent):
    pass

class AssistantTextDeltaEvent(ResponseEvent):
    content: str

class AssistantTextEndEvent(ResponseEvent):
    pass

class AssistantImageDeltaEvent(ResponseEvent):
    file_path: str

class ToolCallStartEvent(ResponseEvent):
    tool_call_id: str
    tool_name: str
```

### Final snapshot event

```
# protocol/events/streaming.py (or protocol/events/metadata.py; naming is what matters)

class ResponseCompleteEvent(ResponseEvent):
    """Final snapshot of the model response."""

    content: str
    thinking_text: str | None = None
```

Semantics:

- This event is emitted exactly once for a completed model response.
- Live REPL may ignore `content` and treat it as a completion boundary.
- Replay and JSON streaming consumers can use `content`/`thinking_text` to reconstruct output without deltas.

### Tools execution events

These represent actual tool execution (not model-side streaming):

```
# protocol/events/tools.py

class ToolCallEvent(ResponseEvent):
    tool_call_id: str
    tool_name: str
    arguments: str

class ToolResultEvent(ResponseEvent):
    tool_call_id: str
    tool_name: str
    result: str
    ui_extra: model.ToolResultUIExtra | None = None
    status: Literal["success", "error"]
    task_metadata: model.TaskMetadata | None = None
    is_last_in_turn: bool = True
```

### Metadata events

```
# protocol/events/metadata.py

class UsageEvent(ResponseEvent):
    usage: model.Usage

class TaskMetadataEvent(Event):
    metadata: model.TaskMetadataItem

class ContextUsageEvent(Event):
    context_percent: float
```

Note:

- `UsageEvent` replaces `ResponseMetadataEvent`.

### Chat/system events

```
# protocol/events/chat.py
class UserMessageEvent(Event):
    content: str
    images: list[message.ImageURLPart] | None = None

class DeveloperMessageEvent(Event):
    item: message.DeveloperMessage

class TodoChangeEvent(Event):
    todos: list[model.TodoItem]


# protocol/events/system.py
class WelcomeEvent(Event):
    work_dir: str
    llm_config: llm_param.LLMConfigParameter
    show_klaude_code_info: bool = True

class ErrorEvent(Event):
    error_message: str
    can_retry: bool = False

class InterruptEvent(Event):
    pass

class EndEvent(Event):
    """Global display shutdown."""

    # session_id is always "__app__"
    pass

class ReplayHistoryEvent(Event):
    events: list[ReplayEventUnion]
    updated_at: float
    is_load: bool = True
```

## Event Ordering Invariants

These rules are required to keep UI simple and deterministic.

### Per `(session_id, response_id)` streaming

- Thinking:
  - `ThinkingStartEvent` MUST be emitted before the first `ThinkingDeltaEvent`.
  - `ThinkingEndEvent` MUST be emitted once when thinking streaming ends.
  - Thinking streaming is not nested.

- Assistant text:
  - `AssistantTextStartEvent` MUST be emitted before the first `AssistantTextDeltaEvent`.
  - `AssistantTextEndEvent` MUST be emitted once when assistant text streaming ends.
  - Assistant text streaming is not nested.

- Tool start signal:
  - If `ToolCallStartEvent` occurs while assistant text streaming is active, the turn layer MUST first emit `AssistantTextEndEvent`.
  - `ToolCallStartEvent` does not imply tool execution; it is a UX hint.

### Response completion

- `ResponseCompleteEvent` is emitted exactly once for each completed model response.
- Order recommendation (not strictly required for all consumers, but preferred):
  1) `ThinkingEndEvent` (if any)
  2) `AssistantTextEndEvent` (if any)
  3) `ResponseCompleteEvent`
  4) `UsageEvent` (if available)

### Cancellation/interrupt

- On user interrupt/cancel:
  - Do NOT emit `ResponseCompleteEvent`.
  - Persist partial assistant text to history (existing behavior) for context continuity.
  - Emit `InterruptEvent` and any tool-abort results as needed.

## UI Architecture Specification

### High-level flow

Replace the current REPL pipeline (event handler + stage manager + ad-hoc buffering) with:

1) `DisplayController`
   - Owns `machines: dict[str, DisplayStateMachine]` keyed by `session_id`.
   - Routes every incoming `Event` to `machines[event.session_id]`.
   - Executes resulting `RenderCommand`s via `CommandRenderer`.

2) `DisplayStateMachine` (per session)
   - Has `DisplayState`: `IDLE`, `THINKING`, `STREAMING_TEXT`, `TOOL_EXECUTING`, `ERROR`.
   - Maintains per-session streaming state (buffers, active flags).

3) `CommandRenderer`
   - Executes `RenderCommand`s against existing `REPLRenderer` primitives.
   - All commands include `session_id` so rendering can use `REPLRenderer.session_print_context(session_id)`.

### Live markdown stream ownership

- Only the main session owns the live markdown streaming area.
- Sub-agent sessions never stream assistant text.
- This is required because the terminal UI uses a single live renderable area.

### Sub-agent session identification

- A session is treated as a sub-agent session if its `TaskStartEvent.sub_agent_state is not None`.
- UI must keep a session registry (colors/styling), similar to current `REPLRenderer.session_map`.

## Current Architecture Notes

## Current Architecture Notes

### Streaming pipeline

Provider LLM client yields `message.LLMStreamItem`:

- Deltas:
  - `message.ThinkingTextDelta`
  - `message.AssistantTextDelta`
  - `message.AssistantImageDelta`
  - `message.ToolCallStartItem`
- Final:
  - `message.AssistantMessage` (parts + usage)

Turn layer translates to protocol events and adds tool execution events.

### Where stage/state currently exists (to be simplified)

- LLM stream parsing uses internal stage for correct flush ordering:
  - `src/klaude_code/llm/openai_compatible/stream.py`
- Turn layer currently buffers partial assistant text for cancellation:
  - `src/klaude_code/core/turn.py`
- REPL UI uses stage manager and ad-hoc logic:
  - `src/klaude_code/ui/core/stage_manager.py`
  - `src/klaude_code/ui/modes/repl/event_handler.py`

Goal: UI should not infer stage boundaries.

## Key Files

### Protocol

- `src/klaude_code/protocol/events.py` (current; will be replaced by package)
- `src/klaude_code/protocol/message.py` (stream items + final message parts)

### Core

- `src/klaude_code/core/turn.py` (delta consumption + event emission)
- `src/klaude_code/core/task.py` (task-level orchestration and event routing)
- `src/klaude_code/session/session.py` (replay history event generation)
- `src/klaude_code/core/manager/sub_agent_manager.py` (sub-agent sessions + event forwarding)

### UI

- `src/klaude_code/ui/modes/repl/event_handler.py` (current, to be replaced/refactored)
- `src/klaude_code/ui/modes/repl/renderer.py` (rendering primitives + per-session styling)
- `src/klaude_code/ui/core/stage_manager.py` (to remove)

### Tests and Displays

- `src/klaude_code/ui/modes/exec/display.py` (ExecDisplay + StreamJsonDisplay)
- `tests/test_osc94_progress_bar.py` (references `ErrorEvent` and `TaskFinishEvent`)
- `tests/test_session.py` (replay and sub-agent replay)

## Acceptance Criteria Checklist (High Level)

- Explicit streaming boundaries exist (thinking/text).
- REPL does not rely on heuristics (no “empty delta” hacks).
- Sub-agent sessions do not stream assistant text.
- `ResponseCompleteEvent` exists and is emitted at end of model response.
- `uv run ruff format`, `uv run ruff check --fix .`, `uv run pyright`, `uv run pytest` are green.