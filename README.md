# Minimal Code Agent CLI (Klaude Code)

An minimal and opinionated code agent with multi-model support.

## Key Features
- **Adaptive Tooling**: Model-aware toolsets (Claude Code tools for Sonnet, Codex `apply_patch` for GPT-5.1/Codex).
- **Multi-Provider Support**: Compatible with `anthropic-messages-api`,`openai-responses-api`, and `openai-compatible-api`(`openrouter-api`),  featuring interleaved thinking, OpenRouter's provider sorting etc.
- **Skill System**: Extensible support for loading Claude Skills.
- **Session Management**: Robust context preservation with resumable sessions (`--continue`).
- **Simple TUI**: Clean interface offering full visibility into model responses, reasoning and actions.
- **Core Utilities**: Slash commands, sub-agents, image pasting, terminal notifications, file mentioning, and auto-theming.


## Installation

```bash
uv tool install klaude-code
```

To update:

```bash
uv tool upgrade klaude-code
```

## Usage

### Interactive Mode

```bash
klaude [--model <name>] [--select-model]
```

**Options:**
- `--version`/`-V`: Show version and exit.
- `--model`/`-m`: Select a model by logical name from config.
- `--select-model`/`-s`: Interactively choose a model at startup.
- `--continue`/`-c`: Resume the most recent session.
- `--resume`/`-r`: Select a session to resume for this project.
- `--vanilla`: Minimal mode with only basic tools (Bash, Read, Edit) and no system prompts.

**Debug Options:**
- `--debug`/`-d`: Enable debug mode with verbose logging and LLM trace.
- `--debug-filter`: Filter debug output by type (comma-separated).


### Configuration

An example config will be created in `~/.klaude/config.yaml` when first run.

Open the configuration file in editor:

```bash
klaude config
```

An minimal example config yaml using OpenRouter's API Key:

```yaml
provider_list:
- provider_name: openrouter-work
  protocol: openrouter # support <responses|openrouter|anthropic|openai>
  api_key: <your-openrouter-api-key>
model_list:
- model_name: gpt-5.1-codex
  provider: openrouter
  model_params:
    model: openai/gpt-5.1-codex
    context_limit: 368000
    thinking:
      reasoning_effort: medium
- model_name: gpt-5.1-high
  provider: openrouter
  model_params:
    model: openai/gpt-5.1
    context_limit: 368000
    thinking:
      reasoning_effort: high
- model_name: sonnet
  provider: openrouter
  model_params:
    model: anthropic/claude-4.5-sonnet
    context_limit: 168000
    provider_routing:
      sort: throughput
- model_name: haiku
  provider: openrouter
  model_params:
    model: anthropic/claude-haiku-4.5
    context_limit: 168000
    provider_routing:
      sort: throughput
main_model: gpt-5.1-codex
subagent_models:
  oracle: gpt-5.1-high
  explore: haiku
  task: sonnet
```

List configured providers and models:

```bash
klaude list
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

### Non-Interactive Headless Mode (exec)

Execute a single command without starting the interactive REPL:

```bash
# Direct input
klaude exec "what is 2+2?"

# Pipe input
echo "hello world" | klaude exec

# With model selection
echo "generate quicksort in python" | klaude exec --model gpt-5.1
```