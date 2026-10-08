Manage shell tasks owned by the current session; never lists arbitrary OS processes.

- `list`: authoritative background tasks and recent completions, including IDs after context compression.
- `output`: read a bounded output page. Pass `next_offset` as `offset` on the next request; offsets are bytes. `truncated` means more output is available now.
- `wait`: wait for completion up to `wait_ms` (default 10000). A wait timeout does not stop the task. Prefer a meaningful wait over repeatedly polling output or list.
- `stop`: terminate the owned process group and preserve its output.

Background completion is reported automatically. Do other useful work instead of busy-polling. A `lost` task means the server restarted and cannot attest to its old process; it is not a successful completion. Old output may expire under retention limits.