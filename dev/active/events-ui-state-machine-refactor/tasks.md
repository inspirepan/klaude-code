# Tasks: Events + REPL State Machine Refactor

Last Updated: 2026-01-03

## Checklist

- [x] Lock event spec (names + fields + invariants)
- [x] Lock `ResponseCompleteEvent` fields (`response_id`, `thinking_text`)
- [x] Decide `EndEvent.session_id` sentinel (`"__app__"`)

- [ ] Create `src/klaude_code/protocol/events/` package skeleton
- [ ] Implement `Event` base model (`session_id`, `timestamp`)
- [ ] Implement lifecycle events (task/turn)
- [ ] Implement streaming events (ThinkingStart/Delta/End, AssistantTextStart/Delta/End, ImageDelta, ToolCallStart)
- [ ] Implement tool execution events (ToolCallEvent, ToolResultEvent)
- [ ] Implement metadata events (UsageEvent, TaskMetadataEvent, ContextUsageEvent)
- [ ] Implement system/chat events (Welcome, End, ReplayHistory, Interrupt, Error, UserMessage, DeveloperMessage, TodoChange)
- [ ] Replace `AssistantMessageEvent` with `ResponseCompleteEvent`
- [ ] Remove old `src/klaude_code/protocol/events.py`

- [ ] Update imports across repo to new events package

- [ ] Update `src/klaude_code/core/turn.py` to emit explicit boundaries
- [ ] Ensure tool-start boundary ends text stream (emit `AssistantTextEndEvent` before tool execution starts)
- [ ] Emit `ResponseCompleteEvent` at final `message.AssistantMessage`
- [ ] Replace `ResponseMetadataEvent` usage with `UsageEvent`
- [ ] Keep cancel partial assistant persistence behavior

- [ ] Update `src/klaude_code/core/task.py` match-cases for renamed events
- [ ] Update `src/klaude_code/session/session.py` replay generation to new events
- [ ] Update `src/klaude_code/core/agent.py` / replay wrappers if needed

- [ ] Add `ui/state/display_state.py` (`DisplayState` enum)
- [ ] Add `ui/state/state_machine.py` (per-session machine)
- [ ] Add `ui/renderer/command_renderer.py` (execute render commands)
- [ ] Add `ui/state/display_controller.py` (routes by `session_id`)

- [ ] Refactor `src/klaude_code/ui/modes/repl/` to use controller + commands
- [ ] Preserve sub-agent behavior: no assistant text streaming for sub sessions
- [ ] Remove `src/klaude_code/ui/core/stage_manager.py` and all usage
- [ ] Remove/replace old `DisplayEventHandler` logic and heuristics

- [ ] Update `src/klaude_code/ui/modes/exec/display.py` for renamed events
- [ ] Update `src/klaude_code/ui/modes/debug/display.py` if needed (mostly generic)
- [ ] Update tests referencing old event classes

- [ ] Run formatter: `uv run ruff format`
- [ ] Run lint: `uv run ruff check --fix .`
- [ ] Run types: `uv run pyright`
- [ ] Run tests: `uv run pytest`

## Notes

- Keep the REPL output single-owner for live markdown streaming (main session only).
- Sub-agent sessions may still output errors and minimal progress headers.