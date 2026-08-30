# Rewind: `/rewind` (fork + summary)

"Rewind" now names exactly one feature: the user rewinds the conversation to
an earlier point and the discarded tail is summarized instead of lost.

The model-invoked `Rewind` tool and its checkpoint markers were removed. Only
the read path survives, so old session files still load — see "Legacy" below.

## User rewind (`/rewind` TUI command)

- Semantics: **fork to a new session**. The server-side
  `RewindWithSummaryOperation` summarizes messages `[pivot..end]` via the
  cache-sharing fork request (full `get_llm_history()` prefix + trailing
  instruction — same pattern as `_build_summary_fork` in
  `agent/compaction/compaction.py`, but scoped to the suffix), then
  `Session.fork(until_index=pivot)` + append `ForkSummaryEntry` + switch the
  client to the new session. Model view of the new session: `[kept prefix,
  summary-as-UserMessage]`.
- Lossless: the original session is untouched (append-only) and remains
  switchable (`klaude -r <short-id>`).
- Pivot anchors: user messages, matched by exact text. The summary request
  quotes the pivot block (`build_user_pivot_quote`).
- The summary prompt is `FORK_SUMMARY_PROMPT` in `prompts/compaction.py`
  (9-section detailed style, with the pivot message quoted explicitly so the
  model cannot guess the boundary). This is NOT the compact `## Goal`
  structure — `_preview_compaction_summary` does not apply to it.
- `ForkSummaryEntry` is a suffix summary carried into the new session. It must
  NOT participate in compaction boundary logic: never return it from
  `_find_last_compaction`, never give it a `first_kept_index`. Future
  auto-compaction treats it as ordinary history.

## Naming rules

- Fork artifact names stay fork-based even though the UI says rewind:
  `ForkSummaryEntry`, `ForkSummaryReadyEvent`, `FORK_SUMMARY_PROMPT`.
- The user-command operation is `RewindWithSummaryOperation` — never a bare
  `RewindOperation`.

## Legacy: the removed model `Rewind` tool

Sessions written before the removal may contain `RewindEntry` and `Rewind`
tool calls. Nothing writes them any more; the read path is kept so those files
still load and replay:

- `protocol/message.py` — `RewindEntry` model (decode only)
- `session/history.py` — `find_checkpoint_index_in_history`, applied by
  `scan_history` (the shared scan behind `rebuild_loaded_history`), which
  drops the rewound tail and marks those lines `rewound`
- `session/session.py` — `get_llm_history` materializes `RewindEntry` as a
  `DeveloperMessage(REWIND_REMINDER_TEMPLATE)`; `get_history_item` replays it
  as `RewindEvent`
- `prompts/messages.py` — `CHECKPOINT_TEMPLATE`, `REWIND_REMINDER_TEMPLATE`
- `tui/machine.py` + `tui/renderer.py` — `RewindEvent` → `RenderRewind` notice

Historical `Rewind` tool calls have no dedicated renderer any more; they fall
through to the generic tool renderer.

## File map

- `agent/rewind/summary.py` — suffix summary generation
- `protocol/message.py` — `ForkSummaryEntry`
- `tui/command/rewind_cmd.py` — `/rewind` command (fork-point picker)
- `agent/runtime/agent_ops.py` — `RewindWithSummaryOperation` handler
  (summary generation, fork, entry append, switch event)
- `prompts/compaction.py` — `FORK_SUMMARY_PROMPT`
