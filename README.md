# Klaude Code

Minimal code agent CLI.

## Features
- **Multi-provider**: Anthropic Message API, OpenAI Responses API, OpenRouter, Claude Max OAuth and ChatGPT Codex OAuth etc.
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

Or use the built-in alias command:

```bash
klaude update
klaude upgrade
klaude --version

```

## Usage

```bash
klaude [--model <name>] [--select-model]
```

**Options:**
- `--model`/`-m`: Preferred model name (exact match picks immediately; otherwise opens the interactive selector filtered by this value).
- `--select-model`/`-s`: Open the interactive model selector at startup (shows all models unless `--model` is also provided).
- `--continue`/`-c`: Resume the most recent session.
- `--resume`/`-r`: Select a session to resume for this project.
- `--resume-by-id <id>`: Resume a session by its ID directly.
- `--vanilla`: Minimal mode with only basic tools (Bash, Read, Edit, Write) and no system prompts.

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
| claude      | N/A (OAuth)           | sonnet@claude, opus@claude (requires Claude Pro/Max subscription)             |
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

#### OAuth Login

For subscription-based providers (Claude Pro/Max, ChatGPT Pro), use the login command:

```bash
# Interactive provider selection
klaude login

# Or specify provider directly
klaude login claude   # Claude Pro/Max subscription
klaude login codex    # ChatGPT Pro subscription
```

To logout:

```bash
klaude logout claude
klaude logout codex
```

#### Custom Configuration

User config file: `~/.klaude/klaude-config.yaml`

Open in editor:

```bash
klaude config
```

##### Adding Models to Built-in Providers

You can add custom models to existing built-in providers without redefining the entire provider. Just reference the `provider_name` and add your `model_list`:

```yaml
# ~/.klaude/klaude-config.yaml
provider_list:
  - provider_name: openrouter  # Reference existing built-in provider
    model_list:
      - model_name: seed
        model_params:
          model: bytedance-seed/seed-1.6  # Model ID from OpenRouter
          context_limit: 262000
          cost:
            input: 0.25
            output: 2
```

**How merging works:**
- Your models are merged with the built-in models for that provider
- You only need `provider_name` and `model_list` - protocol, api_key, etc. are inherited from the built-in config
- To override a built-in model, use the same `model_name` (e.g., `sonnet` to customize the built-in sonnet)

**More examples:**

```yaml
provider_list:
  # Add multiple models to OpenRouter
  - provider_name: openrouter
    model_list:
      - model_name: qwen-coder
        model_params:
          model: qwen/qwen-2.5-coder-32b-instruct
          context_limit: 131072
          cost:
            input: 0.3
            output: 0.9
      - model_name: llama-405b
        model_params:
          model: meta-llama/llama-3.1-405b-instruct
          context_limit: 131072
          cost:
            input: 0.8
            output: 0.8

  # Add models to Anthropic provider
  - provider_name: anthropic
    model_list:
      - model_name: haiku@ant
        model_params:
          model: claude-3-5-haiku-20241022
          context_limit: 200000
          cost:
            input: 1.0
            output: 5.0
```

After adding models, run `klaude list` to verify they appear in the model list.

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

##### Supported Protocols

- `anthropic` - Anthropic Messages API
- `claude_oauth` - Claude OAuth (for Claude Pro/Max subscribers)
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
