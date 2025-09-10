# Minimal Agent CLI

A repository for showing how to make a simple Agent CLI using OpenAI's Response API / Anthropic's Official API / OpenRouter's API

# Usage

```bash
uv sync
uv run cdx [--model <name>] [--select-model] [--debug] [--continue]
```

- `--model`/`-m`: select a model by logical name (must match `model_name` in your config). If omitted, uses the `main_model` from config.
- `--select-model`/`-s`: interactively choose a model at startup. If `-m` is provided, it becomes the default selection.
- `--debug`/`-d`: verbose logs, debug display, and LLM client debugging.
- `--continue`/`-c`: continue from the most recent session.

List configured providers and models:

```bash
uv run cdx list
```

Examples:

```bash
# Start with the default main model
uv run cdx

# Start and interactively choose a model
uv run cdx -s

# Prefer sonnet-4 by default, but confirm interactively
uv run cdx -m sonnet-4 -s

# Start with an explicit model silently
uv run cdx -m gpt-5

# Continue from the latest session
uv run cdx -c
```

# Config
An example config of Responses API will be created in `~/.config/codex-mini/config.yaml` when first run.

