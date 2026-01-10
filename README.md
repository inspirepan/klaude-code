# Klaude Code

Minimal code agent CLI.

## Features
- **Multi-provider**: Anthropic Message API, OpenAI Responses API, OpenRouter, ChatGPT Codex OAuth etc.
- **Keep reasoning item in context**: Interleaved thinking support
- **Model-aware tools**: Claude Code tool set for Opus, `apply_patch` for GPT-5/Codex
- **Reminders**: Cooldown-based todo tracking, instruction reinforcement and external file change reminder
- **Sub-agents**: Task, Explore, Web, ImageGen
- **Structured sub-agent output**: Main agent defines JSON schema and get schema-compliant responses via constrained decoding
- **Recursive `@file` mentions**: Circular dependency protection, relative path resolution
- **External file sync**: Monitoring for external edits (linter, manual)
- **Interrupt handling**: Ctrl+C preserves partial responses and synthesizes tool cancellation results
- **Output truncation**: Large outputs saved to file system with snapshot links
- **Agent Skills**: Built-in + user + project Agent Skills (with implicit invocation by Skill tool or explicit invocation by typing `$`)
- **Sessions**: Resumable with `--continue`
- **Mermaid diagrams**: Terminal image preview and Interactive local HTML viewer with zoom, pan, and SVG export
- **Extras**: Slash commands, sub-agents, image paste, terminal notifications, auto-theming

## Installation

```bash
uv tool install klaude-code
```

To update:

```bash
uv tool upgrade klaude-code
```

Or use the built-in command:

```bash
klaude upgrade
```

## Usage

```bash
klaude [--model [<name>]] [--continue] [--resume [<id>]]
```

**Options:**
- `--model`/`-m`: Choose a model.
  - `--model` (no value): opens the interactive selector.
  - `--model <value>`: resolves `<value>` to a single model; if it can't, it opens the interactive selector filtered by `<value>`.
- `--continue`/`-c`: Resume the most recent session.
- `--resume`/`-r`: Resume a session.
  - `--resume` (no value): select a session to resume for this project.
  - `--resume <id>`: resume a session by its ID directly.
- `--vanilla`: Minimal mode with only basic tools (Bash, Read, Edit, Write) and no system prompts.

**Model selection behavior:**
- Default: uses `main_model` from config.
- `--model` (no value): always prompts you to pick.
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
| codex       | N/A (OAuth)           | gpt-5.2-codex (requires ChatGPT Pro subscription)                             |

List all configured providers and models:

```bash
klaude list
```

Models from providers without a valid API key are shown as dimmed/unavailable.

#### Authentication

Use the auth command to configure API keys or login to subscription-based providers:

```bash
# Interactive provider selection
klaude auth login

# Configure API keys
klaude auth login anthropic   # Set ANTHROPIC_API_KEY
klaude auth login openai      # Set OPENAI_API_KEY
klaude auth login google      # Set GOOGLE_API_KEY
klaude auth login openrouter  # Set OPENROUTER_API_KEY
klaude auth login deepseek    # Set DEEPSEEK_API_KEY
klaude auth login moonshot    # Set MOONSHOT_API_KEY

# OAuth login for subscription-based providers
klaude auth login codex       # ChatGPT Pro subscription
```

API keys are stored in `~/.klaude/klaude-auth.json` and used as fallback when environment variables are not set.

To logout from OAuth providers:

```bash
klaude auth logout codex
```

#### Custom Configuration

User config file: `~/.klaude/klaude-config.yaml`

Open in editor:

```bash
klaude conf
```

##### Model Configuration

You can add custom models to built-in providers or define new ones. Configuration is inherited from built-in providers by matching `provider_name`.

```yaml
# ~/.klaude/klaude-config.yaml
provider_list:
  # Add/Override models for built-in OpenRouter provider
  - provider_name: openrouter
    model_list:
      - model_name: qwen-coder
        model_id: qwen/qwen-2.5-coder-32b-instruct
        context_limit: 131072
        cost: { input: 0.3, output: 0.9 }
      - model_name: sonnet # Override built-in sonnet params
        model_id: anthropic/claude-3.5-sonnet
        context_limit: 200000

  # Add a completely new provider
  - provider_name: my-azure
    protocol: openai
    api_key: ${AZURE_OPENAI_KEY}
    base_url: https://my-instance.openai.azure.com/
    is_azure: true
    azure_api_version: "2024-02-15-preview"
    model_list:
      - model_name: gpt-4
        model_id: gpt-4-deploy-name
        context_limit: 128000
```

**Key Tips:**
- **Merging**: If `provider_name` matches a built-in provider, settings like `protocol` and `api_key` are inherited.
- **Overriding**: Use the same `model_name` as a built-in model to override its parameters.
- **Environment Variables**: Use `${VAR_NAME}` syntax for secrets.

##### Supported Protocols

- `anthropic` - Anthropic Messages API
- `openai` - OpenAI Chat Completion API
- `responses` - OpenAI Responses API (for o-series, GPT-5, Codex)
- `codex_oauth` - OpenAI Codex CLI (OAuth-based, for ChatGPT Pro subscribers)
- `openrouter` - OpenRouter API (handling `reasoning_details` for interleaved thinking)
- `google` - Google Gemini API
- `bedrock` - AWS Bedrock for Claude(uses AWS credentials instead of api_key)

List configured providers and models:

```bash
klaude list
```

### Cost Tracking

View aggregated usage statistics across all sessions:

```bash
# Show all historical usage data
klaude cost

# Show usage for the last 7 days only
klaude cost --days 7
```

### Slash Commands

Inside the interactive session (`klaude`), use these commands to streamline your workflow:

- `/model` - Switch the active LLM during the session.
- `/thinking` - Configure model thinking/reasoning level.
- `/clear` - Clear the current conversation context.
- `/copy` - Copy last assistant message.
- `/status` - Show session usage statistics (cost, tokens, model breakdown).
- `/resume` - Select and resume a previous session.
- `/fork-session` - Fork current session to a new session ID (supports interactive fork point selection).
- `/export` - Export last assistant message to a temp Markdown file.
- `/export-online` - Export and deploy session to surge.sh as a static webpage.
- `/debug [filters]` - Toggle debug mode and configure debug filters.
- `/init` - Bootstrap a new project structure or module.
- `/dev-doc [feature]` - Generate a comprehensive execution plan for a feature.
- `/terminal-setup` - Configure terminal for Shift+Enter support.
- `/help` - List all available commands.


### Input Shortcuts

| Key                  | Action                                      |
| -------------------- | ------------------------------------------- |
| `Enter`              | Submit input                                |
| `Shift+Enter`        | Insert newline (requires `/terminal-setup`) |
| `Ctrl+J`             | Insert newline                              |
| `Ctrl+L`             | Open model picker overlay                   |
| `Ctrl+T`             | Open thinking level picker overlay          |
| `Ctrl+V`             | Paste image from clipboard                  |
| `Left/Right`         | Move cursor (wraps across lines)            |
| `Backspace`          | Delete character or selected text           |
| `c` (with selection) | Copy selected text to clipboard             |

### Sub-Agents

The main agent can spawn specialized sub-agents for specific tasks:

| Sub-Agent | Purpose |
|-----------|---------|
| **Explore** | Fast codebase exploration - find files, search code, answer questions about the codebase |
| **Task** | Handle complex multi-step tasks autonomously |
| **WebAgent** | Search the web, fetch pages, and analyze content |
| **ImageGen** | Generate images from text prompts via OpenRouter Nano Banana Pro |
