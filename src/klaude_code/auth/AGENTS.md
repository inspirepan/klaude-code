# Authentication Module Guidelines

The auth layer owns credential persistence and provider-specific OAuth mechanics. User-facing
login/logout orchestration lives in `app/auth_flow.py`; the CLI and TUI commands delegate to it.

## Current Authentication Modes

- API keys are stored in the `env` section of `~/.klaude/klaude-auth.json` by `auth/env.py`.
  Real environment variables take precedence over stored values.
- Codex OAuth state is managed by `auth/codex/` and supports multiple named accounts.
- AWS Bedrock and Google Vertex use structured credential fields configured through the shared
  auth flow; they are not OAuth providers.
- `auth/removed_provider.py` only supports cleanup of credentials left by removed providers.

## Adding an OAuth Protocol

An OAuth-backed LLM protocol crosses several layers. Keep provider mechanics in this package and
wire higher-level behavior at the owning layer:

1. **Protocol**: add the value to `protocol/llm_param.py::LLMClientProtocol`.
2. **Auth implementation**: add `auth/<provider>/` with the provider's state, token manager,
   OAuth flow, exceptions, and public exports. Reuse `BaseAuthState` and `BaseTokenManager` from
   `auth/base.py`; add PKCE helpers only when the protocol uses PKCE.
3. **LLM client**: implement or reuse a client under `llm/`, decorate it with
   `llm.registry.register()`, and add its lazy module mapping to `_PROTOCOL_MODULES`.
4. **Credential availability**: teach `config/config.py::ProviderConfig.is_api_key_missing()` how
   to determine whether the OAuth state exists. Token refresh remains an LLM-client concern.
5. **Login/logout flow**: add provider cases to `app/auth_flow.py`. Keep `cli/auth_cmd.py` and the
   TUI command classes as thin delegates.
6. **Provider selector**: add the provider and its status rendering to
   `tui/command/auth_selector.py`.
7. **Model display**: update `cli/list_model.py` when the provider needs auth or usage details that
   generic API-key rendering cannot show.
8. **Built-in config**: add the provider and models to `config/assets/builtin_config.yaml`.

Do not add a new OAuth protocol merely to support another OpenAI- or Anthropic-compatible API-key
endpoint. Those should normally be a provider configuration using an existing protocol.

## Token Storage and Refresh

- Use a unique `BaseTokenManager.storage_key`; never store tokens in user config or session data.
- Keep provider-specific locking and account semantics inside the token manager/OAuth classes.
- Availability checks should only establish that credentials exist. Refresh expired tokens at the
  provider boundary immediately before a request, as `CodexClient` does.
- Never log raw access tokens, refresh tokens, authorization codes, or API keys.

## Validation

Add focused coverage at each changed boundary. Existing examples are:

- `tests/auth/test_codex_token_manager.py`
- `tests/app/test_auth_flow.py`
- `tests/cli/test_cli_auth_cmd.py`
- `tests/tui/test_auth_selector.py`
- `tests/config/test_config.py`

Run the focused tests first, then `make lint` for cross-layer and type checks.
