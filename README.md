# Minimal Agent CLI

A repository for showing how to make a simple Agent CLI using OpenAI's Response API / Anthropic's Official API / OpenRouter's API

## Usage

### Interactive Mode

```bash
uv sync
uv run cdx [--model <name>] [--select-model] [--debug] [--continue]
```

- `--model`/`-m`: select a model by logical name (must match `model_name` in your config). If omitted, uses the `main_model` from config.
- `--select-model`/`-s`: interactively choose a model at startup. If `-m` is provided, it becomes the default selection.
- `--debug`/`-d`: verbose logs, debug display, and LLM client debugging.
- `--continue`/`-c`: continue from the most recent session.
- `--resume`/`-r`: select a specific session to resume from a list.


### Non-Interactive Mode (exec)

Execute a single command without starting the interactive REPL:

```bash
# Direct input
cdx exec "what is 2+2?"

# Pipe input
echo "hello world" | cdx exec

# With options
cdx exec "explain this code" --model gpt-4 --debug
```

### List Models

List configured providers and models:

```bash
uv run cdx list
```

### Configuration

An example config will be created in `~/.config/codex-mini/config.yaml` when first run. You can edit it directly or use `uv run cdx config` to open it in your default editor.


Open the configuration file in your default editor:

```bash
uv run cdx config
```