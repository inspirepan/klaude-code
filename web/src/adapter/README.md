# adapter — klaude ledger → `TrajectorySnapshot`

Pure functions. No React, no fetch, no DOM. `buildTrajectorySnapshot(rows,
{sessionId})` takes the rows of `GET /api/web/sessions/{id}/history` (ascending
`line_index`) and returns the snapshot the forked trajectory view folds. This
replaces upstream's 1752-line Definition pipeline; everything it produces is a
pure function of the rows, so rebuilding after a prepend is cheap and stable.

| File | Role |
|---|---|
| `wire.ts` | REST shapes (`HistoryRow`, `HistoryPage`, `SessionMeta`, `SessionListRow`, `SessionState`). |
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
| `ForkSummaryEntry` | `UserMessageNode` | `user` | — | Renders as a user row but does **not** open a turn — `session/ledger.py` does not count it as one, and neither does the fallback. |
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

Every history row carries the ordinals `session/ledger.py` computes in one pass
over the **whole file**, so they are absolute and a prepend cannot renumber
anything:

| Field | Meaning |
|---|---|
| `turn_index` | 1-based human turn; **0** for lines ahead of the first human user message. |
| `step_index` | 1-based `AssistantMessage` inside the turn; `null` on every other line. |
| `auto` | `UserMessage` lines only: true when the runtime wrote the message (bash-mode echo, empty-response retry, stream-error retry, sub-agent fork context). |

`buildTrajectorySnapshot` adopts them wherever they are present, for the node's
`turn`/`step`, for `eventLocations`, for the request identity
`assistant\0turn\0step`, and for the `auto` row tag. Turn 0 is kept as 0:
`layout.ts` already folds turn-0 cells into Turn 1, which is exactly the
prologue's place.

**The fallback still exists** for a server older than the ledger scan: `turn`
then counts human user messages seen inside the loaded window (`classify.ts`
decides which ones are human) and `step` counts assistant messages inside the
turn. Window-relative ordinals shift when an older page is prepended — the third
turn on screen becomes the fifth once its predecessors load. Row identity
deliberately does not depend on them: `layout.ts` was patched to key an
assistant record on `node.seq` instead of `turn/step`, so keys survive a
prepend either way. Both paths are covered by `snapshot.test.ts`
(`describe('turn ordinals')`).

The two paths agree on everything the ledger scan defines, `ForkSummaryEntry`
included: it renders as a user row but opens no turn.

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

`partial` and `runningCalls` are always empty **here**. They are spliced in
afterwards by `src/app/live`, which is the only consumer of the WS channel:

```
buildTrajectorySnapshot(rows)  ->  spliceLiveSnapshot(snapshot, liveState)  ->  TrajectoryView
        (REST, landed rows)              (WS, partial + runningCalls)
```

The split is deliberate and matches the upstream snapshot model: REST owns
every row that reached `events.jsonl` — with its ledger status, its usage and
its stable seq — and the socket only contributes the two fields that describe
work still in flight. A cold session never opens a socket (decision #28) and
therefore simply has neither, which is deviation D11.

The wire carries no absolute turn ordinal for a response that has not landed,
so `spliceLiveSnapshot` anchors the in-flight rows on the newest landed one:
the streaming `partial` is the step *after* it inside the same turn, and a
running tool call belongs to the streaming step when a response is open, else
to the landed step. `history.appended` refreshes the tail within a flush of the
row landing, so that anchor is never more than one row stale.

`app/live/merge.ts` owns the other half of the handshake — pulling the
`after_line` increment, and re-reading the statuses of the loaded window when a
marker (`CompactionEntry` / `RetractEntry` / `RewindEntry`) lands, since a
marker restates the status of lines above it. The refresh replaces `status` and
`dropped_by` in place: `line_index` and `entry` are never rewritten, so React
keys and the folded layout survive it.
