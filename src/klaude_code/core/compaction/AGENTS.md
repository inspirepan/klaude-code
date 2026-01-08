# Compaction Module

Context window compaction for long conversations.

## File Overview

- `compaction.py`: Core compaction logic, threshold checking, summary generation
- `overflow.py`: Context overflow error detection patterns
- `prompts.py`: LLM prompts for summarization

## Triggering Compaction

### Threshold-based (`should_compact_threshold`)

Compaction triggers when:

```
current_tokens > context_limit - reserve_tokens
```

Default configuration (adjusted based on model's context limit):
- `reserve_tokens`: 16384 (or 25% of context limit)
- `keep_recent_tokens`: 20000 (or 35% of context limit)

Token estimation sources:
1. Last successful `AssistantMessage.usage.context_size`
2. Fallback: estimate from message text length (~4 chars per token)

### Overflow-based (`is_context_overflow`)

Detects LLM API error messages indicating context overflow:
- "prompt is too long"
- "exceeds the context window"
- "context length exceeded"
- HTTP 400/413/429 with no body

## Trigger Locations

### 1. TUI Runner (`tui/runner.py`)

Before executing a `RunAgentOperation`, checks threshold and submits `CompactSessionOperation`:

```python
if run_ops and should_compact_threshold(...):
    await executor.submit_and_wait(CompactSessionOperation(...))
```

### 2. Task Turn Start (`core/task.py`)

At the beginning of each turn in `TaskRunner._run_inner()`. Important for multi-turn tool loops where no new user input occurs:

```python
# Threshold-based compaction before starting a new turn
if ctx.sub_agent_state is None and should_compact_threshold(...):
    result = await run_compaction(reason=CompactionReason.THRESHOLD, ...)
    session_ctx.append_history([result.to_entry()])
```

Note: Sub-agents skip threshold compaction (handled by parent).

### 3. Context Overflow Recovery (`core/task.py`)

When LLM API returns context overflow error, triggers compaction and retries:

```python
except TurnError as e:
    if is_context_overflow(str(e)):
        result = await run_compaction(reason=CompactionReason.OVERFLOW, ...)
        session_ctx.append_history([result.to_entry()])
        continue  # retry turn
```

## Compaction Process

1. **Find cut index**: Walk backwards from history end, accumulating tokens until `keep_recent_tokens` is reached
2. **Adjust cut index**: Never cut on `ToolResultMessage` (breaks LLM history)
3. **Serialize old messages**: Convert to text format `[User]:`, `[Assistant]:`, `[Tool result]:`
4. **Generate summary**: Call LLM with summarization prompt
5. **Append file operations**: Collect read/modified files from `file_tracker` and tool calls
6. **Create `CompactionEntry`**: Store summary, `first_kept_index`, `tokens_before`

## Post-Compaction History (`Session.get_llm_history`)

The LLM-facing history view is constructed as:

```
[UserMessage(summary)] + [kept_messages from first_kept_index:]
```

Implementation in `session.py`:

```python
def get_llm_history(self) -> list[message.HistoryEvent]:
    # Find last CompactionEntry
    last_compaction = find_last_compaction(history)
    
    if last_compaction is None:
        return [it for it in history if not isinstance(it, CompactionEntry)]
    
    # Inject summary as UserMessage
    summary_message = UserMessage(parts=[TextPart(text=last_compaction.summary)])
    
    # Keep messages after cut point
    kept = history[last_compaction.first_kept_index:]
    
    return [summary_message, *kept]
```

The summary contains:
- Compaction prefix: "The conversation history before this point was compacted..."
- Structured summary: Goal, Progress (Done/In Progress/Blocked), Key Decisions, Next Steps
- File operations: `<read-files>` and `<modified-files>` sections
