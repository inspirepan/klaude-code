# Klaude Code

A coding agent for your terminal. Klaude reads and edits files, runs commands, and delegates work to specialized sub-agents.

Use models from Anthropic, OpenAI, Google, OpenRouter, and other providers, or sign in with a ChatGPT subscription.

## Get started

Install with [uv](https://docs.astral.sh/uv/getting-started/installation/):

```bash
uv tool install klaude-code
```

Configure a provider, then start Klaude in your project directory:

```bash
klaude login
cd your-project
klaude
```

You can also supply credentials through environment variables such as `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `GEMINI_API_KEY`. On first run, choose a model from the picker. Klaude saves your choice.

To update, run `klaude upgrade` or `uv tool upgrade klaude-code`.

## Work in the terminal

Describe a task in the input editor. Use `@path` to attach a file or directory, or paste an image with `ctrl-v`.

Klaude can search the codebase, edit files, run tests, and search the web. Specialized sub-agents handle code search, implementation, correctness review, and maintainability review. Use `/tasks` to inspect background agents and shell commands.

While Klaude works, you can send more input. `enter` queues a message for the next safe step boundary. `alt-enter` queues a follow-up for after the current turn.

### Choose a model

```bash
klaude models                 # Available models and role bindings
klaude models --all           # Include disabled entries and missing credentials
klaude -m                     # Open the model picker
klaude -m sonnet              # Choose by name
klaude -m sonnet@anthropic    # Choose a specific provider
```

If a model query has several matches, Klaude opens a filtered picker. Inside a session, use `/model` to switch models or `/sub-agent-model` to configure sub-agents.

The model catalog comes from your installed version and configuration. Use `klaude models` to check availability.

### Resume a conversation

```bash
klaude -c              # Resume the latest session in this directory
klaude -r              # Browse saved sessions
klaude -r SESSION_ID   # Resume by ID, unique prefix, or name
```

Each terminal runs its own conversation and background tasks. Exiting saves history and stops that process's owned work. Klaude asks for confirmation when tasks are still running. A session open in another process cannot be resumed at the same time.

Use `/fork-session` to branch a conversation. `/rewind` creates a branch from an earlier message and carries a summary of the discarded tail into the new session. Stop owned tasks before starting a new session or switching branches.

### Use interactive commands

Type `/` to browse commands and installed skills. These commands cover common tasks:

| Command | Action |
| --- | --- |
| `/init` | Create project instructions |
| `/model` | Switch the main model |
| `/sub-agent-model` | Configure sub-agent models |
| `/manage-providers` | Manage model and WebSearch providers |
| `/tasks` | Browse background tasks and their output |
| `/stop` | Stop child agents |
| `/context` | Inspect context usage |
| `/compact` | Summarize older context |
| `/status` | Show session usage and cost |
| `/copy` | Copy the last assistant message |
| `/fork-session` | Branch the conversation |
| `/rewind` | Branch from an earlier message with a summary |
| `/new` | Start a new conversation |
| `/exit` | Save history and exit |

Klaude compacts older context as the conversation approaches the model's limit. The agent can also use Handoff to summarize a long conversation and continue in a fresh context.

### Use keyboard shortcuts

| Key | Action |
| --- | --- |
| `enter` | Submit input |
| `alt-enter` | Queue a follow-up while the agent works |
| `ctrl-j` | Insert a newline |
| `shift-enter` | Insert a newline in supported terminals |
| `ctrl-l` | Open the model picker |
| `ctrl-v` | Paste an image |
| `ctrl-o` | Toggle compact and expanded transcript views |
| `ctrl-t` | Expand or fold diffs and compaction summaries |
| `esc` or `ctrl-c` | Interrupt the main agent |

## Add project instructions and skills

Klaude reads `AGENTS.md`, `CLAUDE.md`, and `AGENT.md` for project instructions. It loads instructions from the initial search paths and discovers scoped instructions near files as you work.

Project memory uses `~/.klaude/projects/<project-key>/memory/MEMORY.md`. Klaude also reads compatible Claude Code project memory. The index enters context automatically; the agent can read additional memory files as needed.

Skills are installed separately. For example:

```bash
npx skills add inspirepan/agent-skills --global --agent codex claude-code --skill klaude-config
```

Shared user skills can live in `~/.agents/skills/`. Project skills can live in `.agents/skills/` or `.claude/skills/`. Klaude also supports the other user directories listed in the [configuration reference](docs/configuration.md#skill-directories).

Type `//` for skill-only completion. Use `/skill:name` or `//skill:name` to invoke a skill explicitly. The agent can also select a skill from its description and read its instructions.

## Configure providers and models

Run `klaude config` to edit `~/.klaude/klaude-config.yaml`. You can add providers, override built-in models, and set model fallback lists.

The [configuration reference](docs/configuration.md) covers credentials, model selection, sub-agent defaults, custom providers, and WebSearch.

## Run tasks from scripts

Use `klaude run` to start an independent background process:

```bash
id=$(klaude run "Investigate the failing tests and report the cause")
klaude brief "$id"
klaude wait "$id" --timeout 600
klaude output "$id"
```

`run` returns a session ID immediately. `wait` returns when the session finishes or needs attention. The default approval policy holds permission requests for your response. Use `klaude respond` to answer pending approvals or questions.

Use `klaude ps` to list online sessions and `klaude send SESSION_ID "message"` to message one. Messages require an online process. For one command that waits and prints the result, use `klaude run --wait "your task"`.

For command options, run `klaude --help` or `klaude COMMAND --help`. `klaude --skill` prints the integration guide with the models and agent types available in your configuration. Inside Klaude, agents use the native `Agent` and task-management tools for delegated work.

## Inspect history and costs

```bash
klaude web             # Open the read-only viewer of saved history
klaude cost            # Usage from the last 7 days
klaude cost --days 30  # Usage from the last 30 days
klaude cost --all      # All recorded usage
```

## Develop Klaude

Python 3.13 or later is required. Building the web viewer also requires Node.js and either pnpm or npm.

```bash
git clone https://github.com/inspirepan/klaude-code.git
cd klaude-code
uv sync
make install
```

`make install` builds the web viewer and installs the CLI as an editable package. Restart running Klaude processes after code changes to load the new version, then resume with `klaude -r`.

Use the following checks during development:

```bash
make format      # Apply Python formatting and lint fixes
make lint        # Run ruff, ty, and import-linter
make test        # Run the non-network test suite
make build       # Build the web viewer and Python distributions
make pre-push    # Run all required checks before pushing
```

See [AGENTS.md](AGENTS.md) for repository conventions, [the model checklist](docs/add-model.md) to add or upgrade a model, and [CHANGELOG.md](CHANGELOG.md) for release history.
