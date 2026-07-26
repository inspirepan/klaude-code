# Compaction Module Guidelines

Context-window compaction keeps a structured summary plus a recent, valid suffix of conversation
history. The persisted history remains append-only; `Session.get_llm_history()` constructs the
compacted view sent to providers.

## Ownership

- `compaction.py`: threshold calculation, cut-point selection, summary generation, file-operation
  carry-over, and `CompactionEntry` construction.
- `overflow.py`: provider error classification for context-window overflow.
- `prompts/compaction.py`: model-facing summary prompts and the summary prefix. Keep prompt text
  there rather than duplicating it in this package.

## Triggering

`should_compact_threshold()` compares the current LLM-facing token estimate against the effective
input budget:

```text
context_limit - max_tokens - reserve_tokens
```

The reserve and kept-tail sizes are derived by `_resolve_compaction_config()` and scale with the
context window. Manual `/compact` keeps a smaller recent suffix than automatic compaction. Keep
numeric expectations in `tests/agent/test_compaction_threshold.py`, not in this document.

Token accounting prefers the last successful `usage.context_size`, adds history written after that
usage, and falls back to estimating the current LLM-facing history. A compaction newer than the last
usage invalidates that usage snapshot for threshold decisions.

There are three entry paths:

1. `tui/runner.py` checks before submitting a new user turn and schedules
   `CompactSessionOperation` first when needed.
2. `agent/task.py` checks before every main-agent step, covering multi-tool loops without a new
   user turn. Sub-agents skip this automatic check.
3. `agent/task.py` classifies provider errors with `is_context_overflow()`, compacts, then retries
   the failed step.

## Cut and Summary Invariants

- Start after the previous compaction's `first_kept_index`; repeated compactions must summarize the
  previous summary rather than resurrect already-compacted history.
- Never leave the kept suffix beginning with dangling tool results or split an assistant tool call
  from its results. Preserve developer/user anchors around the cut.
- Prefer the cache-sharing fork summary path when the compact model and main profile are compatible;
  otherwise serialize the summarized prefix into the dedicated compaction prompt.
- Strip system reminders and sanitize instruction-like text before persisting a summary.
- The fallback serializer records image file/URL references as text instead of embedding bytes. The
  cache-sharing fork path uses the actual LLM-facing prefix, so its media still goes through the
  provider input budget; do not assume every compaction request is metadata-only.
- Carry forward read/modified file details and `kept_items_brief`, then append the continuation
  instruction exactly once.

## Persisted and LLM-Facing History

`run_compaction()` returns a `CompactionResult`; callers append `result.to_entry()` to session
history. Loading a session rebuilds active history around rewinds and the latest compaction. The
LLM-facing view contains the summary as a user message followed by the valid kept suffix, with
dangling tool calls removed as needed.

When changing cut logic, test repeated compaction, rewind interaction, split tool steps, and old
persisted sessions. Run `tests/agent/test_compaction*.py` and the session-history tests before
broader Python checks.
