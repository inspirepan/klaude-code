# Minimal Agent CLI (klaude-code)

A repository for showing how to make a simple Agent CLI using OpenAI's Response API / Anthropic API / OpenRouter's API, like Claude Code & Codex.

Designed with a modern Python stack (3.13+, uv) and strict engineering practices.

## Key Features

- **Adaptive Tooling**: Automatically configures the optimal toolset based on the selected model (e.g., enables advanced planning tools `update_plan`/`apply_patch` for reasoning-heavy models like GPT-5, while using standard `edit`/`bash` for others).
- **Engineered Slash Commands**: Built-in workflow optimization commands like `/plan` (development planning), `/init` (project bootstrapping), and `/doc` (documentation generation) powered by specialized prompt templates.
- **Claude Skill System**: Supports loading external "Skills" to expand the agent's capabilities beyond basic file and shell operations.
- **Sub-Agent Architecture**: Utilizes specialized sub-agents (Task & Oracle) for delegating complex execution or research tasks to specialized prompts/models.
- **Multi-Provider Support**: Seamlessly switch between OpenAI, Anthropic, Google Gemini, and OpenRouter models.
- **Session Management**: Robust context handling with resumable sessions (`--continue`).
- **Multimodal Vision**: Native support for image analysis. The agent can "see" images when reading files (PNG/JPEG/WEBP) and process images pasted directly from the system clipboard into the terminal.

## Usage

### Interactive Mode

```bash
uv sync
uv run klaude [--model <name>] [--select-model]
```

- `--model`/`-m`: Select a model by logical name from config.
- `--select-model`/`-s`: Interactively choose a model at startup.
- `--debug`/`-d`: Verbose logging and LLM trace.
- `--continue`/`-c`: Resume the most recent session.

### Slash Commands

Inside the interactive session (`klaude`), use these commands to streamline your workflow:

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
klaude exec "what is 2+2?"

# Pipe input
echo "hello world" | klaude exec

# With model selection
echo "generate quicksort in python" | uv run klaude exec --model gpt-5
```

### List Models

List configured providers and models:

```bash
uv run klaude list
```

### 👁️ Multimodal Capabilities

The system is fully multimodal (model permitting) and supports image interactions:

1.  **Reading Images**: When the agent uses the `read` tool on an image file (PNG, JPG, GIF, WEBP), the visual content is automatically encoded and sent to the model.
    - *Limit: 4MB max per image for inline transfer.*
2.  **Clipboard Paste**: You can paste images directly from your system clipboard into the terminal prompt (e.g., Cmd+V).
    - They appear as `[Image #N]` tags in the input.
    - The image data is automatically attached to your message context.

### Configuration

An example config will be created in `~/.klaude/config.yaml` when first run.


Open the configuration file in editor:

```bash
uv run klaude config
```

### Terminal Notifications

- Main session task completions emit an OSC 9 notification (supported terminals only).
- Disable with `CODEX_NOTIFY=0`.

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
