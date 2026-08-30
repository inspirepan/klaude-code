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
| `llm-request.ts` | `LLMRequestEntry` → the request dot's provider / options / usage / timing. |
| `system-context.ts` | `GET .../system-context` → the SYSTEM row's prompt snapshot and tool catalogue. |
| `classify.ts` | Non-human `UserMessage` detection and the legacy checkpoint reminder. |
| `snapshot.ts` | The single linear pass that builds nodes, requests and annotations. |
| `annotate.ts` | Applies annotations to the folded layout (imported by `TrajectoryView`). |
| `record-focus.ts` | Ledger line → folded record index, for the search jump (imported by `TrajectoryView`). |
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
| `CompactionEntry` | `CompactionSummaryNode` | `compacted` (built from the request) | one `compaction` `RequestView` | Dot anchors on the COMPACT row; `request_id` joins the primary `LLMRequestEntry` onto it. |
| `RewindEntry` (legacy) | `ContextMessageNode` | `rewind` | — | Rationale + note as the body. |
| `SideQuestionEntry` | `ContextMessageNode` | `btw` | — (its call's dot sits on the line above) | Question is the row preview, answer follows in Preview/Raw. |
| `ForkSummaryEntry` | `UserMessageNode` | `user` | — (its call's dot sits on the line above) | Renders as a user row but does **not** open a turn — `session/ledger.py` does not count it as one, and neither does the fallback. |
| `LLMRequestEntry` | — | — (a dot with no row) | one `assistant` `RequestView`, unless a following entry claims it | One LLM call made outside a step. See “Request dots”. |
| `SpawnSubAgentEntry` | — | — | — | Attaches `{sessionId, type, desc}` to the next unlinked `Agent` tool call (FIFO, so parallel spawns line up with their batch). |
| `InterruptEntry`, `StreamErrorItem` | — | — | folds into the preceding assistant request (`status: 'error'` + message) | Reset at each user message. |
| `CacheHitRateEntry` | — | — | folds into the **following** assistant request's usage | klaude writes it when the step's usage arrives, i.e. just before the assistant message it describes. Used only when the provider reported no cached tokens, and never for an `LLMRequestEntry` — it belongs to a main step. |
| `RetractEntry` | — | — | — | The withdrawn row is greyed through its own `status`. |
| `TaskMetadataItem`, `TaskFileChangeSummaryEntry`, `FallbackModelConfigWarnEntry`, `PromptSuggestionEntry`, `AwaySummaryEntry`, unknown types | — | — | — | No row. |

Row status (`retracted` / `compacted` / `rewound`) becomes
`cell.discarded = {status, droppedBy}`: the row keeps its place, greyed and
struck through (UX spec D3). `unknown` rows and rows with `entry: null` render
nothing.

## Request dots

Every LLM call gets one dot, numbered session-globally in wire order. A main
step reads its own `AssistantMessage.usage`; the three calls that happen
*outside* a step — compaction, `/btw`, `/rewind`'s fork summary — used to throw
their numbers away and now persist an `LLMRequestEntry` instead.

**The join is `request_id`, never position.** The entry is written on the line
immediately before the entry it describes, and that entry repeats the id — but
one operation can issue several calls, and a failed one has no paired entry at
all, so adjacency is not a reliable pairing.

| Entry kind / `label` | Where its dot lands |
|---|---|
| `compaction`, the call `CompactionEntry.request_id` names (`fork` > `summary` > `task_prefix`) | merged into the COMPACT row's own request |
| `compaction`, the other call of a degraded run | its own dot on the line above the COMPACT row, fanned out beside it |
| `side_question` | its own dot on the line above the BTW row |
| `fork` (`fork` or `fallback`) | its own dot on the line above the fork-summary USER row, in the **new** session |
| any `status: error` / `interrupted` | its own dot and no row at all, with error styling |

Every one of them shows the same four tabs: Summary, Options, Usage, Timing.

A dot with no row is an `AssistantRequestView` whose `step` is
`SIDECAR_STEP_BASE + line_index`. Upstream's request identity is
`assistant\0turn\0step`, and a synthetic step keeps that identity unique
without inventing a row: `layout.ts` renders such a request as a zero-height
`requestOnly` record, which is also what makes two coincident dots fan out
sideways (`--request-boundary-offset`). The step number never reaches the
screen. The turn is clamped to `>= 1`, because `layout.ts` folds turn-0 cells
into Turn 1 and a dot only renders when the request's turn matches its
record's.

What each tab reads:

- **Summary** — `status` / `error` (`error` and `interrupted` both render as a
  failure; an interrupt that carried no message of its own is named
  `Interrupted`), `provider`, `model`.
- **Options** — `options`, the credential-free dump of the effective call
  parameters, mapped onto the fields `AssistantRequestConfig` declares
  (`provider` / `model` / `purpose` / `reasoningEffort` / `temperature` /
  `maxTokens` / `thinking`). **Absent `options` hides the tab**: an old record
  must never be shown today's model configuration. `verbosity`,
  `cache_retention`, `fast_mode`, `context_limit`, `supports_vision` and `cost`
  have no upstream field and are dropped rather than renamed into one.
- **Usage** — `usage`, through the same inclusive→disjoint mapping an assistant
  message gets (below). `CacheHitRateEntry` is **not** folded in:
  `agent/task.py` writes it for the next *main step*, so charging its cached
  tokens to a compaction or `/btw` call would misattribute them.
- **Timing** — `started_at` / `first_token_at` / `completed_at` become the
  request's `timing`, which `TrajectoryView` turns into the same Started /
  Total / TTFT / Generation / Throughput panel an assistant row gets.
  `first_token_at` is absent when the call streamed no delta; TTFT then reads
  as unavailable rather than 0.

**Old sessions** carry no entry (or no `request_id`): the compaction request
keeps its pre-M4 shape — `completedAt = startedAt`, so the marker reports a
zero-length call rather than a pending one — and usage, options, provider and
timing are simply absent. Nothing is ever rendered as `0`.

## SYSTEM row and tool schemas

klaude persists neither the system prompt nor the tool catalogue, so both come
from `GET /api/web/sessions/{id}/system-context`, fetched once per page load
(`app/api.ts` caches the promise, its failure included) and handed to
`buildTrajectorySnapshot` as `options.systemContext`.

- `available: true` builds a `ConversationPromptSnapshot` and hangs it on the
  window's first ordinary request as `prompt` + `promptChange` (`kind:
  'initial'`, `seq: 0`). That is all `layout.ts` needs to emit its `system`
  record — “Initial System Prompt”, with the System Prompt and Tools tabs.
  Which request carries it decides only *whether* the row exists: an `initial`
  change is always placed at the head of the first visible turn. Seq 0 is a
  constant rather than a window position, so prepending an older page cannot
  change the record's identity.
- `source: 'rebuilt'` means the server re-ran today's prompt builders off the
  session meta, so the snapshot carries a `caveat` (`locale.ts`,
  `klaude.systemContext.rebuilt`) that the inspector prints above the prompt.
- `available: false` — and the window before the fetch resolves — produces no
  SYSTEM row at all, exactly as before M4.
- `callSchemas` maps **call id → schema**, resolved by tool name against that
  same catalogue, for every call in the window — including a result whose call
  head fell outside it. A tool that has since been renamed resolves to nothing
  and its Schema tab stays empty.

The Diff tab stays dormant: there is one snapshot per session, so no `previous`
prompt exists to diff against.

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
persisted history without any live event stream. An `LLMRequestEntry` records
the same three boundaries directly (`started_at` / `first_token_at` /
`completed_at`); they travel on `RequestView.timing`.

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

`assistant.text.end` carries a `stop_reason` when — and only when — the final
`AssistantMessage` closed the block; a block a tool call cut short has no such
key, and neither does an old tape. The reducer keeps it on the partial and
`splice.ts` surfaces it as an in-flight `RequestView` whose status is derived
the way a landed row's `stop_reason` is (`error` → a failed request). Before it
arrives, nothing extra is added.

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

## Search jump

The toolbar's search box is upstream's **live filter over loaded rows** and
stays exactly that (plan decision #22, UX spec §6): whitespace-split AND terms,
a 3000 ms index rebuild throttle, no counter, no next/prev. M5 adds one thing
beside it — an answer for the rows that are *not* loaded — and never changes
the filter itself.

```
TrajectoryView ── onSearchQueryChange ──► session-page.searchQuery
                                              │
                                              ▼
                        SearchBar ── searchSession() ──► /api/web/.../search
                             │  (300 ms debounce, aborts, drops stale answers)
                             │
                             ├─ partitionSearchMatches(matches, firstLoadedLine)
                             │       unloaded / loaded / earliestUnloadedLine
                             │
                             └─ onLoadUntilLine(earliest) ──► session-page
                                       │
                                       ├─ setFocusLine({line})   (before the walk)
                                       └─ walkToLine() ──► loadOlder() × N pages
                                                                │
TrajectoryView ◄── focusRecordLine ─────────────────────────────┘
```

States: **idle** (no query, or nothing older on disk — no request is made) →
**waiting** (debounce running, or the answer in flight; the bar stays hidden) →
**reporting** (`unloaded.length > 0`; the bar names the count and offers the
jump) → **walking** (`loadOlder` pages, progress reads the window's oldest
line) → back to **idle** once the window covers every hit, or **capped**
(`MAX_JUMP_PAGES` pages walked without reaching it; the button becomes
"继续加载"). Any failure — 422 on an empty query, an offline server, an abort —
resolves to "no server information", which renders as no bar at all.

Three things this leans on:

- **The server text is a subset of the client index** (`session/search.py`), so
  a line the server matched is guaranteed to survive the live filter once its
  page is loaded. The bar therefore never has to re-check its own hits.
- **`matches` holds the first `limit` hits ascending**, so `matches[0]` is the
  oldest match even when `truncated` — truncation drops the newest hits, which
  are the ones the loaded window already shows.
- **The jump command is issued before the pages are fetched.** `TrajectoryTable`
  re-runs its scroll effect only when its rows change, so a focus set *after*
  the last page landed would arrive one commit too late and never scroll.
  `record-focus.ts` therefore answers `null` for a line no loaded row reaches,
  and starts answering in the very commit the page lands. It keeps one focus
  object per record so the ledger scrolls once, not once per fold.
