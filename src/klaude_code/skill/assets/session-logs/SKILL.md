---
name: session-logs
description: Search and analyze session logs (older/parent conversations) using jq. Use this skill when the user asks about prior chats, parent conversations, historical context, or session cost/usage analysis. Triggers include "session logs", "previous conversation", "what did we discuss", "session cost", "session history".
---

# session-logs

Search conversation history stored in session JSONL files. Use when a user references older/parent conversations or asks what was said before.

## Location

Session logs live at: `~/.klaude/projects/<project_key>/sessions/`

- `project_key` is derived from the current working directory (replace `/` with `-`, strip leading `-`). For example, `/home/user/code/my-project` becomes `home-user-code-my-project`.
- Each session is a directory: `<session_id>/`
  - **`events.jsonl`** - Full conversation transcript (one JSON object per line)
  - **`meta.json`** - Session metadata (id, work_dir, created_at, updated_at, user_messages, messages_count, model_name, etc.)

## JSONL Structure

Each line in `events.jsonl` has `{"type": "<TypeName>", "data": {...}}`:

| type | description |
|------|-------------|
| `UserMessage` | User input. `data.parts[].text` for content |
| `AssistantMessage` | Assistant response. `data.parts[]` contains `text`, `thinking_text`, `tool_call` parts |
| `ToolResultMessage` | Tool execution result. `data.tool_name`, `data.output_text` |
| `DeveloperMessage` | System/checkpoint messages |
| `TaskMetadataItem` | Cost and usage stats. `data.main_agent.usage.total_cost` |
| `StreamErrorItem` | Error during streaming |

## Common Queries

### List all sessions by date

```bash
PROJECT_DIR=~/.klaude/projects/<project_key>/sessions
for d in "$PROJECT_DIR"/*/; do
  meta="$d/meta.json"
  [ -f "$meta" ] || continue
  jq -r '[.updated_at // 0 | todate, .id, (.messages_count // 0 | tostring), (.user_messages[0] // "" | .[:60])] | join(" | ")' "$meta"
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
jq -s '[.[] | select(.type == "TaskMetadataItem") | .data.main_agent.usage.total_cost // 0] | add' <session_dir>/events.jsonl
```

### Cost including sub-agents

```bash
jq -s '[.[] | select(.type == "TaskMetadataItem") | ((.data.main_agent.usage.total_cost // 0) + ([.data.sub_agent_task_metadata[]?.usage.total_cost // 0] | add // 0))] | add' <session_dir>/events.jsonl
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
  total: length,
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

- Sessions are append-only JSONL (one JSON object per line)
- Large sessions can be several MB -- use `head`/`tail` for sampling
- `meta.json` caches `user_messages` array for quick listing without parsing events.jsonl
- Sub-agent sessions also exist as separate session directories (they have `sub_agent_state` in meta.json)
- Use `jq -s` (slurp) when aggregating across lines; use streaming mode for extraction
