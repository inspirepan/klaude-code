# Server Notes

## Event routing

- A WebSocket forwards a session's own events and its descendants' (found in
  persisted history at attach, then by `TaskStartEvent.parent_session_id`).
  Never forward by task ID: IDs are attribution, not ownership.
- Work done for another session must not inherit the caller's event context.
  `deliver_peer` runs under `detached_event_context()`, and server-spawned
  tasks (drains, launches, actor workers) use `create_task(context=detached_context())`;
  otherwise the recipient's events carry the sender's task ID.

## Root agent states

`HeadlessRuntime` treats a root agent as Working (turn running), Waiting (in a
wait tool; any new input ends the wait), Awaiting (no turn, owned agents
running), Idle, or Paused (user interrupted or stopped).

- A finished owned agent signals `Agent.signal_task_result()` and, when the
  owner is Awaiting, starts a `ContinueAgentOperation` that delivers its report.
  Each delivery wakes at most once. Finished shells do not wake an idle owner.
- Paused (`_wake_paused`, stop and failure latches) lifts only on operator
  input: typed, bash mode, or an operator `send` (`sender_session_id is None`).
  Attach revives the drain latches but not Paused.
- Another agent's message never lifts a stop or failure, and peer-only queues
  start at most `PEER_TURNS_WITHOUT_USER_LIMIT` turns between operator inputs.
