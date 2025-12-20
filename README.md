# Klaude Code

Multi-model code agent CLI.

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

An example config will be created in `~/.klaude/klaude-config.yaml` when first run.

Open the configuration file in editor:

```bash
klaude config
```

An example config yaml:

```yaml
provider_list:
- provider_name: openrouter
  protocol: openrouter # support <responses|openrouter|anthropic|openai>
  api_key: <your-openrouter-api-key>

- provider_name: openai-responses
  protocol: responses
  api_key: <your-openai-api-key>

- provider_name: anthropic
  protocol: anthropic
  api_key: <your-anthropic-api-key>

- provider_name: moonshot
  protocol: anthropic
  base_url: https://api.moonshot.cn/anthropic
  api_key: <your-api-key>

- provider_name: deepseek
  protocol: anthropic
  base_url: https://api.deepseek.com/anthropic
  api_key: <your-api-key>

model_list:

- model_name: deepseek
  provider: deepseek
  model_params:
    model: deepseek-reasoner
    context_limit: 128000
    thinking:
      type: enabled
      budget_tokens: 8192
    cost:
      currency: CNY
      input: 2
      output: 3
      cache_read: 0.2

- model_name: codex-max
  provider: openai-responses
  model_params:
    model: gpt-5.1-codex-max
    thinking:
      reasoning_effort: medium
    context_limit: 400000
    max_tokens: 128000
    cost:
      input: 1.25
      output: 10
      cache_read: 0.13

- model_name: gpt-5.1
  provider: openrouter
  model_params:
    model: openai/gpt-5.1
    context_limit: 400000
    max_tokens: 128000
    verbosity: high
    thinking:
      reasoning_effort: high
    cost:
      input: 1.25
      output: 10
      cache_read: 0.13

- model_name: kimi@moonshot
  provider: moonshot
  model_params:
    model: kimi-k2-thinking
    context_limit: 262144
    thinking:
      type: enabled
      budget_tokens: 8192
    cost:
      currency: CNY
      input: 4
      output: 16
      cache_read: 1

- model_name: opus
  provider: openrouter
  model_params:
    model: anthropic/claude-4.5-opus
    context_limit: 200000
    provider_routing:
      only: [ google-vertex ]
    verbosity: high
    thinking:
      type: enabled
      budget_tokens: 31999
    cost:
      input: 5
      output: 25
      cache_read: 0.5
      cache_write: 6.25

- model_name: gemini
  provider: openrouter
  model_params:
    model: google/gemini-3-pro-preview
    context_limit: 1048576
    thinking:
      reasoning_effort: medium
    cost:
      input: 2
      output: 12
      cache_read: 0.2

- model_name: haiku
  provider: anthropic
  model_params:
    model: claude-haiku-4-5-20251001
    context_limit: 200000
    cost:
      input: 1
      output: 5
      cache_read: 0.1
      cache_write: 1.25

main_model: opus

sub_agent_models:
  oracle: gpt-5.1
  explore: haiku
  task: opus
  webagent: haiku

```

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
