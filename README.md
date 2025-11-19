# Minimal Agent CLI (codex-mini)

A repository for showing how to make a simple Agent CLI using OpenAI's Response API / Anthropic API / OpenRouter's API, like Claude Code & Codex.

Designed with a modern Python stack (3.13+, uv) and strict engineering practices.

## Key Features

- **Adaptive Tooling**: Automatically configures the optimal toolset based on the selected model (e.g., enables advanced planning tools `update_plan`/`apply_patch` for reasoning-heavy models like GPT-5, while using standard `edit`/`bash` for others).
- **Engineered Slash Commands**: Built-in workflow optimization commands like `/plan` (development planning), `/init` (project bootstrapping), and `/doc` (documentation generation) powered by specialized prompt templates.
- **Claude Skill System**: Supports loading external "Skills" to expand the agent's capabilities beyond basic file and shell operations.
- **Sub-Agent Architecture**: Utilizes specialized sub-agents (Task & Oracle) for delegating complex execution or research tasks to specialized prompts/models.
- **Multi-Provider Support**: Seamlessly switch between OpenAI, Anthropic, Google Gemini, and OpenRouter models.
- **Session Management**: Robust context handling with resumable sessions (`--continue`).

## Usage

### Interactive Mode

```bash
uv sync
uv run cdx [--model <name>] [--select-model]
```

- `--model`/`-m`: Select a model by logical name from config.
- `--select-model`/`-s`: Interactively choose a model at startup.
- `--debug`/`-d`: Verbose logging and LLM trace.
- `--continue`/`-c`: Resume the most recent session.

### Slash Commands

Inside the interactive session (`cdx`), use these commands to streamline your workflow:

- `/plan [goal]` - Generate a comprehensive execution plan for a feature.
- `/init [spec]` - Bootstrap a new project structure or module.
- `/doc [target]` - Write or update documentation.
- `/model` - Switch the active LLM during the session.
- `/clear` - Clear the current conversation context.
- `/diff` - Show pending changes.
- `/help` - List all available commands.

### Non-Interactive Headless Mode (exec)

Execute a single command without starting the interactive REPL:

```bash
# Direct input
cdx exec "what is 2+2?"

# Pipe input
echo "hello world" | cdx exec

# With model-config override in exec
echo "generate quicksort in python" | uv run cdx exec --model-config-json '{"protocol":"responses","api_key":"sk-...","base_url":"https://api.openai.com/v1","model":"gpt-5-2025-08-07","reasoning":{"effort":"high"}}'
```

### List Models

List configured providers and models:

```bash
uv run cdx list
```

### Configuration

An example config will be created in `~/.config/codex-mini/config.yaml` when first run.


Open the configuration file in editor:

```bash
uv run cdx config
```

### Override Model Config via JSON (env)

You can also set the override via environment variable (applies to both interactive and exec modes):

```bash
export CODEX_MODEL_CONFIG_JSON='{"protocol":"anthropic","api_key":"sk-...","base_url":"https://api.anthropic.com","model":"claude-3-7-sonnet","thinking":{"type":"enabled","budget_tokens":1024}}'
uv run cdx
```

Notes:
- The JSON must match `LLMConfigParameter` (provider + model fields). Common keys: `protocol`, `api_key`, `base_url`, `is_azure`, `azure_api_version`, `model`, `temperature`, `max_tokens`, `reasoning`, `thinking`.
- The override only affects the main agent; plan/task/oracle models still follow your YAML config.

## Agent Architecture & Design

### 🧠 Adaptive Model-Tooling
The system dynamically configures its capabilities based on the active model's strengths:
- **Reasoning Models (e.g., GPT-5)**: Equips with `update_plan` and `apply_patch` tools to leverage high reasoning effort and precise code generation.
- **Standard Models (e.g., Gemini 2/3, Claude 3.7)**: Uses robust `edit` (str replace) and `bash` tools for reliable execution.
- **Sub-Agents**: Automatically switches context and toolsets when delegating to `Oracle` (Read-only analysis) or `Task` (Code execution) agents.

### 🔔 Context-Aware Reminders
Inspired by Claude Code, the system injects `<system-reminder>` tags into the conversation stream to guide the agent without polluting the user context:
- **Empty Todo**: Nudges the agent to create a Todo list if working on complex tasks without one.
- **File Changes**: Detects external file modifications and automatically feeds the new content to the agent, preventing "hallucination" on stale code.
- **Forgotten Context**: Intelligent recall of project instructions (`AGENTS.md`) when the agent navigates into relevant directories.
- **Stale Todos**: Gentle reminders to update or clean up todo items if they haven't been touched recently.

### 🤖 Specialized Sub-Agents
Complex tasks are handled by a hierarchy of specialized agents:
- **Main Agent**: Orchestrator, handles user interaction and high-level planning.
- **Oracle Agent**: "ReadOnly" expert. Spawns with a focused context to read docs/code and answer questions without risk of modifying files.
- **Task Agent**: Execution specialist. Spawns to handle tedious coding tasks or refactoring with a stripped-down toolset focused on speed and precision.

## Development Stack

This project utilizes best-in-class modern Python tooling:

- **Python 3.13+**
- **uv**: Extremely fast Python package manager and resolver.
- **Pyright**: Strict static type checking.
- **Ruff**: Fast linting and formatting (line length 120).
- **Rich**: Beautiful terminal UI capabilities.

