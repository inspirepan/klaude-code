"""Token storage and management for Sign in with ChatGPT."""

import uuid
from typing import Any

from filelock import FileLock
from pydantic import Field

from klaude_code.auth.base import LOCK_TIMEOUT_SECONDS, BaseAuthState, BaseTokenManager

DEVICE_ID_KEY = "chatgpt_device_id"


class ChatGPTAuthState(BaseAuthState):
    """Stored authentication state for a ChatGPT subscription."""

    client_id: str
    scopes: list[str] = Field(default_factory=list)
    id_token: str | None = None


class ChatGPTTokenManager(BaseTokenManager[ChatGPTAuthState]):
    """Manage the single Sign in with ChatGPT credential."""

    @property
    def storage_key(self) -> str:
        return "chatgpt"

    def _create_state(self, data: dict[str, Any]) -> ChatGPTAuthState:
        return ChatGPTAuthState.model_validate(data)

    def get_or_create_device_id(self) -> str:
        """Return this installation's stable host ID.

        The value survives logout, so every sign-in from the same installation
        reports the same `ext_agent_host_id`.
        """
        with FileLock(self._get_lock_file(), timeout=LOCK_TIMEOUT_SECONDS):
            store = self._load_store()
            saved = store.get(DEVICE_ID_KEY)
            if isinstance(saved, str):
                try:
                    return str(uuid.UUID(saved))
                except ValueError:
                    pass

            device_id = str(uuid.uuid4())
            store[DEVICE_ID_KEY] = device_id
            self._save_store(store)
            return device_id
