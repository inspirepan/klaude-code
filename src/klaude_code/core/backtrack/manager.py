from dataclasses import dataclass


@dataclass
class BacktrackRequest:
    checkpoint_id: int
    note: str
    rationale: str


class BacktrackManager:
    """Manage backtrack requests and checkpoint metadata for a task run."""

    def __init__(self) -> None:
        self._pending: BacktrackRequest | None = None
        self._n_checkpoints: int = 0
        self._checkpoint_user_messages: dict[int, str] = {}

    def set_n_checkpoints(self, n: int) -> None:
        self._n_checkpoints = n

    @property
    def n_checkpoints(self) -> int:
        return self._n_checkpoints

    def sync_checkpoints(self, checkpoints: dict[int, str]) -> None:
        self._checkpoint_user_messages = dict(checkpoints)

    def register_checkpoint(self, checkpoint_id: int, user_message: str) -> None:
        self._checkpoint_user_messages[checkpoint_id] = user_message

    def get_checkpoint_user_message(self, checkpoint_id: int) -> str | None:
        return self._checkpoint_user_messages.get(checkpoint_id)

    def send_backtrack(self, checkpoint_id: int, note: str, rationale: str) -> str:
        if self._pending is not None:
            raise ValueError("Only one backtrack can be pending at a time")
        if checkpoint_id < 0 or checkpoint_id >= self._n_checkpoints:
            raise ValueError(f"Invalid checkpoint {checkpoint_id}, available: 0-{self._n_checkpoints - 1}")
        if checkpoint_id not in self._checkpoint_user_messages:
            raise ValueError("Checkpoint is no longer available")
        self._pending = BacktrackRequest(checkpoint_id=checkpoint_id, note=note, rationale=rationale)
        return "Backtrack scheduled"

    def fetch_pending(self) -> BacktrackRequest | None:
        pending = self._pending
        self._pending = None
        return pending
