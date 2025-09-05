# Minimal Agent CLI

A repository for showing how to make a simple Agent CLI using OpenAI's Response API / Anthropic's Official API / OpenRouter's API

# Usage

```bash
uv sync
uv run codex-mini [--model <name>] [--debug]
```
Use --model/-m to select a model by name (must match model_name in your config).
Use --debug/-d for verbose logs, debug display, and LLM client debugging.

# Config
An example config of Responses API will be created in `~/.config/codex-mini/config.yaml` when first run.

