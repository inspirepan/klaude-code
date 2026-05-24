"""Token storage and management for Codex authentication."""

import time
from pathlib import Path
from typing import Any, cast

from klaude_code.auth.base import BaseAuthState, BaseTokenManager


class CodexAuthState(BaseAuthState):
    """Stored authentication state for Codex."""

    account_id: str
    name: str = "default"
    created_at: int | None = None
    last_used_at: int | None = None


class CodexTokenManager(BaseTokenManager[CodexAuthState]):
    """Manage Codex OAuth tokens."""

    def __init__(self, auth_file: Path | None = None, account_name: str | None = None):
        super().__init__(auth_file)
        self.account_name = _normalize_account_name(account_name) if account_name is not None else None

    @property
    def storage_key(self) -> str:
        return "codex"

    def _create_state(self, data: dict[str, Any]) -> CodexAuthState:
        return CodexAuthState.model_validate(data)

    def _load_codex_store(self) -> dict[str, Any] | None:
        data: Any = self._load_store().get(self.storage_key)
        if not isinstance(data, dict):
            return None

        if "accounts" in data:
            accounts = data.get("accounts")
            if isinstance(accounts, dict):
                return cast(dict[str, Any], data)
            return None

        if "access_token" in data:
            legacy_state = self._create_state(cast(dict[str, Any], data))
            state_data = legacy_state.model_copy(update={"name": "default"}).model_dump(mode="json")
            return {"active": "default", "accounts": {"default": state_data}}

        return None

    def _save_codex_store(self, codex_store: dict[str, Any]) -> None:
        store = self._load_store()
        store[self.storage_key] = codex_store
        self._save_store(store)

    def load(self) -> CodexAuthState | None:
        """Load the selected Codex account state from file."""
        codex_store = self._load_codex_store()
        if codex_store is None:
            return None

        account_name = self.account_name or codex_store.get("active")
        if not isinstance(account_name, str):
            return None

        accounts = codex_store.get("accounts")
        if not isinstance(accounts, dict):
            return None

        data = accounts.get(account_name)
        if not isinstance(data, dict):
            return None

        try:
            self._state = self._create_state(cast(dict[str, Any], data))
            return self._state
        except ValueError:
            return None

    def save(
        self,
        state: CodexAuthState,
        account_name: str | None = None,
        *,
        set_active: bool = True,
    ) -> None:
        """Save a Codex account state."""
        resolved_name = _normalize_account_name(account_name or self.account_name or state.name)
        now = int(time.time())
        state = state.model_copy(
            update={
                "name": resolved_name,
                "created_at": state.created_at or now,
                "last_used_at": now,
            }
        )

        codex_store = self._load_codex_store() or {"active": resolved_name, "accounts": {}}
        accounts = codex_store.get("accounts")
        if not isinstance(accounts, dict):
            accounts = {}
        accounts[resolved_name] = state.model_dump(mode="json")
        codex_store["accounts"] = accounts
        if set_active or not isinstance(codex_store.get("active"), str):
            codex_store["active"] = resolved_name
        self._save_codex_store(codex_store)
        self._state = state

    def delete(self, account_name: str | None = None) -> None:
        """Delete one stored Codex account. Defaults to the selected or active account."""
        codex_store = self._load_codex_store()
        if codex_store is None:
            self._state = None
            return

        accounts = codex_store.get("accounts")
        if not isinstance(accounts, dict):
            self._state = None
            return

        resolved_name = account_name or self.account_name or codex_store.get("active")
        if isinstance(resolved_name, str):
            accounts.pop(resolved_name, None)

        store = self._load_store()
        if not accounts:
            store.pop(self.storage_key, None)
        else:
            codex_store["accounts"] = accounts
            active = codex_store.get("active")
            if not isinstance(active, str) or active not in accounts:
                codex_store["active"] = sorted(accounts)[0]
            store[self.storage_key] = codex_store

        if not store:
            if self.auth_file.exists():
                self.auth_file.unlink()
        else:
            self._save_store(store)
        self._state = None

    def list_accounts(self) -> list[CodexAuthState]:
        """List all stored Codex accounts."""
        codex_store = self._load_codex_store()
        if codex_store is None:
            return []
        accounts = codex_store.get("accounts")
        if not isinstance(accounts, dict):
            return []

        states: list[CodexAuthState] = []
        for name, data in accounts.items():
            if not isinstance(name, str) or not isinstance(data, dict):
                continue
            try:
                state = self._create_state(cast(dict[str, Any], data))
            except ValueError:
                continue
            states.append(state)
        return sorted(states, key=lambda state: state.name.casefold())

    def get_active_account_name(self) -> str | None:
        """Return the active Codex account name, if configured."""
        codex_store = self._load_codex_store()
        if codex_store is None:
            return None
        active = codex_store.get("active")
        return active if isinstance(active, str) else None

    def set_active_account(self, account_name: str) -> CodexAuthState:
        """Set the active Codex account and return its state."""
        resolved_name = _normalize_account_name(account_name)
        codex_store = self._load_codex_store()
        if codex_store is None:
            raise ValueError("No Codex accounts are logged in")
        accounts = codex_store.get("accounts")
        if not isinstance(accounts, dict) or resolved_name not in accounts:
            raise ValueError(f"Codex account '{resolved_name}' is not logged in")
        codex_store["active"] = resolved_name
        self._save_codex_store(codex_store)
        self.clear_cached_state()
        state = self.get_state()
        if state is None:
            raise ValueError(f"Codex account '{resolved_name}' is not logged in")
        return state


def _normalize_account_name(account_name: str) -> str:
    name = account_name.strip()
    if not name:
        raise ValueError("Codex account name cannot be empty")
    return name
