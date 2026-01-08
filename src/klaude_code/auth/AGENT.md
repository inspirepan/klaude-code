# Adding a New OAuth Provider

This document describes all the files and changes required to add a new OAuth-based authentication provider (like `antigravity`, `codex`, or `claude`).

## Overview

Adding a new OAuth provider requires changes in these areas:

1. **Protocol Registration** - Register the new protocol enum
2. **Auth Module** - Create OAuth flow, token manager, and exceptions
3. **LLM Client** - Implement the LLM client for the new protocol
4. **Config Integration** - Update config validation to recognize OAuth protocols
5. **CLI Commands** - Add login/logout support
6. **Model List Display** - Show OAuth status in `klaude list`
7. **Builtin Config** - Add provider and models to builtin config

---

## 1. Protocol Registration

### `src/klaude_code/protocol/llm_param.py`

Add the new protocol to the `LLMClientProtocol` enum:

```python
class LLMClientProtocol(Enum):
    # ... existing protocols ...
    ANTIGRAVITY = "antigravity"  # Add new protocol
```

---

## 2. Auth Module

Create a new directory under `src/klaude_code/auth/<provider_name>/` with these files:

### `src/klaude_code/auth/<provider>/pkce.py` (if using PKCE)

PKCE utilities for OAuth flow:

```python
def generate_pkce() -> tuple[str, str]:
    """Generate PKCE code verifier and challenge.
    Returns: Tuple of (verifier, challenge).
    """
```

### `src/klaude_code/auth/<provider>/exceptions.py`

Define provider-specific exceptions:

```python
class <Provider>AuthError(Exception): ...
class <Provider>NotLoggedInError(<Provider>AuthError): ...
class <Provider>TokenExpiredError(<Provider>AuthError): ...
class <Provider>OAuthError(<Provider>AuthError): ...
```

### `src/klaude_code/auth/<provider>/token_manager.py`

Token storage using base classes:

```python
from klaude_code.auth.base import BaseAuthState, BaseTokenManager

class <Provider>AuthState(BaseAuthState):
    """Add provider-specific fields like project_id, email, etc."""
    project_id: str
    email: str | None = None

class <Provider>TokenManager(BaseTokenManager[<Provider>AuthState]):
    @property
    def storage_key(self) -> str:
        return "<provider>"  # Key in ~/.klaude/klaude-auth.json
```

### `src/klaude_code/auth/<provider>/oauth.py`

OAuth flow implementation:

```python
class <Provider>OAuth:
    def login(self) -> <Provider>AuthState: ...
    def refresh(self) -> <Provider>AuthState: ...
    def ensure_valid_token(self) -> tuple[str, str]: ...
    def get_api_key_json(self) -> str: ...  # For JSON-encoded credentials
```

### `src/klaude_code/auth/<provider>/__init__.py`

Export public API:

```python
from klaude_code.auth.<provider>.exceptions import ...
from klaude_code.auth.<provider>.oauth import <Provider>OAuth
from klaude_code.auth.<provider>.token_manager import <Provider>AuthState, <Provider>TokenManager

__all__ = [...]
```

### `src/klaude_code/auth/__init__.py`

Add exports for the new provider.

---

## 3. LLM Client

Create a new directory under `src/klaude_code/llm/<provider>/` with these files:

### `src/klaude_code/llm/<provider>/input.py`

Message conversion to the provider's API format.

### `src/klaude_code/llm/<provider>/client.py`

LLM client implementation:

```python
from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.llm.registry import register

@register(llm_param.LLMClientProtocol.<PROVIDER>)
class <Provider>Client(LLMClientABC):
    def __init__(self, config: llm_param.LLMConfigParameter):
        # Initialize token manager and OAuth
        self._token_manager = <Provider>TokenManager()
        self._oauth = <Provider>OAuth(self._token_manager)

    def _get_credentials(self) -> tuple[str, str]:
        """Get credentials, auto-refreshing if needed."""
        return self._oauth.ensure_valid_token()

    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        # Get credentials, make API call, return stream
```

### `src/klaude_code/llm/<provider>/__init__.py`

Export the client class.

### `src/klaude_code/llm/registry.py`

Register the protocol to module mapping:

```python
_PROTOCOL_MODULES: dict[llm_param.LLMClientProtocol, str] = {
    # ... existing mappings ...
    llm_param.LLMClientProtocol.<PROVIDER>: "klaude_code.llm.<provider>",
}
```

---

## 4. Config Integration

### `src/klaude_code/config/config.py`

#### `ProviderConfig.is_api_key_missing()`

Add the new protocol to the OAuth check:

```python
def is_api_key_missing(self) -> bool:
    # ... existing checks ...
    
    if self.protocol == LLMClientProtocol.<PROVIDER>:
        from klaude_code.auth.<provider>.token_manager import <Provider>TokenManager
        token_manager = <Provider>TokenManager()
        state = token_manager.get_state()
        return state is None
```

#### `Config.resolve_model_location_prefer_available()`

Add the protocol to the "no API key required" set:

```python
if (
    provider.protocol
    not in {
        llm_param.LLMClientProtocol.CODEX_OAUTH,
        llm_param.LLMClientProtocol.CLAUDE_OAUTH,
        llm_param.LLMClientProtocol.<PROVIDER>,  # Add here
        llm_param.LLMClientProtocol.BEDROCK,
    }
    and not api_key
):
```

#### `Config.get_model_config()`

Same change as above - add protocol to the set.

---

## 5. CLI Commands

### `src/klaude_code/cli/auth_cmd.py`

#### `_select_provider()`

Add to the provider selection menu:

```python
SelectItem(
    title=[("", "<Provider Name> "), ("ansibrightblack", "[OAuth]\n")],
    value="<provider>",
    search_text="<provider>",
),
```

#### `_build_provider_help()`

Add provider name to help text:

```python
names = ["codex", "claude", "<provider>"] + [...]
```

#### `login_command()`

Add login case:

```python
case "<provider>":
    from klaude_code.auth.<provider>.oauth import <Provider>OAuth
    from klaude_code.auth.<provider>.token_manager import <Provider>TokenManager

    token_manager = <Provider>TokenManager()
    # Check existing login, run OAuth flow, display result
```

#### `logout_command()`

Add logout case and update help text:

```python
provider: str = typer.Argument("codex", help="Provider to logout (codex|claude|<provider>)")

case "<provider>":
    from klaude_code.auth.<provider>.token_manager import <Provider>TokenManager
    token_manager = <Provider>TokenManager()
    # Check login status, confirm, delete tokens
```

---

## 6. Model List Display

### `src/klaude_code/cli/list_model.py`

#### Add status display function

```python
def _get_<provider>_status_rows() -> list[tuple[Text, Text]]:
    """Get <Provider> OAuth login status as (label, value) tuples."""
    from klaude_code.auth.<provider>.token_manager import <Provider>TokenManager

    rows: list[tuple[Text, Text]] = []
    token_manager = <Provider>TokenManager()
    state = token_manager.get_state()

    if state is None:
        # Show "Not logged in" with hint
    elif state.is_expired():
        # Show "Token expired" with hint
    else:
        # Show "Logged in" with details (email, project, expires)

    return rows
```

#### `_build_provider_info_panel()`

Add status display:

```python
if provider.protocol == LLMClientProtocol.<PROVIDER>:
    for label, value in _get_<provider>_status_rows():
        info_table.add_row(label, value)
```

---

## 7. Builtin Config

### `src/klaude_code/config/assets/builtin_config.yaml`

Add provider and models:

```yaml
- provider_name: <provider>
  protocol: <provider>
  model_list:
  - model_name: model-a
    model_id: actual-model-id
    context_limit: 200000
    max_tokens: 64000
    thinking:
      type: enabled
      budget_tokens: 10240
  - model_name: model-b
    model_id: another-model-id
    context_limit: 1048576
```

---

## Checklist

When adding a new OAuth provider, ensure you've completed:

- [ ] Add protocol enum to `llm_param.py`
- [ ] Create `auth/<provider>/` module (pkce, exceptions, token_manager, oauth, __init__)
- [ ] Update `auth/__init__.py` exports
- [ ] Create `llm/<provider>/` module (input, client, __init__)
- [ ] Register protocol in `llm/registry.py`
- [ ] Update `config.py` - `is_api_key_missing()` method
- [ ] Update `config.py` - `resolve_model_location_prefer_available()` method
- [ ] Update `config.py` - `get_model_config()` method
- [ ] Update `auth_cmd.py` - provider selection, login, logout
- [ ] Update `list_model.py` - status display function and panel
- [ ] Add provider/models to `builtin_config.yaml`
- [ ] Run `make lint` to verify all changes
