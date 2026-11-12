---
name: klaude-session-logs
description: Search and analyze klaude-code session logs using jq. Use when the user asks about klaude-code conversation history, parent sessions, or session cost and usage.
---

# klaude-session-logs

Search klaude-code conversation history stored in session JSONL files. Use when a user references older/parent conversations or asks what was said before.

## Location

Session logs live at: `~/.klaude/projects/<project_key>/sessions/`

- `project_key` is derived from the current working directory (replace `/` with `-`, strip leading `-`). For example, `/home/user/code/my-project` becomes `home-user-code-my-project`.
- Each session is a directory: `<session_id>/`
  - **`events.jsonl`** - Full conversation transcript (one JSON object per line)
  - **`meta.json`** - Session metadata (id, work_dir, created_at, updated_at, user_messages, messages_count, model_name, etc.)

## JSONL Structure

Each line in `events.jsonl` has `{"type": "<TypeName>", "data": {...}}`. Common types are:

| type | description |
|------|-------------|
| `UserMessage` | User input. `data.parts[].text` for content |
| `AssistantMessage` | Assistant response. `data.parts[]` contains `text`, `thinking_text`, `tool_call` parts |
| `ToolResultMessage` | Tool execution result. `data.tool_name`, `data.output_text` |
| `SystemMessage` | System-level model input |
| `DeveloperMessage` | Model-facing attachments, reminders, and checkpoints |
| `TaskMetadataItem` | Cost and usage stats. `data.main_agent.usage.total_cost` |
| `StreamErrorItem` | Error during streaming |
| `InterruptEntry` | Interrupted task marker |
| `CompactionEntry` | Context compaction summary and boundary |
| `RewindEntry` | Session rewind marker |
| `CacheHitRateEntry` | Prompt cache hit-rate snapshot |
| `SpawnSubAgentEntry` | Sub-agent session spawned from this parent session |
| `AwaySummaryEntry` | Persisted while-you-were-away summary |
| `PromptSuggestionEntry` | Persisted next-prompt suggestion |

Other sidecar event types may be added over time. Inspect available types before writing queries that must account for every JSONL row.

## Common Queries

### List all sessions by date

```bash
PROJECT_DIR=~/.klaude/projects/<project_key>/sessions
for d in "$PROJECT_DIR"/*/; do
  meta="$d/meta.json"
  [ -f "$meta" ] || continue
  jq -r '[((.updated_at // 0) | todate), .id, ((.messages_count // 0) | tostring), ((.user_messages[0] // "") | .[:60])] | join(" | ")' "$meta"
done | sort -r
```

### Find sessions from a specific day

```bash
for d in "$PROJECT_DIR"/*/; do
  [ -f "$d/meta.json" ] || continue
  jq -r 'select((.updated_at // 0 | todate) | startswith("2026-02-21")) | .id' "$d/meta.json"
done
```

### Extract user messages from a session

```bash
jq -r 'select(.type == "UserMessage") | .data.parts[]? | select(.type == "text") | .text' <session_dir>/events.jsonl
```

### Search for keyword in assistant responses

```bash
jq -r 'select(.type == "AssistantMessage") | .data.parts[]? | select(.type == "text") | .text' <session_dir>/events.jsonl | rg -i "keyword"
```

### Get total cost for a session

```bash
jq -s '[.[] | select(.type == "TaskMetadataItem") | .data.main_agent.usage.total_cost // 0] | add // 0' <session_dir>/events.jsonl
```

### Cost including sub-agents

```bash
jq -s '[.[] | select(.type == "TaskMetadataItem") | ((.data.main_agent.usage.total_cost // 0) + ([.data.sub_agent_task_metadata[]?.usage.total_cost // 0] | add // 0))] | add // 0' <session_dir>/events.jsonl
```

### Daily cost summary

```bash
for d in "$PROJECT_DIR"/*/; do
  [ -f "$d/events.jsonl" ] || continue
  date=$(jq -r '.updated_at // 0 | todate | split("T")[0]' "$d/meta.json" 2>/dev/null) || continue
  cost=$(jq -s '[.[] | select(.type == "TaskMetadataItem") | ((.data.main_agent.usage.total_cost // 0) + ([.data.sub_agent_task_metadata[]?.usage.total_cost // 0] | add // 0))] | add // 0' "$d/events.jsonl")
  echo "$date $cost"
done | awk '{a[$1]+=$2} END {for(d in a) printf "%s $%.4f\n", d, a[d]}' | sort -r
```

### Count messages in a session

```bash
jq -s '{
  events: length,
  total: [.[] | select(.type == "UserMessage" or .type == "AssistantMessage" or .type == "ToolResultMessage")] | length,
  user: [.[] | select(.type == "UserMessage")] | length,
  assistant: [.[] | select(.type == "AssistantMessage")] | length,
  tool_results: [.[] | select(.type == "ToolResultMessage")] | length
}' <session_dir>/events.jsonl
```

### Tool usage breakdown

```bash
jq -r 'select(.type == "AssistantMessage") | .data.parts[]? | select(.type == "tool_call") | .tool_name' <session_dir>/events.jsonl | sort | uniq -c | sort -rn
```

### Search across ALL sessions for a phrase

```bash
rg -l "phrase" "$PROJECT_DIR"/*/events.jsonl
```

### Extract model names used

```bash
jq -r 'select(.type == "TaskMetadataItem") | .data.main_agent.model_name' <session_dir>/events.jsonl | sort -u
```

### Fast text-only output (low noise)

```bash
jq -r 'select(.type == "UserMessage" or .type == "AssistantMessage") | .data.parts[]? | select(.type == "text") | .text' <session_dir>/events.jsonl | rg "keyword"
```

## Tips

- `events.jsonl` is append-only (one JSON object per line); `meta.json` is an atomically rewritten snapshot
- Large sessions can be several MB -- use `head`/`tail` for sampling
- `meta.json` caches `user_messages` array for quick listing without parsing events.jsonl
- `meta.json.messages_count` counts `UserMessage`, `AssistantMessage`, and `ToolResultMessage`; it is not the total number of JSONL rows
- Sub-agent sessions also exist as separate session directories (they have `sub_agent_state` in meta.json)
- Include `TaskMetadataItem` entries with `is_partial: true` in cost totals: they represent usage from interrupted tasks
- Use `jq -s` (slurp) when aggregating across lines; use streaming mode for extraction
