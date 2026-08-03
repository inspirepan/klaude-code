"""Autonomy reminder for headless sessions (spawned via `klaude run`).

Injected once at conversation start. Re-injected after compaction: the marker
lives in file_tracker with ``is_memory=True`` so ``reset_attachment_loaded_flags``
clears it together with the other transient reminders.
"""

from __future__ import annotations

from klaude_code.protocol import message
from klaude_code.protocol.models import FileStatus
from klaude_code.session import Session

_AUTONOMY_MARKER = "klaude://autonomy-reminder"

AUTONOMY_REMINDER = """<system-reminder>
You are running unattended, dispatched by another agent. Do not ask
clarifying questions — make reasonable assumptions and state them in
your final report. Interactive requests reach a queue nobody may be
watching; use them only when truly blocked.
</system-reminder>"""


async def autonomy_attachment(session: Session) -> message.DeveloperMessage | None:
    if session.spawn_kind != "headless":
        return None
    if _AUTONOMY_MARKER in session.file_tracker:
        return None
    session.file_tracker[_AUTONOMY_MARKER] = FileStatus(mtime=0.0, content_sha256=None, is_memory=True)
    return message.DeveloperMessage(parts=[message.TextPart(text=AUTONOMY_REMINDER)])
