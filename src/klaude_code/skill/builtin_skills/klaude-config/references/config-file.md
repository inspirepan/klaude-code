---
name: config-file
description: klaude-config.yaml structure, model selection, credentials, and merging rules
---

# Configuration File Reference

Path: `~/.klaude/klaude-config.yaml` (open with `klaude config`). An example is generated at `~/.klaude/klaude-config.example.yaml` if absent; it may not reflect later upgrades. For current builtins, see `src/klaude_code/config/assets/builtin_config.yaml` in the klaude-code source.

## Example

```yaml
main_model: [sonnet, gpt-6.1-sol] # selectors are tried in order
fast_model: haiku
compact_model: gemini-flash
sub_agent_models:
  finder: [haiku, gemini-flash]
  code-reviewer: opus
theme: dark
provider_list:
- provider_name: my-provider
  protocol: openai                  # required for a new provider
  api_key: ${MY_API_KEY}
  base_url: https://api.example.com/v1
  model_list:
  - model_name: my-model            # selector
    model_id: actual-model-id       # identifier sent to the API
    max_tokens: 16000
    context_limit: 200000
    supports_vision: false
    cost: { input: 1, output: 10, cache_read: 0.1 }
```

Model IDs, limits, and costs for custom providers must match the actual service.

## Configure a Custom Endpoint

1. Confirm the service's protocol, SDK base URL, model ID, model output token limit (`max_tokens`), and authentication requirements. Ask for missing information; an endpoint and key alone do not establish the protocol or model. If `max_tokens` is omitted, the current implementation defaults to 32000; a value above the service's allowed maximum will be rejected. Use a distinct `provider_name` and `model_name`, or confirm an intended override of an existing name. Ask before changing the default model.
2. Distinguish a complete request endpoint from `base_url`. For ordinary non-Azure clients, Klaude passes `base_url` to the OpenAI or Anthropic SDK, which adds its request path. For example, OpenAI base `https://api.example.com/v1` normally produces `/v1/chat/completions` or `/v1/responses`; Anthropic base `https://api.example.com` normally produces `/v1/messages`. Confirm the service's documented URL and compatibility; do not blindly strip a suffix or assume an arbitrary endpoint works. Azure uses separate endpoint handling.
3. Use an environment variable for the key, referenced as `${MY_API_KEY}`. Ask the user to supply it through their environment or an appropriate secret manager; never print it, put it in a command argument, shell history, logs, or the example YAML. For supported builtin credential names, `klaude login <provider>` prompts with hidden input. Custom provider names are not generally accepted by `klaude login`; see Credentials below.
4. With authorization to edit, inspect the existing user configuration without exposing secrets, then add or update only the intended provider and model. Preserve other settings and ordering. If the file is invalid or cannot be safely inspected, stop and ask before overwriting it. Add a provider-qualified `main_model` only if requested. When guiding, show the user how to merge the relevant entry rather than replace the file.
5. Validate the YAML and installed version's schema locally, then use `klaude models --all` to inspect the model and availability. These checks do not verify the remote endpoint or key. Request explicit authorization before any remote API test, which may incur charges.

The following are alternative entries under `provider_list`; replace placeholders with confirmed service values. `model_name` is the local selector and `model_id` is sent to the service. The `max_tokens: 4096` values are examples; set each according to the service's actual limit. The URL shapes are illustrative, not a compatibility guarantee.

```yaml
provider_list:
  - provider_name: example-chat
    protocol: openai
    base_url: https://api.example.com/v1
    api_key: ${MY_API_KEY}
    model_list:
      - model_name: chat-model
        model_id: actual-chat-model-id
        max_tokens: 4096
  - provider_name: example-responses
    protocol: responses
    base_url: https://api.example.com/v1
    api_key: ${MY_API_KEY}
    model_list:
      - model_name: responses-model
        model_id: actual-responses-model-id
        max_tokens: 4096
  - provider_name: example-anthropic
    protocol: anthropic
    base_url: https://api.example.com
    api_key: ${MY_API_KEY}
    model_list:
      - model_name: messages-model
        model_id: actual-messages-model-id
        max_tokens: 4096
```

## Model Selection

| Form | Example | Behavior |
|------|---------|----------|
| Unqualified | `sonnet` | Tries matching available providers in `provider_list` order |
| Provider-qualified | `sonnet@anthropic` | Selects a specific provider |
| Variant | `opus:max` | Selects a configured model variant |
| Preference list | `[sonnet, gpt-6.1-sol]` | Tries each selector and its matching providers in order |

Use `klaude models` for configured available models and role bindings, or `klaude models --all` to include disabled models and unavailable providers. `klaude models --json --all` provides machine-readable output. These inspect local configuration; availability is not a live API check.

`/model` moves the selected model to the front of the saved `main_model` preference, preserving the remaining fallback order. `/sub-agent-model` changes sub-agent preferences. Missing user entries use built-in role defaults. A native sub-agent inherits the parent model when its role preference is unavailable; a headless agent fails to start if every model in its role preference list is unavailable.

## Credentials

`klaude login` opens the provider chooser; `klaude login <provider>` configures a provider. For OAuth, use `klaude login chatgpt` or `klaude login xai`. API keys saved through login are stored in `~/.klaude/klaude-auth.json`.

Login recognizes the installed version's supported builtin credential names, not arbitrary custom provider names. For a custom credential, use an environment variable or, where appropriate and authorized, Klaude's `klaude_code.auth.env.set_auth_env(name, value)` mechanism; it updates the `env` section of the auth store. The store is ordinary JSON and the current implementation does not set restrictive permissions itself. Protect the file and avoid passing the value through command arguments or exposing existing credentials. Prefer the user's own secure input mechanism over copying a key from chat.

A value such as `${MY_API_KEY}` resolves from the environment first, then the stored credential. `${FIRST_VAR|SECOND_VAR}` tries each name in order, checking environment and stored credentials for each name. See [builtin-providers.md](builtin-providers.md) for provider-specific credentials.

## Supported Protocols

| Protocol | API |
|----------|-----|
| `anthropic` | Anthropic Messages |
| `responses` | OpenAI Responses |
| `openai` | OpenAI Chat Completions |
| `openrouter` | OpenRouter |
| `google` | Google Gemini |
| `google_vertex` | Google Vertex AI |
| `bedrock` | AWS Bedrock for Claude |
| `chatgpt_oauth` | ChatGPT subscription OAuth |
| `xai_oauth` | xAI subscription OAuth |

## Merging Rules

User config merges over builtins at startup:

- `provider_list` entries match by `provider_name`; user-listed providers come first in the merged order. Matching models merge by `model_name`; new models append. Unspecified fields retain builtin values.
- A new provider needs `protocol`; an unknown provider without it is skipped.
- `main_model`, `fast_model`, `compact_model`, `theme`, and `sub_agent_model_decision_tree` use the user value when set. `sub_agent_models` merges per key.
- `web_search.providers` replaces the builtin list and order; omitted fields on matching entries inherit builtin values. An empty list disables the chain.
- Saving writes user overrides rather than the entire merged builtin configuration.
- Klaude's save rereads the user file and applies changes relative to its loaded baseline; an unreadable or invalid file falls back to a snapshot overwrite. Provider entries are maintained in the user configuration rather than synced from edits to the merged provider list.

## Model Config Fields

| Field | Description |
|-------|-------------|
| `model_name`, `model_alias` | Selector and alternative names |
| `model_id` | Actual identifier sent to the API |
| `max_tokens`, `context_limit` | Maximum output tokens and context window |
| `disabled` | Disable the model |
| `temperature`, `effort`, `verbosity` | Sampling, output effort, and verbosity settings |
| `thinking` | Reasoning settings, including `type`, `reasoning_effort`, and `budget_tokens` |
| `fast_mode`, `cache_retention` | Priority processing and prompt cache retention (`short` or `long`) |
| `supports_vision` | Image input support; defaults to `true` |
| `provider_routing` | OpenRouter routing preferences |
| `cost` | Per-million-token prices: `input`, `output`, `cache_read`, `cache_write`; optional `currency` and `peak` |

## Provider Config Fields

| Field | Description |
|-------|-------------|
| `provider_name`, `protocol` | Provider identifier and API protocol |
| `api_key`, `base_url`, `disabled` | Credentials, endpoint, and provider availability |
| `model_list` | Models belonging to this provider |
| `is_azure`, `azure_api_version` | Azure OpenAI settings |
| `google_application_credentials`, `google_cloud_project`, `google_cloud_location` | Google Vertex AI settings |
| `aws_access_key`, `aws_secret_key`, `aws_session_token`, `aws_region`, `aws_profile` | AWS Bedrock settings |

For the complete current schema and allowed values, see `src/klaude_code/config/config.py` and `src/klaude_code/protocol/llm_param.py` in the klaude-code source.
