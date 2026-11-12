# Configuration reference

Klaude reads user configuration from `~/.klaude/klaude-config.yaml`. `klaude config` opens that file in your editor.

User settings merge with the [built-in configuration](../src/klaude_code/config/assets/builtin_config.yaml). Matching `provider_name` values inherit provider settings. Matching `model_name` values override individual model settings. Omitted fields keep their built-in values.

## Credentials

`klaude login` lists providers and configures credentials. `klaude login chatgpt` signs in with a ChatGPT subscription. `klaude logout chatgpt` removes that login.

API keys configured through login are stored in `~/.klaude/klaude-auth.json`. Environment variables take precedence over stored keys. Provider configuration supports `${VAR_NAME}` references and `${FIRST_VAR|SECOND_VAR}` alternatives.

Common credential variables include:

| Provider | Environment variables |
| --- | --- |
| Anthropic | `ANTHROPIC_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| OpenRouter | `OPENROUTER_API_KEY` |
| Google | `GEMINI_API_KEY` |
| DeepSeek | `DEEPSEEK_API_KEY` |
| Moonshot | `MOONSHOT_API_KEY` |
| MiniMax | `MINIMAX_API_KEY` |
| OpenCode Go | `OPENCODE_API_KEY` |
| Azure OpenAI Responses | `AZURE_OPENAI_API_KEY` and `AZURE_OPENAI_ENDPOINT` or `AZURE_OPENAI_BASE_URL` |
| AWS Bedrock | `AWS_BEDROCK_ACCESS_KEY_ID`, `AWS_BEDROCK_SECRET_ACCESS_KEY`, and `AWS_BEDROCK_REGION` |
| Google Vertex AI | `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT`, and `GOOGLE_CLOUD_LOCATION` |

Bedrock also accepts the standard `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_REGION` variables. The built-in configuration contains the full provider list, including disabled providers. `klaude models --all` includes models whose providers lack credentials.

## Model preferences

The model settings accept a selector or an ordered list of selectors:

```yaml
main_model:
  - sonnet
  - gpt-6.1-sol

fast_model: haiku
compact_model: gemini-flash
```

Use `model_name@provider` to select a provider, such as `sonnet@anthropic`. An unqualified selector expands into available providers in `provider_list` order. Klaude tries those candidates before the next selector in the list.

Runtime fallback handles non-retryable failures such as quota, billing, permission, and unavailable-model errors. Switching models with `/model` moves the selected model to the front of `main_model`, preserving the remaining fallback order.

The helper settings have these roles:

| Setting | Role |
| --- | --- |
| `main_model` | Main conversation |
| `fast_model` | Session-title generation |
| `compact_model` | Compaction and helper tasks |

An unavailable helper preference falls back to its built-in default, then to the main model. An unset helper preference inherits the main model.

## Sub-agent models

`sub_agent_models` maps registered agent types to model preferences:

```yaml
sub_agent_models:
  general-purpose: sonnet
  finder:
    - haiku
    - gemini-flash
  code-reviewer: opus
```

The registered types are:

| Type | Role |
| --- | --- |
| `general-purpose` | Autonomous implementation and other multi-step tasks |
| `general-purpose-fork-context` | General-purpose work with the parent's conversation history |
| `finder` | Codebase search and exploration |
| `code-reviewer` | Correctness review |
| `code-maintenance-reviewer` | Maintainability review |

Missing entries use the built-in role defaults. If a role preference is unavailable, Klaude tries its built-in default before inheriting the parent model. `/sub-agent-model` changes these preferences interactively. `klaude models` shows role bindings.

## Custom providers and models

The following example adds a model to an existing provider and defines a separate OpenAI-compatible provider:

```yaml
provider_list:
  - provider_name: openrouter
    model_list:
      - model_name: custom-coder
        model_id: vendor/model-id
        context_limit: 128000
        cost: { input: 0.3, output: 0.9 }

  - provider_name: local
    protocol: openai
    base_url: http://localhost:8000/v1
    api_key: ${LOCAL_MODEL_API_KEY}
    model_list:
      - model_name: local-coder
        model_id: local-model-id
        context_limit: 32768
        supports_vision: false
```

The model IDs and limits above are placeholders for the server's actual values. Prices are per million tokens. `supports_vision` defaults to `true`; text-only models need `false`.

Supported protocol values are:

| Value | API |
| --- | --- |
| `anthropic` | Anthropic Messages |
| `openai` | OpenAI Chat Completions |
| `responses` | OpenAI Responses |
| `openrouter` | OpenRouter, including reasoning details |
| `chatgpt_oauth` | ChatGPT subscription authentication |
| `xai_oauth` | xAI subscription authentication |
| `google` | Google Gemini |
| `google_vertex` | Google Vertex AI |
| `bedrock` | AWS Bedrock for Claude |

The configuration schema is defined in [config.py](../src/klaude_code/config/config.py) and [llm_param.py](../src/klaude_code/protocol/llm_param.py). The [model checklist](add-model.md) covers changes to the built-in catalog.

## WebSearch providers

`/manage-providers` controls which WebSearch providers are enabled and their order. The default order is Parallel, Exa, Brave, DeepSeek, then OpenAI. Providers without credentials are skipped. Request failures fall back to the next provider.

| Search provider | Environment variable |
| --- | --- |
| Parallel | `PARALLEL_API_KEY` |
| Exa | `EXA_API_KEY` |
| Brave | `BRAVE_API_KEY` |
| DeepSeek | `DEEPSEEK_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |

DeepSeek uses its standalone Search API. OpenAI search uses a model.

## Skill directories

The bundled skills `klaude-config` and `klaude-session-logs` sync to `~/.klaude/skills/`. A manifest protects local edits and user-deleted skills from being overwritten or restored. Other skills can be installed independently. User directories are searched in this order, with later entries overriding earlier entries of the same name:

1. `~/.claude/skills/`
2. `~/.klaude/skills/`
3. `~/.agents/skills/`
4. `~/.config/agents/skills/`

Project discovery searches ancestor directories for `.claude/skills/` and `.agents/skills/`. Nearer directories override more distant directories. In the same directory, `.agents/skills/` takes precedence. Hidden child directories are skipped, and directory symlinks are supported.
