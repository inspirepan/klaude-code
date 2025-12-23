# Klaude Code

Minimal code agent CLI.

## Features
- **Multi-provider**: Anthropic, OpenAI Responses API, OpenRouter
- **Keep reasoning item in context**: Interleaved thinking support
- **Model-aware tools**: Claude Code tools for Sonnet, `apply_patch` for GPT-5/Codex
- **Structured sub-agent output**: Define JSON schema, get schema-compliant responses via constrained decoding
- **Recursive `@file` mentions**: Circular dependency protection, relative path resolution
- **Reminders**: Cooldown-based todo tracking and instruction reinforcement
- **External file sync**: Monitoring for external edits (linter, manual)
- **Interrupt handling**: Ctrl+C preserves partial responses and synthesizes tool cancellation results
- **Output truncation**: Large outputs saved to file system with snapshot links
- **Skills**: Built-in + user + project Agent Skills (with implicit invocation by Skill tool or explicit invocation by typing `$`)
- **Sessions**: Resumable with `--continue`
- **Extras**: Slash commands, sub-agents, image paste, terminal notifications, auto-theming

## Installation

```bash
uv tool install klaude-code
```

To update:

```bash
uv tool upgrade klaude-code
```

Or use the built-in alias command:

```bash
klaude update
klaude upgrade
```

To show version:

```bash
klaude --version
klaude -v
klaude version
```

## Usage

### Interactive Mode

```bash
klaude [--model <name>] [--select-model]
```

**Options:**
- `--version`/`-V`/`-v`: Show version and exit.
- `--model`/`-m`: Preferred model name (exact match picks immediately; otherwise opens the interactive selector filtered by this value).
- `--select-model`/`-s`: Open the interactive model selector at startup (shows all models unless `--model` is also provided).
- `--continue`/`-c`: Resume the most recent session.
- `--resume`/`-r`: Select a session to resume for this project.
- `--vanilla`: Minimal mode with only basic tools (Bash, Read, Edit) and no system prompts.

**Model selection behavior:**
- Default: uses `main_model` from config.
- `--select-model`: always prompts you to pick.
- `--model <value>`: tries to resolve `<value>` to a single model; if it can't, it prompts with a filtered list (and falls back to showing all models if there are no matches).

**Debug Options:**
- `--debug`/`-d`: Enable debug mode with verbose logging and LLM trace.
- `--debug-filter`: Filter debug output by type (comma-separated).


### Configuration

#### Quick Start (Zero Config)

Klaude comes with built-in provider configurations. Just set an API key environment variable and start using it:

```bash
# Pick one (or more) of these:
export ANTHROPIC_API_KEY=sk-ant-xxx      # Claude models
export OPENAI_API_KEY=sk-xxx             # GPT models
export OPENROUTER_API_KEY=sk-or-xxx      # OpenRouter (multi-provider)
export DEEPSEEK_API_KEY=sk-xxx           # DeepSeek models
export MOONSHOT_API_KEY=sk-xxx           # Moonshot/Kimi models

# Then just run:
klaude
```

On first run, you'll be prompted to select a model. Your choice is saved as `main_model`.

#### Built-in Providers

| Provider    | Env Variable          | Models                                                                        |
|-------------|-----------------------|-------------------------------------------------------------------------------|
| anthropic   | `ANTHROPIC_API_KEY`   | sonnet, opus                                                                  |
| openai      | `OPENAI_API_KEY`      | gpt-5.2                                                                       |
| openrouter  | `OPENROUTER_API_KEY`  | gpt-5.2, gpt-5.2-fast, gpt-5.1-codex-max, sonnet, opus, haiku, kimi, gemini-* |
| deepseek    | `DEEPSEEK_API_KEY`    | deepseek                                                                      |
| moonshot    | `MOONSHOT_API_KEY`    | kimi@moonshot                                                                 |
| codex       | N/A (OAuth)           | gpt-5.2-codex                                                                 |

List all configured providers and models:

```bash
klaude list
```

Models from providers without a valid API key are shown as dimmed/unavailable.

#### Custom Configuration

User config file: `~/.klaude/klaude-config.yaml`

Open in editor:

```bash
klaude config
```

##### Adding Models to Built-in Providers

You can add custom models to existing providers without redefining the entire provider:

```yaml
# Just specify provider_name and your new models - no need for protocol/api_key
provider_list:
  - provider_name: openrouter
    model_list:
      - model_name: my-custom-model
        model_params:
          model: some-provider/some-model-id
          context_limit: 200000
```

Your models are merged with built-in models. To override a built-in model, use the same `model_name`.

##### Overriding Provider Settings

Override provider-level settings (like api_key) while keeping built-in models:

```yaml
provider_list:
  - provider_name: anthropic
    api_key: sk-my-custom-key  # Override the default ${ANTHROPIC_API_KEY}
    # Built-in models (sonnet, opus) are still available
```

##### Adding New Providers

For providers not in the built-in list, you must specify `protocol`:

```yaml
provider_list:
  - provider_name: my-azure-openai
    protocol: openai
    api_key: ${AZURE_OPENAI_KEY}
    base_url: https://my-instance.openai.azure.com/
    is_azure: true
    azure_api_version: "2024-02-15-preview"
    model_list:
      - model_name: gpt-4-azure
        model_params:
          model: gpt-4
          context_limit: 128000
```

##### Full Example

```yaml
# User configuration - merged with built-in config
main_model: opus

sub_agent_models:
  oracle: gpt-4.1
  explore: sonnet
  task: opus
  webagent: sonnet

provider_list:
  # Add models to built-in openrouter
  - provider_name: openrouter
    model_list:
      - model_name: qwen-coder
        model_params:
          model: qwen/qwen-2.5-coder-32b-instruct
          context_limit: 131072

  # Add a completely new provider
  - provider_name: local-ollama
    protocol: openai
    base_url: http://localhost:11434/v1
    api_key: ollama
    model_list:
      - model_name: local-llama
        model_params:
          model: llama3.2
          context_limit: 8192
```

##### Supported Protocols

- `anthropic` - Anthropic Claude API
- `openai` - OpenAI-compatible API
- `responses` - OpenAI Responses API (for o-series, GPT-5, Codex)
- `openrouter` - OpenRouter API
- `codex` - OpenAI Codex CLI (OAuth-based)

List configured providers and models:

```bash
klaude list
```

### Session Management

Clean up sessions with few messages:

```bash
# Remove sessions with fewer than 5 messages (default)
klaude session clean

# Remove sessions with fewer than 10 messages
klaude session clean --min 10

# Remove all sessions for the current project
klaude session clean-all
```

### Slash Commands

Inside the interactive session (`klaude`), use these commands to streamline your workflow:

- `/dev-doc [feature]` - Generate a comprehensive execution plan for a feature.
- `/export` - Export last assistant message to a temp Markdown file.
- `/init` - Bootstrap a new project structure or module.
- `/model` - Switch the active LLM during the session.
- `/clear` - Clear the current conversation context.
- `/diff` - Show local git diff changes.
- `/help` - List all available commands.


### Input Shortcuts

| Key                  | Action                                      |
| -------------------- | ------------------------------------------- |
| `Enter`              | Submit input                                |
| `Shift+Enter`        | Insert newline (requires `/terminal-setup`) |
| `Ctrl+J`             | Insert newline                              |
| `Ctrl+V`             | Paste image from clipboard                  |
| `Left/Right`         | Move cursor (wraps across lines)            |
| `Backspace`          | Delete character or selected text           |
| `c` (with selection) | Copy selected text to clipboard             |

### Non-Interactive Headless Mode (exec)

Execute a single command without starting the interactive REPL:

```bash
# Direct input
klaude exec "what is 2+2?"

# Pipe input
echo "hello world" | klaude exec

# With model selection

# Exact model name (non-interactive)
echo "generate quicksort in python" | klaude exec --model gpt-5.1

# Partial/ambiguous name opens the interactive selector (filtered)
echo "generate quicksort in python" | klaude exec --model gpt
```
