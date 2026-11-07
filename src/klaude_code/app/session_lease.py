"""OS-held execution leases, released automatically after process death."""

import fcntl
import hashlib
from pathlib import Path
from typing import IO


class SessionInUseError(ValueError):
    """The session is already owned by another process."""


class SessionLease:
    @staticmethod
    def _path(session_id: str) -> Path:
        name = hashlib.sha256(session_id.encode()).hexdigest()
        return Path.home() / ".klaude" / "run" / "sessions" / f"{name}.lock"

    @classmethod
    def is_active(cls, session_id: str) -> bool:
        """Probe an existing lease without creating files or holding execution."""
        try:
            with cls._path(session_id).open("r") as file:
                try:
                    fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return True
        except FileNotFoundError:
            pass
        return False

    def __init__(self, session_id: str) -> None:
        path = self._path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._file: IO[str] = path.open("a+")
        try:
            fcntl.flock(self._file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._file.close()
            raise SessionInUseError(f"Session {session_id} is active in another Klaude process") from None

    def close(self) -> None:
        self._file.close()
