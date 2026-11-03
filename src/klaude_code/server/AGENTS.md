# Read-only Web Server

`klaude web` uses `read_only.create_read_only_app`: disk reads only, no Runtime,
execution controls, WebSocket, or daemon. The page polls persisted history.

- Refresh the disk index before listing or resolving sessions.
- Status reflects persisted facts, not whether the viewer owns a Runtime.
- Keep host/path guards and exclude credentials from model context responses.
- Scheduling belongs in `app/scheduler.py`; peer IPC in `app/peer_endpoint.py`.
