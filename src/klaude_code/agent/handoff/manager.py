from dataclasses import dataclass


@dataclass
class HandoffRequest:
    goal: str

class HandoffManager:
    """Manage pending handoff requests for a task run."""

    def __init__(self) -> None:
        self._pending: HandoffRequest | None = None

    def send_handoff(self, goal: str) -> str:
        if self._pending is not None:
            raise ValueError("Only one handoff can be pending at a time")
        self._pending = HandoffRequest(goal=goal)
        return "Handoff scheduled"

    def fetch_pending(self) -> HandoffRequest | None:
        pending = self._pending
        self._pending = None
        return pending
