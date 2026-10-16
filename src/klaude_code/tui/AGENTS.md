# TUI Rendering Notes

## Current Interactive TUI Architecture

The TUI is a WebSocket client of the local klaude server (`run_attach()` in
runner.py; the wire lives in `tui/client/socket_client.py`). Execution,
follow-up queueing/draining, and interaction parking all happen server-side;
the runner renders the event stream and sends operations over the socket.
Exiting the TUI is a detach — the server keeps the session running.

During interactive `run_attach()` sessions, prompt-toolkit owns the bottom
dynamic UI in both busy and idle states:

- Rich prints stable scrollback content above the prompt.
- prompt-toolkit renders live output, running status, queued follow-up block,
  and input editor in one bottom layout.
- Interactive sessions default to compact transcript rendering: thinking is kept
  out of the scrollback entirely (the status line reports that the model is
  reasoning plus its char count, and the last few lines of the reasoning scroll
  through a transient preview window below it — see the renderer's thinking live
  tail) and sub-agent internals are represented
  by a batched status/summary view. `ctrl-o` toggles the process-local expanded
  view at any time — idle or mid-run — by clearing the screen and replaying the
  display's event tape; expanded mode preserves the full transcript rendering —
  a live markdown stream for the main agent and a complete thinking block per
  sub-agent once that block finishes.
- Transcript rebuilds (ctrl-o toggle, `/refresh`) replay `TUIDisplay._tape`
  (`control/event_tape.py`), NOT `runtime.replay_session_history`. The tape
  records everything the display consumed — including the in-flight turn that
  persisted history does not cover — so a mid-run rebuild reproduces the screen
  and the machine state exactly. Rules:
  - One attach replay is one `ReplayHistoryEvent`: the server sends long
    history in `replay_history` chunks, and `SocketRuntimeClient` merges them
    until the next frame. Each `ReplayHistoryEvent` is a rebuild that resets
    machine and renderer state, so splitting it strands sub-agents whose turns
    cross a chunk and the task snapshot then prints them at the end.
  - The tape is the single re-render source. Do not add a second replay path
    from persisted history for anything the live display already consumed.
  - `DisplayStateMachine` handlers always run with live semantics; a rebuild
    goes through `transition_rebuild`, which only filters the transient-UI
    commands (`_REBUILD_SUPPRESSED_COMMANDS`: spinner/task-clock/title). Do not
    reintroduce per-handler `is_replay` branches — put state bookkeeping in the
    handler and let the filter drop the UI commands.
  - Toggle/refresh are bus events (`ToggleTranscriptDetailEvent`,
    `RefreshDisplayEvent`) handled inside `consume_envelope`, so a rebuild is
    serialized with live events by construction. Do not call rebuild methods on
    the display from outside that consumer.
  - Mid-run rebuilds end with `renderer.flush_rebuild_tails()`: open
    assistant/thinking streams render their stabilized prefix and stay open so
    live deltas continue them; an active bash or compact-thinking tail is
    re-emitted.
  - Terminal width changes reuse the same path: `ResizeWatcher`
    (`input/resize_watcher.py`) chains onto the prompt-toolkit app's
    `_on_resize`, debounces the SIGWINCH burst, and emits a
    `RefreshDisplayEvent` only when the settled width actually changed
    (height-only resizes never rewrap scrollback). Do not register a separate
    SIGWINCH handler — prompt-toolkit owns the signal and re-binds it per app
    run.
  - The repaint erases scrollback (`2J 3J H`) and moves a scrolled-up reader
    to the bottom. Width repaints still run after the resize burst settles,
    but they are unconditional so the transcript always rewraps as soon as
    the new width is known.
- The detail level itself lives in `tui/transcript_detail.py`, not in a bool on
  each layer. Rules when touching compact/expanded behavior:
  - "Does this event print at all" belongs in the `_HIDDEN_IN` table there.
    `DisplayStateMachine._visible` and `TUICommandRenderer._visible` both ask it;
    do not add a fresh `if compact and is_sub_agent` guard beside a display method.
  - "How much does it print" is a `detail: Detail` keyword threaded into the
    component. Do not add a second `compact: bool` convention or a public
    `render_compact_*` twin of an existing renderer; `render_compact_*` is only
    for renderables that have no expanded counterpart at all.
  - `TranscriptDetail` is one object shared by the machine and the renderer;
    `TUIDisplay` owns it. Never give the two layers separate copies -- they would
    drift on toggle and paint a mixed transcript.
  - `compact` in `components/rich/status.py` is the terminal-*width* axis and is
    spelled `narrow`. Keep the two axes textually distinct.
- `MARKDOWN_STREAM_LIVE_REPAINT_ENABLED` is expected to stay `False` for this
  model; do not re-enable Markdown bottom Live to fix spacing or repaint bugs.
- prompt-toolkit must be the only runtime stdin reader. Do not add background
  `os.read(stdin)` monitors. Escape interrupt is implemented as a prompt-toolkit
  key binding, not as a background stdin reader.

### Running status flow

The status data still originates in the existing renderer/status pipeline:

1. `DisplayStateMachine` emits `SpinnerStart` / `SpinnerUpdate` /
   `SpinnerStop` commands.
2. `TUICommandRenderer` builds the Rich status renderable with
   `StackedStatusText` and renders it to styled snapshot fragments. Interactive
   snapshots disable Rich shimmer; prompt-toolkit owns the only status animation.
3. `TUICommandRenderer(status_sink=...)` sends those lines to
   `PromptToolkitInput.set_status_lines()`.
4. `PromptToolkitInput` displays those lines in a prompt-toolkit window and
   adds the lightweight prompt-toolkit spinner prefix. Sub-agent rows reuse the
   same frames with their identity color; completed rows use a static marker.
5. `PromptToolkitInput` periodically asks the renderer to refresh the status
   snapshot so elapsed-time metadata keeps updating while only the spinner is
   animating.

Do not bypass this pipeline with direct prompt-toolkit status strings unless you
also preserve sub-agent coloring/truncation semantics and metadata formatting.

### Shared background tasks and peer messages

- `/tasks` without arguments opens `TaskPanel` in the existing prompt-toolkit
  `SelectOverlay`; explicit `/tasks list/output/wait/stop` keeps text output.
  `RuntimeClient.manage_tasks()` uses the existing owned-task HTTP endpoint;
  panel queries do not enter the transcript or acknowledge model delivery.
- Status bar order: the main agent's spinner row (kept while background
  children run; hidden only while a blocking Agent call is pending), then the
  live tail (thinking preview / bash output), then compact child groups (type,
  description, model, tool count, up to the latest tool rows; attention first,
  under the height budget), then one ` ◈  N agents · N shells … /tasks …` footer
  (`MainTaskStatus`) shown only while background tasks are active. With no main
  turn but agents running, the footer leads with `Awaiting` (a finished agent
  starts the next turn) or `Paused` (the user interrupted; reports wait for them).
- Compact file diffs fold by size (`diffs.fold_limit`): up to 10 changed lines
  (30 for Markdown) show whole, larger edits preview 5 lines (15), a new or
  deleted code file shows only its header. A compact sub-agent's file changes
  print nothing as they happen; the run's `▌` block sums them up in one
  `± N files +a -r paths` line (each diff below it under ctrl-t). ctrl-t (`ToggleDiffDetailEvent`, `TranscriptDetail.diffs_expanded`)
  expands every diff without leaving compact mode; expanded mode never folds.
- A call the agent made keeps its tool mark (`$ Shell`, `◈ Tasks`); input the
  system fills back in later uses `MARK_CALLBACK` (`› Shell`, `› Task`, `› Message`).
  Compact shell/task reports join the open tool block: no blank line before or
  after them (`_CALLBACK_SOURCES`), and a report subject is clipped to two lines.
- The primary session changes only on `WelcomeEvent`. A TaskStart or user
  message from another top-level session (a peer's turn) is dropped, never
  promoted to the main transcript.
  `PromptBottomBar` splits status lines at the first row without the plain
  spinner so the live tail sits under the main row.
- Each background fact reaches the compact transcript once. Agent launches are
  `◈ Agents` rows (consecutive launches share the header); waits are one
  `◈ Tasks  Waiting for <description>` row (repeats collapse) and still-running
  results print nothing; a finished agent prints only its `▌` batch block
  (`TaskDirectory.claim_summary` / `claim_report` dedupe the block against task
  reports and wait results, and a report builds the block when none printed);
  a finished Bash task prints one `$ Shell` row. Background `TaskMetadataEvent`
  cost trees are full-mode only. Name tasks and peers by description through
  `TaskDirectory`, never by ID; IDs belong to `/tasks` and expanded mode.
- Interaction request/resolved/cancelled events join by child session and
  request ID. The existing approval dialog remains the only approval surface.
  It cancels the task panel before `pause_for_external_input()` yields stdin;
  embedded overlays never save/restore editor drafts. External modal pause
  restores both the current draft and its cursor exactly once.
- Task-panel messages require explicit confirmation and a running owned child.
  `send_task_message()` rechecks the task and sends external peer data with
  `expected_operation_id` on `/send-active` (required, no `/send` fallback on
  older servers); server admission checks that operation immediately
  before enqueue. Labels confer no operator identity. A receipt is queued, not
  read; normal safe-boundary peer/follow-up semantics still apply after enqueue.
- `/stop` submits `StopSubAgentsOperation` immediately, even while busy. It stops
  only owned child agents (including queued runs); Esc interrupts only the root.
  Render its actual `OperationFinishedEvent` outcome, never an optimistic success.
- `/tasks list/output/wait/stop` submits `ManageTasksOperation(TaskRequest)`.
  `TaskControlResultEvent` carries the typed response or error through the normal
  display/tape path. Queries never acknowledge model delivery. Long waits run
  outside the actor mailbox and do not occupy a root execution slot.
- `BackgroundTasksUpdatedEvent` is an authoritative full list per owner. It
  reconciles existing sub-agent rows and counts; legacy shell events must not
  override its counts. A running Agent tool reference is not child completion.
  Root completion/interruption does not end child rows or block the editor.
- Peer and task reports are sourced messages, not operator input cards. Render
  `peer_message` fields directly; never parse `<agent-message>` body text.
  Peer messages render as a `Message` tool row naming the peer, with the body
  in a result panel (`render_message`): `✉ … to X` in `PEER_MESSAGE_SENT` (blue)
  and `› … from X` in `PEER_MESSAGE_RECEIVED` (purple), one color for mark,
  border, and body. Compact shows six lines, expanded adds the whole body and
  incoming metadata.
- `TaskMetadataItem.background_task_id` identifies independent background costs.
  Replay it without synthesizing a parent turn finish, and deduplicate against
  typed task snapshots. Background completion never starts an assistant turn.

### Queued follow-up input flow

- Busy-time Enter submits a `FollowUpAgentOperation` instead of interrupting or
  starting another task.
- Queued messages are stored on `Agent` and are not immediately written to
  session history or emitted as normal user turns.
- The queue panel is prompt-toolkit dynamic UI, not scrollback. Do not emit
  queued-message `NoticeEvent`s for the queue panel.
- At safe step boundaries, the current task admits a FIFO batch of queued
  follow-ups before its next request, including retries and final responses.
  Each batch reaches history in one confirmed write before its durable queue
  copy is cleared and its messages are rendered as normal user turns.
- Plain `Up` on an empty editor with queued messages dequeues all queued
  messages at once, clears the queue, and writes them back into the editor
  separated by standalone `--- split ---` lines. Queue-edit parsing also
  accepts standalone `---` lines. `alt-up` / `Esc Up` keeps the same dequeue
  behavior as a fallback. Plain `Up` remains history navigation when the queue
  is empty.

### `/btw` side question flow

A side question runs beside the task instead of inside it, so it deliberately
does not use the queue, the spinner phase, or an overlay:

- The runner intercepts `runs_in_background` commands before queue mode and
  submits `AskSideQuestionOperation` without waiting. The input is not echoed as
  a user turn; the answer panel carries the question instead.
- Pending requests are keyed by `request_id` in `DisplayStateMachine`, and each
  adds its own status row (`_side_question_status_lines`) *next to* the task's
  row, carrying its question ellipsized to one line. Do not express this as a
  `SpinnerPhase`: the phase belongs to the task, and a side question must not
  overwrite what the task reports.
- Task end goes through `_spinner_stop_commands()` so a pending answer keeps the
  spinner alive after the task it was asked during has finished. `Esc` keeps its
  meaning — interrupt the task — and does not cancel a side question.
- The answer prints into scrollback as a bordered panel, not into a
  prompt-toolkit window: terminal scrolling, selection, and links come for free,
  and tape rebuilds plus history replay reproduce it like any other block. It is
  persisted as a `SideQuestionEntry` sidecar, which never reaches LLM input. The
  panel's bottom border reports the forked request's cache hit rate, so the
  entry persists that rate too — replay renders the same panel.

### Live output flow

- Renderer live output, such as bash-mode live tail, should use
  `TUICommandRenderer(stream_sink=...)` while prompt-toolkit owns the bottom UI.
- `PromptToolkitInput.set_stream_lines()` renders the live-output block below
  status and above the queue and input.
- Do not reintroduce `CropAboveLive` for running prompt-owned live output.

### Spacing invariants for the prompt bottom layout

- Bottom-row stability is the core invariant: shrinking the bar without new
  scrollback content repaints it at a higher bottom row and the whole bar
  visibly hops up one line. The renderer therefore holds an ended stream's
  `end_of_stream` signal until its next scrollback write, so the height
  collapse lands in the same redraw that grows the transcript. Growth only
  scrolls the view, which reads as normal streaming.
- Keep one blank row between recent scrollback and the status block at all
  times; the status must never sit flush against transcript content.
- Keep the live-tail block (bash output, thinking preview) directly below
  status when visible.
- Keep status directly above the queue block / input editor.
- Keep one blank row above the queue block and none below it; the queue sits
  directly on the input's top rule.
- Status, queue, and input should be independent blocks; queue updates must not
  clear or replace running status.

## Legacy / Cleanup Notes

These paths are reduced or legacy in the current interactive model:

- `src/klaude_code/tui/components/rich/status.py`
  - Still used. `StackedStatusText`, `ResponsiveDynamicText`, metadata
    truncation, and status-line rendering are used by `TUICommandRenderer` to
    produce prompt-toolkit status snapshots.
  - The old Rich breathing spinner/shimmer is no longer what the user sees in
    the interactive bottom layout while prompt-toolkit owns status, but the file
    still owns important formatting logic.
- `MarkdownStream.live_sink` / `TUICommandRenderer.set_stream_renderable()`
  - Assistant Markdown still passes `set_stream_renderable` as a live sink, but
    normal interactive Markdown live repaint is disabled by
    `MARKDOWN_STREAM_LIVE_REPAINT_ENABLED = False`; stream renderables are
    snapshots for prompt-toolkit `stream_sink`, not Rich bottom Live updates.
  - This is still useful for bash live-tail and any future prompt-owned live
    output, but should not start terminal Live rendering.

Do not reintroduce `src/klaude_code/tui/components/rich/live.py`,
`CropAboveLive`, `_bottom_live`, `_bottom_renderable()`, or related bottom Live
height bookkeeping. The previous Rich bottom Live fallback has been removed;
new running output belongs in the prompt-toolkit bottom layout.

Interactive TUI output is sensitive to Rich version differences and terminal Live behavior. When changing spacing or streaming output, verify both the project environment and the globally installed `klaude` tool environment.

## Rich Version Differences

`uv run ...` and `klaude` may use different Python environments. The project `.venv` can have a different Rich version than the `uv tool install -e --force .` environment under `~/.local/share/uv/tools/klaude-code/`.

Do not assume reinstalling the editable tool also aligns dependency versions. In particular, Rich 14 and Rich 15 differ in how `Console.print(Text(...), end="\n")` handles `Text` values that already end with `\n`: Rich 15 emits the text newline plus the `end` newline, which can create double blank lines in streamed Markdown.

When printing pre-rendered Markdown chunks, keep trailing newlines out of the `Text` payload and pass them via `end` instead. This keeps Rich 14 and Rich 15 behavior consistent.

## Markdown Stream Spacing

`MarkdownStream` splits output into stable scrollback and a live suffix snapshot. Spacing bugs often appear only while streaming, not during replay, because replay renders the full Markdown in one pass.

Keep these invariants:

- Markdown block spacing should produce one visible blank line between Markdown blocks, not two.
- The live suffix should not preserve standalone leading blank lines when the stable prefix already ended at a Markdown block boundary.
- Assistant/thinking message boundaries should still leave one visible blank line before the next rendered block, such as a tool call or metadata line.
- Prompt live output should not add an extra gap between Markdown live content and the status block; keep that separation only for bash live-tail output. The compact-thinking preview also sits flush against the status line, which reads as its header.

## Verification

For spacing changes, test both environments when possible:

```bash
uv run pytest tests/tui/test_markdown_stream.py tests/tui/test_renderer_bottom_live.py tests/tui/test_renderer_spacing.py -q --tb=short
uv run ruff check src/klaude_code/tui src/klaude_code/tui/components/rich tests/tui
```

Also run a real tmux smoke test with the globally installed command, because that exercises the `uv tool` dependency environment:

```bash
tmux new-session -d -s klaude-smoke 'cd /path/to/repo && klaude -m v4-flash:no-thinking'
```

Use prompts that force Markdown streaming boundaries, for example a paragraph followed by a list. Compare live output against `klaude -c` replay only after accounting for the fact that replay does not use the bottom Live stream.
