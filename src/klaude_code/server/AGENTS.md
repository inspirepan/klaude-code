# Server Notes

## Event routing

- A WebSocket forwards a session's own events and its descendants' (found in
  persisted history at attach, then by `TaskStartEvent.parent_session_id`).
  Never forward by task ID: IDs are attribution, not ownership.
- Work done for another session must not inherit the caller's event context.
  `deliver_peer` runs under `detached_event_context()`, and server-spawned
  tasks (drains, launches, actor workers) use `create_task(context=detached_context())`;
  otherwise the recipient's events carry the sender's task ID.

## Session status and continuation

`HeadlessRuntime.session_status()` derives the shared `SessionStatus`: Needs
you takes precedence over Working, then Idle. Execution and attention remain
independent, so a child question never hides other running work. Connections
and loading do not determine the category; turn results are separate facts.

- `continuation()` is shared by status and scheduler admission. A queue alone
  is not a promise to run: paused/error/capped/recovered work needs operator input.
- Root turns can block in a wait tool; no turn with owned agents still running
  is `waiting_agents` only when their results may automatically continue it.

- A finished owned agent signals `Agent.signal_task_result()` and, when the
  owner permits automatic continuation, starts a `ContinueAgentOperation` that delivers its report.
  Each delivery wakes at most once. Finished shells do not wake an idle owner.
- Paused (`_wake_paused`, stop and failure latches) lifts only on operator
  input (typed or bash mode) or explicit `control resume`. Structured peer
  messages never confer operator identity, even without a sender session ID.
  Native messages whose sender matches the recipient's persisted parent carry
  delegated task direction within existing user authorization; they remain peer
  inputs and never lift permission or continuation boundaries.
  Attach only re-arms permitted drains and never lifts control latches.
- Another agent's message never lifts a stop or failure, and peer-only queues
  start at most `PEER_TURNS_WITHOUT_USER_LIMIT` turns between operator inputs.
- Restart resumes only inputs proven not to have started. Interrupted/unknown
  inputs and recovered Agent reports need explicit resume; shell results do not
  wake an idle owner. Loading or viewing a result does not authorize continuation.
