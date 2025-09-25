# Minimal Agent CLI

A repository for showing how to make a simple Agent CLI using OpenAI's Response API / Anthropic API / OpenRouter's API, like Claude Code & Codex

## Features
- Handling OpenAI Responses API, Anthropic API, OpenAI Compatible API
- Model Selection
- Slash Commands
- Python Rich UI
- Session Management
- Coding Agent Tools & SubAgents
- Claude Code's `<system-reminder>`
- Headless Mode
- YAML Configuration for Providers & Models


## Usage

### Interactive Mode

```bash
uv sync
uv run cdx [--model <name>] [--model-config-json '<json>'] [--select-model] [--debug] [--continue]
```

- `--model`/`-m`: select a model by logical name (must match `model_name` in your config). If omitted, uses the `main_model` from config.
- `--model-config-json`: override the main agent model config with a JSON string matching `LLMConfigParameter`. Takes precedence over `--model`/`--select-model`. Example: `{"protocol":"openai","api_key":"sk-...","base_url":"https://api.openai.com/v1","model":"gpt-4o-mini"}`. Also reads env `CODEX_MODEL_CONFIG_JSON`.
- `--select-model`/`-s`: interactively choose a model at startup. If `-m` is provided, it becomes the default selection.
- `--debug`/`-d`: verbose logs, debug display, and LLM client debugging.
- `--continue`/`-c`: continue from the most recent session.
- `--resume`/`-r`: select a specific session to resume from a list.
- `--unrestricted`/`-u`: disable safety guardrails for file reads and shell command validation (use with caution).


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

