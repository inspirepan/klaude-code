---
name: builtin-providers
description: Builtin provider credentials, protocols, and model discovery
---

# Builtin Providers

Run `klaude models` to see locally available models and role bindings. `klaude models --all` includes disabled models and unavailable providers; `--json` emits machine-readable output. Availability reflects local configuration and credentials, not a live request. For the current builtin catalog, provider order, model IDs, variants, prices, and default preferences, inspect `src/klaude_code/config/assets/builtin_config.yaml` in the klaude-code source. User configuration can override these defaults.

## Providers and Credentials

| Provider | Protocol | Credentials or login |
|----------|----------|----------------------|
| `youtu-anthropic` | `anthropic` | `YOUTU_API_KEY`; disabled by default |
| `anthropic` | `anthropic` | `ANTHROPIC_API_KEY` |
| `aws-bedrock` | `bedrock` | `AWS_BEDROCK_ACCESS_KEY_ID`, `AWS_BEDROCK_SECRET_ACCESS_KEY`, `AWS_BEDROCK_REGION`; falls back respectively to `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` |
| `openai` | `responses` | `OPENAI_API_KEY` |
| `azure-openai-responses` | `responses` | `AZURE_OPENAI_API_KEY`; override `base_url` with the actual URL in provider configuration |
| `google` | `google` | `GEMINI_API_KEY` |
| `google-vertex` | `google_vertex` | `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` |
| `deepseek` | `anthropic` | `DEEPSEEK_API_KEY` |
| `moonshot-cn` | `anthropic` | `MOONSHOT_API_KEY` |
| `moonshot-ai` | `openai` | `MOONSHOT_API_KEY` |
| `minimax` | `anthropic` | `MINIMAX_API_KEY` |
| `opencode-go` | `openai` | `OPENCODE_API_KEY` |
| `chatgpt` | `chatgpt_oauth` | `klaude login chatgpt` |
| `xai-grok-build` | `xai_oauth` | `klaude login xai` |
| `openrouter` | `openrouter` | `OPENROUTER_API_KEY` |

Bedrock also supports an `aws_profile` plus `aws_region` in provider configuration. The table describes builtin defaults; custom providers and overrides can use different credentials or endpoints.

Azure's builtin `base_url` uses `${AZURE_OPENAI_ENDPOINT|AZURE_OPENAI_BASE_URL}`, but `base_url` does not expand environment variables. Override it with the actual URL in provider configuration.

## Credential Setup

- Set the relevant environment variable, or run `klaude login` to choose a provider and save an API key in `~/.klaude/klaude-auth.json`.
- Use `klaude login chatgpt` or `klaude login xai` for subscription OAuth. `klaude logout <provider>` removes a login.
- Provider config can reference `${ENV_VAR}` or `${FIRST_VAR|SECOND_VAR}`. For each name, the environment takes precedence over stored credentials.

See [config-file.md](config-file.md) for configuration, model selection, and merge rules.
