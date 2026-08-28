# Rewind: Two Distinct Concepts

The word "rewind" names two unrelated-by-mechanism features. Do not merge
them, do not share flow control between them, and keep their vocabulary
separate.

## 1. Agent rewind (this package)

The model rolls back its own context mid-task.

- Model-invoked `Rewind` tool (`protocol/tools.py` `REWIND`, implemented in
  `tool/rewind_tool.py`). The model passes a `checkpoint_id` it saw in an
  auto-injected `<system-reminder>Checkpoint N</system-reminder>` marker.
- Semantics: **in-place truncation** of active history back to the checkpoint.
  The discarded tail is **lost** (no summary, no recovery). The session id and
  the session file do not change.
- `manager.py` (this package) holds per-task-run state only: checkpoint
  registration (`agent/task.py` registers one checkpoint per user message),
  validation, and a single-slot pending request (`send_rewind` raises if one
  is already pending). `agent/task.py` fetches the pending request between
  steps and applies it.
- Persisted as `RewindEntry` (`protocol/message.py`). At load time
  `_apply_rewind_entry_to_history` (`session/history.py`) truncates again;
  the entry **stays in active history** so recorded indices (e.g.
  `CompactionEntry.first_kept_index`) still line up after a reload.

## 2. User rewind (`/rewind` TUI command)

The user rewinds the conversation to an earlier point; the discarded tail is
summarized instead of lost.

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
- Pivot anchors: user messages (exact-text match) AND model-Rewind
  boundaries (RewindEntry, matched by checkpoint id) — anchoring on the
  boundary keeps the pre-rewind history verbatim and summarizes only the
  post-rewind redo work. The summary request quotes whichever boundary
  block applies (`build_user_pivot_quote` / `build_rewind_boundary_quote`).
- The summary prompt is `FORK_SUMMARY_PROMPT` in `prompts/compaction.py`
  (9-section detailed style, with the pivot message quoted explicitly so the
  model cannot guess the boundary). This is NOT the compact `## Goal`
  structure — `_preview_compaction_summary` does not apply to it.
- `ForkSummaryEntry` is a suffix summary carried into the new session. It must
  NOT participate in compaction boundary logic: never return it from
  `_find_last_compaction`, never give it a `first_kept_index`. Future
  auto-compaction treats it as ordinary history.

## Naming rules

- The model tool owns the plain word "rewind" for in-place truncation.
  `/rewind` command copy must state that the discarded tail is summarized
  into a new session.
- Fork artifact names stay fork-based even though the UI says rewind:
  `ForkSummaryEntry`, `ForkSummaryReadyEvent`, `FORK_SUMMARY_PROMPT`.
- The user-command operation is `RewindWithSummaryOperation` — never a bare
  `RewindOperation` (that would read as the model-tool flow).

## File map

- `agent/rewind/manager.py` (this package) — agent-rewind pending state only
- `tool/rewind_tool.py` — model `Rewind` tool entry point
- `protocol/message.py` — `RewindEntry`, `ForkSummaryEntry`
- `session/history.py` — load-time application of `RewindEntry`
- `tui/command/rewind_cmd.py` — `/rewind` command (fork-point picker)
- `agent/runtime/agent_ops.py` — `RewindWithSummaryOperation` handler
  (summary generation, fork, entry append, switch event)
- `prompts/compaction.py` — `FORK_SUMMARY_PROMPT`
