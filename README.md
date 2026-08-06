# Klaude Code

Minimal code agent CLI — and an **agent multiplexer**: one local server owns all agent execution, humans use the TUI, and other agents (Claude Code, scripts, cron jobs) drive it through the CLI.

## Agent Multiplexer

Every klaude command is a thin client of a single local server (Unix socket, auto-started on demand). `run` returns immediately, multi-target `wait` is a barrier, `--group` names a fan-out — orchestration is plain bash:

```bash
id=$(klaude run --group me "fix the failing tests under tests/server/")
klaude ps                                  # ID / NAME / TITLE / STATE / MODEL / ACTIVITY
klaude brief "$id"                         # compact, bounded status report
klaude wait "$id" --timeout 600            # block until it settles (exit 0/2/3/124)
klaude output "$id"                        # last assistant message
klaude send "$id" --wait "now update the changelog too"   # next turn, same context
```

Parallel fan-out + barrier + synthesis:

```bash
G="review-$(git rev-parse --short HEAD)"
git diff --name-only main | \
  xargs -I{} klaude run --group "$G" --agent code-reviewer "review the changes in {}"
klaude wait --group "$G" --timeout 900
klaude output --group "$G" | klaude run --wait "dedupe these findings and rank by severity"
```

Sessions never expire: `send` works days later and across server restarts. Background agents run unattended (`--approval hold|auto|deny`); when one parks at `waiting_input`, answer it with `klaude respond` or attach the TUI. The server caps concurrent headless runs (`headless_max_running`, default 8) and queues the rest.

For the full integration guide (command cheatsheet, orchestration patterns, current models and agent types, assembled from your live config):

```bash
klaude agents --prime    # paste into your agent's CLAUDE.md / AGENTS.md
```

## Features
- **Agent multiplexer**: single local server owns all execution; spawn background agents with `run`, track with `ps`/`brief`/`wait`, continue with `send`, interrupt with `kill`
- **Agent-friendly CLI**: bounded `brief` reports, `--json` everywhere, exit-code contracts, plain-text `--help`, `klaude agents --prime` integration guide
- **Multi-provider**: Anthropic Message API, OpenAI Responses API, OpenRouter, ChatGPT Codex OAuth etc.
- **Keep reasoning item in context**: Interleaved thinking support
- **Model-aware tools**: Claude Code tool set for Opus, `apply_patch` for GPT-5/Codex
- **Reminders**: Cooldown-based todo tracking, instruction reinforcement and external file change reminder
- **Sub-agents**: General Purpose, Finder, Code Reviewer, Code Maintenance Reviewer (+ fork-context variant)
- **Recursive `@file` mentions**: Circular dependency protection, relative path resolution
- **External file sync**: Monitoring for external edits (linter, manual)
- **Interrupt handling**: Ctrl+C preserves partial responses and synthesizes tool cancellation results
- **Output truncation**: Large outputs saved to file system with snapshot links
- **Agent Skills**: Built-in + user + project Agent Skills (with implicit invocation by Skill tool or explicit invocation by typing `//skill` or `/skill`)
- **Prompt caching**: Append-only persisted history and stable request prefixes maximize cache hits
- **Context management**: Auto-compaction, Rewind (rollback to checkpoint), Handoff (compress and continue in fresh context)
- **Auto memory**: Persistent cross-session memory per project (`~/.klaude/projects/<project>/memory/`)
- **Local server**: Managed with `klaude server` (status / stop / reload / logs / run)
- **Sessions**: Resumable with `--continue`, forkable with `/fork-session`
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

### Development Install

```bash
git clone https://github.com/inspirepan/klaude-code.git
cd klaude-code
make install    # init submodules, install as editable
```

Or step by step:

```bash
git submodule update --init --recursive
uv sync                              # install Python deps
uv tool install -e .                 # install CLI globally (editable)
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
export YOUTU_API_KEY=xxx                  # Youtu gateway (multi-provider)
export DEEPSEEK_API_KEY=sk-xxx           # DeepSeek models
export MOONSHOT_API_KEY=sk-xxx           # Moonshot/Kimi models
export MINIMAX_API_KEY=xxx               # MiniMax models
export GOOGLE_API_KEY=xxx                # Google Gemini models (or GEMINI_API_KEY)
export EXA_API_KEY=exa-xxx               # Exa Search (optional, WebSearch provider, preferred)
export BRAVE_API_KEY=BSA-xxx             # Brave Search (optional, WebSearch provider, fallback)

# Then just run:
klaude
```

On first run, you'll be prompted to select a model. Your choice is saved as `main_model`.

You can also configure fallback lists for the main model and helper models:

```yaml
main_model:
  - gpt-5.5
  - gpt-5.4
  - opus

fast_model:
  - haiku
  - gemini-flash
  - gpt-5-nano

compact_model:
  - gemini-flash
  - haiku
```

Klaude expands each entry into concrete provider candidates in `provider_list` order, then falls through to the next model in the list. For example, `gpt-5.4` will try available providers such as `gpt-5.4@openai` and `gpt-5.4@openrouter` before moving to the next model. Runtime fallback is used for non-retryable provider/model failures such as quota, billing, permission, or model-unavailable errors. `fast_model` is used for session-title generation; `compact_model` is used for compact/helper tasks.

When you switch models with `/model`, Klaude updates `main_model` without discarding the fallback chain: the selected model is moved to the front if it already exists, or inserted at the front otherwise.

#### Built-in Providers

| Provider(s) | Credentials |
|-------------|-------------|
| `youtu-anthropic`, `youtu-openai`, `youtu-gemini` | `YOUTU_API_KEY` |
| `anthropic` | `ANTHROPIC_API_KEY` |
| `aws-bedrock` | `AWS_BEDROCK_ACCESS_KEY_ID` + `AWS_BEDROCK_SECRET_ACCESS_KEY` + `AWS_BEDROCK_REGION` (standard `AWS_*` fallbacks are also accepted) |
| `openai` | `OPENAI_API_KEY` |
| `azure-openai-responses` | `AZURE_OPENAI_API_KEY` + `AZURE_OPENAI_ENDPOINT` (or `AZURE_OPENAI_BASE_URL`) |
| `google` | `GOOGLE_API_KEY` or `GEMINI_API_KEY` |
| `google-vertex` | `GOOGLE_APPLICATION_CREDENTIALS` + `GOOGLE_CLOUD_PROJECT` + `GOOGLE_CLOUD_LOCATION` |
| `deepseek` | `DEEPSEEK_API_KEY` |
| `moonshot-cn`, `moonshot-ai` | `MOONSHOT_API_KEY` |
| `minimax` | `MINIMAX_API_KEY` |
| `opencode-go`, `opencode-go-anthropic` | `OPENCODE_API_KEY` |
| `codex` | OAuth via `klaude auth login codex` |
| `openrouter` | `OPENROUTER_API_KEY` |

List all configured providers, models, and agent types:

```bash
klaude agents
```

Models from providers without valid credentials are shown as dimmed/unavailable. The built-in
model catalog changes more frequently than this README; use `klaude agents` for the authoritative
provider/model list (`--json` for machines, `--prime` for an AI-agent integration guide).

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
klaude auth login minimax     # Set MINIMAX_API_KEY
klaude auth login aws-bedrock    # Configure AWS Bedrock credentials
klaude auth login google-vertex  # Configure Google Vertex credentials

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
main_model:
  - gpt-5.5
  - gpt-5.4
  - opus

fast_model:
  - haiku
  - gemini-flash
  - gpt-5-nano

compact_model:
  - gemini-flash
  - haiku

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
- **Model Preference Lists**: `main_model`, `fast_model`, and `compact_model` accept either a single string or a list of model selectors. When you provide a list, Klaude first tries matching providers in `provider_list` order for each selector, then moves to the next selector.
- **Updating Defaults**: `/model` keeps saving the selected model back to `main_model`, but preserves fallback order by moving or inserting the selected model at the front of the list.

##### Sub-agent Model Configuration

`sub_agent_models` accepts registered sub-agent type names as keys. Current supported keys are:

- `general-purpose` - Autonomous multi-step task executor
- `general-purpose-fork-context` - Same as above but inherits parent conversation history
- `finder` - Fast codebase search and exploration
- `code-reviewer` - Identifies bugs in proposed changes
- `code-maintenance-reviewer` - Reviews maintainability, reuse, layering, and unnecessary complexity

If a sub-agent type is not configured, it falls back to the main agent model. Each key also accepts a list for fallback ordering.

```yaml
sub_agent_models:
  general-purpose: sonnet
  finder:
    - haiku
    - gemini-flash
  code-reviewer: opus
```

##### Supported Protocols

- `anthropic` - Anthropic Messages API
- `openai` - OpenAI Chat Completion API
- `responses` - OpenAI Responses API (for o-series, GPT-5, Codex)
- `codex_oauth` - OpenAI Codex CLI (OAuth-based, for ChatGPT Pro subscribers)
- `openrouter` - OpenRouter API (handling `reasoning_details` for interleaved thinking)
- `google` - Google Gemini API
- `google_vertex` - Google Vertex AI (uses GCP credentials)
- `bedrock` - AWS Bedrock for Claude (uses AWS credentials instead of api_key)

List configured providers and models:

```bash
klaude agents
```

### Cost Tracking

View aggregated usage statistics across all sessions:

```bash
# Show all historical usage data
klaude cost

# Show usage for the last 7 days only
klaude cost --days 7

# Alias for days
klaude cost --recent 7
```

### Slash Commands

Inside the interactive session (`klaude`), use these commands to streamline your workflow:

- `/...` supports mixed completion for commands + skills (command names take priority on conflicts).
- `//...` shows skill-only completion and triggers skills explicitly.

- `/copy` - Copy last assistant message to clipboard.
- `/compact` - Clear conversation history but keep a summary in context.
- `/fork-session` - Fork current session from a selected point.
- `/refresh-terminal` - Refresh terminal display.
- `/new` - Start a new session (clears context).
- `/model` - Switch the active LLM and update `main_model` in config while preserving fallback order (the selected model is moved/inserted to the front).
- `/sub-agent-model` - Configure sub-agent models at runtime.
- `/status` - Show session usage statistics (cost, tokens, model breakdown).
- `/login` - Login to provider or configure API key.
- `/logout` - Logout from provider.
- `/continue` - Continue current session without a new user message.
- `/debug [filters]` - Toggle debug mode and configure debug filters.


### Input Shortcuts

| Key                  | Action                                      |
| -------------------- | ------------------------------------------- |
| `Enter`              | Submit input                                |
| `Shift+Enter`        | Insert newline (terminal-dependent)         |
| `Ctrl+J`             | Insert newline                              |
| `Ctrl+L`             | Open model picker overlay                   |
| `Ctrl+V`             | Paste image from clipboard                  |
| `Left/Right`         | Move cursor (wraps across lines)            |
| `Backspace`          | Delete character or selected text           |
| `c` (with selection) | Copy selected text to clipboard             |

### Sub-Agents

The main agent can spawn specialized sub-agents for specific tasks:

| Sub-Agent | Purpose |
|-----------|---------|
| **General Purpose** | Handle complex multi-step tasks autonomously |
| **General Purpose (Fork Context)** | Same as above, but inherits the parent agent's full conversation history |
| **Finder** | Fast codebase exploration - find files, search code, answer questions about the codebase |
| **Code Reviewer** | Identify real bugs in proposed changes |
| **Code Maintenance Reviewer** | Review maintainability, reuse, layering, and unnecessary complexity |

### Local Server

Klaude runs a local server on a Unix domain socket (`~/.klaude/run/server.sock`).

```bash
klaude server run       # run the server in the foreground (debugging)
klaude server status    # pid, socket path, uptime, version, session counts
klaude server stop      # graceful shutdown
klaude server reload    # graceful restart on the current code (--force to interrupt sessions)
klaude server logs      # tail server logs
```

### Prompt Caching

Klaude is designed to maximize prefix cache hit rates across LLM API calls. Cache pricing varies by
provider and model, but cache hits generally reduce input cost and latency.

**Append-only persisted history.** New messages, tool results, compaction entries, and rewind entries
are appended to `events.jsonl`. The active LLM-facing view may omit or summarize earlier events,
but ordinary consecutive requests keep unchanged prefixes byte-identical whenever possible.

Design choices that preserve prefix stability:
- **Stable system prompt**: The system prompt is composed of a static base prompt + stable tool strategy block + environment info, avoiding per-step variation.
- **Stable JSON serialization**: Tool schemas and provider payloads use `canonicalize_json()` for deterministic key ordering across calls.
- **Cache control markers**: For Anthropic and OpenRouter (Claude models), `cache_control: {"type": "ephemeral"}` is placed on the system prompt and the last message part to hint the provider's caching boundary.
- **Cache-aware compaction**: Compatible main/compact models can reuse the original request prefix
  while generating the summary; the next request uses the summary plus the retained tail.
- **Fork-context sub-agents**: Sub-agents with `fork_context=True` inherit the parent's full system prompt and tool list to maximize prefix cache sharing.

The TUI displays cache hit rate per step in the metadata line (e.g. `cache 12.5k (98%)`). Rates below 90% are highlighted as a warning.

### Context Management

The agent automatically manages context window limits:

- **Auto-compaction**: When the conversation approaches the model's context limit, the LLM-facing
  view replaces older messages with a compact summary while persisted events remain append-only.
  The agent also recovers from context overflow errors by compacting and retrying.
- **Rewind**: The agent can roll back the conversation to a previous checkpoint (automatically inserted at key points). File system changes are preserved; only conversation history is rewound.
- **Handoff**: The agent can compress the current conversation into a summary and continue in a fresh context. Useful for very long sessions where context quality degrades.

### Auto Memory

Klaude maintains persistent memory per project across sessions. Memory files are stored in `~/.klaude/projects/<project-key>/memory/` with a `MEMORY.md` index file. The agent automatically loads relevant memories at session start and can save new memories during a session.

Memory types include user preferences, feedback/corrections, project context, and external references.

### Project Configuration Files

Klaude reads instruction files from your project directory to customize agent behavior:

| File | Purpose |
|------|---------|
| `AGENTS.md` | Project-level instructions checked into version control (shared with team) |
| `CLAUDE.md` | Personal instructions (typically gitignored) |

These files are loaded automatically and injected into the system prompt. They can be placed at the project root or in subdirectories for scoped instructions.
