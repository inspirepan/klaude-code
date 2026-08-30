# adapter — klaude ledger → `TrajectorySnapshot`

Pure functions. No React, no fetch, no DOM. `buildTrajectorySnapshot(rows,
{sessionId})` takes the rows of `GET /api/web/sessions/{id}/history` (ascending
`line_index`) and returns the snapshot the forked trajectory view folds. This
replaces upstream's 1752-line Definition pipeline; everything it produces is a
pure function of the rows, so rebuilding after a prepend is cheap and stable.

| File | Role |
|---|---|
| `wire.ts` | REST shapes (`HistoryRow`, `HistoryPage`, `SessionMeta`, `SessionListRow`). |
| `json.ts` | Defensive readers for the opaque `entry.data`; `readTime` for Python's zone-less microsecond stamps. |
| `seq.ts` | The seq scheme (below). |
| `parts.ts` | klaude `parts` → upstream `ContentBlock` / `AssistantBlock`. |
| `images.ts` | Image parts → `ImageAttachmentRef` carrying a loadable URL. |
| `usage.ts` | `Usage` → the panel's disjoint token buckets, plus `AssistantTiming`. |
| `classify.ts` | Non-human `UserMessage` detection and the legacy checkpoint reminder. |
| `snapshot.ts` | The single linear pass that builds nodes, requests and annotations. |
| `annotate.ts` | Applies annotations to the folded layout (imported by `TrajectoryView`). |
| `fixtures.ts` | Row builders used by the tests. |

## Seq scheme

`layout.ts` interleaves nodes (`node.seq`) and requests (`RequestView.startSeq`)
on one integer axis and `TrajectoryView` numbers requests in that order, so a
request header must be able to sit *between* two nodes. Every raw line therefore
owns a block of 8 seqs:

```
base = line_index * 8
base + 0   the request produced by that line   (request dot anchor)
base + 1   the conversation node               (the ledger row)
base + 2   step end / reserved
base + 3.. reserved (live partial rows, future sidecars)
```

Consequences:

- A request sorts after the previous line's node and before its own node, so
  request headers land exactly where the model call happened — no fractional
  seqs, no renumbering.
- Seqs are a pure function of `line_index`, so prepending an older page leaves
  every already-rendered row's seq (and therefore its React key) untouched.
- `lineIndexOfSeq(seq)` recovers the raw line for any seq.

## Entry mapping

| klaude entry | Node | Row kind | Request | Notes |
|---|---|---|---|---|
| `UserMessage` | `UserMessageNode` | `user` | — | Non-human ones (`source == "bash_mode"`, the empty-response and stream-error continuation prompts, the sub-agent fork-context reminder) are tagged `auto` and do **not** open a turn. |
| `AssistantMessage` | `AssistantMessageNode` | `message` (+ one `tool` row per `ToolCallPart`) | one `assistant` `RequestView` | `usage` → buckets, `stop_reason == "error"` → `status: 'error'`. |
| `ToolResultMessage` | `ToolResultNode` | folded into the paired `tool` row | — | Paired by `call_id`; `callTime` is the emitting assistant's `created_at`. `status ∈ {error, aborted}` → `isError`, headline = first output line. |
| `DeveloperMessage` | `ContextMessageNode` | `context` | — | Hidden when the text carries a legacy `<system-reminder>Checkpoint N</system-reminder>`. |
| `CompactionEntry` | `CompactionSummaryNode` | `compacted` (built from the request) | one `compaction` `RequestView` | Dot anchors on the COMPACT row; usage/timing stay unknown until M4. |
| `RewindEntry` (legacy) | `ContextMessageNode` | `rewind` | — | Rationale + note as the body. |
| `SideQuestionEntry` | `ContextMessageNode` | `btw` | — | Question is the row preview, answer follows in Preview/Raw. |
| `ForkSummaryEntry` | `UserMessageNode` | `user` | — | Opens a turn: it is the forked session's first user message. |
| `SpawnSubAgentEntry` | — | — | — | Attaches `{sessionId, type, desc}` to the next unlinked `Agent` tool call (FIFO, so parallel spawns line up with their batch). |
| `InterruptEntry`, `StreamErrorItem` | — | — | folds into the preceding assistant request (`status: 'error'` + message) | Reset at each user message. |
| `CacheHitRateEntry` | — | — | folds into the **following** request's usage | klaude writes it when the step's usage arrives, i.e. just before the assistant message it describes. Used only when the provider reported no cached tokens. |
| `RetractEntry` | — | — | — | The withdrawn row is greyed through its own `status`. |
| `TaskMetadataItem`, `TaskFileChangeSummaryEntry`, `FallbackModelConfigWarnEntry`, `PromptSuggestionEntry`, `AwaySummaryEntry`, unknown types | — | — | — | No row. |

Row status (`retracted` / `compacted` / `rewound`) becomes
`cell.discarded = {status, droppedBy}`: the row keeps its place, greyed and
struck through (UX spec D3). `unknown` rows and rows with `entry: null` render
nothing.

There is **no SYSTEM row yet**: klaude never persists the system prompt or the
tool catalog. M4 adds `GET /api/web/sessions/{id}/system-context`; until then
`requests[].prompt` / `promptChange` stay unset, which `layout.ts` handles by
emitting no `system` entries at all.

## Turn and step numbering

`turn` counts human user messages seen **within the loaded window**; `step`
counts assistant messages inside the turn (1-based). `eventLocations` publishes
the same pair, which drives `Turn N · Step M` and the request identity
`assistant\0turn\0step`.

Because the window can grow at the top, turn ordinals shift when an older page
is prepended (the third turn on screen becomes the fifth once its predecessors
load). Row identity deliberately does **not** depend on them: `layout.ts` was
patched to key an assistant record on `node.seq` instead of `turn/step`, so keys
survive a prepend. An absolute turn ordinal per row from the server would remove
the label shift — see the open questions in `web/VENDOR.md`.

## Usage

klaude's counts are inclusive (`AGENTS.md`, "Usage Model Semantics"); upstream's
panel wants a disjoint input split. `toUsageLike` therefore reports the
*uncached* remainder as `inputTokens`:

```
cacheRead   = cached_tokens                       (or CacheHitRateEntry, when 0)
cacheWrite  = cache_write_tokens
promptTotal = max(input_tokens, cacheRead + cacheWrite)   # Bedrock normalization
inputTokens = promptTotal - cacheRead - cacheWrite
outputTokens / reasoningTokens pass through (upstream prints Content = output - reasoning)
```

so the panel's `Input = input + cacheRead + cacheWrite` reproduces the recorded
prompt total. Empty cache and reasoning buckets are omitted rather than printed
as zeros.

Timing is `{stepStartTime: usage.created_at, firstTokenTime: created_at +
first_token_latency_ms, completedTime: message.created_at}`, which makes the
inspector's Started / Total / TTFT / Generation / Throughput rows correct for
persisted history without any live event stream.

## Annotations

`layout.ts` builds cells from nodes alone, so ledger-only facts travel beside the
snapshot in `annotations` and are applied by `applyTrajectoryAnnotations` in
`TrajectoryView`, once, before the table, the timeline and the search index see
the cells:

- `bySeq` — keyed on `cell.sourceSeq` (message-backed rows, and the COMPACT row
  through its request seq).
- `byCallId` — keyed on `cell.callId` (tool rows carry no seq).

Fields: `lineIndex`, `discarded`, `auto`, `subAgent`, and `kind` (the `rewind` /
`btw` override, since no upstream node arm produces those rows).

## Live state

`partial` and `runningCalls` are always empty here. The WS channel is part 2: it
will feed those two fields (and only those) while REST keeps owning every landed
row, exactly as the upstream snapshot model expects.
