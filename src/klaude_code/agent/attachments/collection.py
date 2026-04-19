from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence

from klaude_code.protocol import message
from klaude_code.session import Session

logger = logging.getLogger(__name__)

type Attachment = Callable[[Session], Awaitable[message.DeveloperMessage | None]]

# Attachments that mutate file_tracker or depend on another attachment's side effects
# must run sequentially.
_SEQUENTIAL_ATTACHMENTS: frozenset[str] = frozenset(
    {
        "at_file_reader_attachment",
        "file_changed_externally_attachment",
        "last_path_memory_attachment",
        "last_path_skill_attachment",
    }
)


async def collect_attachments(
    session: Session,
    attachments: Sequence[Attachment],
) -> list[message.DeveloperMessage]:
    """Collect attachments with error isolation and safe ordering."""

    async def _safe_call(attachment: Attachment) -> message.DeveloperMessage | None:
        try:
            return await attachment(session)
        except Exception:
            name = getattr(attachment, "__name__", repr(attachment))
            logger.warning("Attachment %s failed", name, exc_info=True)
            return None

    sequential: list[Attachment] = []
    parallel: list[Attachment] = []
    for attachment in attachments:
        name = getattr(attachment, "__name__", "")
        if name in _SEQUENTIAL_ATTACHMENTS:
            sequential.append(attachment)
        else:
            parallel.append(attachment)

    results: list[message.DeveloperMessage | None] = []
    for attachment in sequential:
        results.append(await _safe_call(attachment))

    if parallel:
        results.extend(await asyncio.gather(*[_safe_call(attachment) for attachment in parallel]))

    return [result for result in results if result is not None]
