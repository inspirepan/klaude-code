# Repository Guidelines

## Project Structure & Module Organization

Python package with source code located in `src/klaude_code/`. Main modules include:
- `src/klaude_code/app/`: Application entry point and server lifecycle
- `src/klaude_code/auth/`: OAuth authentication providers (codex, github-copilot, etc.)
- `src/klaude_code/cli/`: Command-line interface
- `src/klaude_code/config/`: Configuration loading, model config, builtin defaults
- `src/klaude_code/agent/`: Agent runtime (agent loop, attachments, memory, context management)
- `src/klaude_code/tool/`: Tool implementations (file, shell, web, agent, etc.)
- `src/klaude_code/prompts/`: Prompt templates and system prompt builder
- `src/klaude_code/control/`: Event bus, session orchestration, runtime facade
- `src/klaude_code/llm/`: LLM client implementations per protocol
- `src/klaude_code/protocol/`: Communication structures, event definitions, sub-agent profiles
- `src/klaude_code/session/`: Session persistence and history management
- `src/klaude_code/skill/`: Skill loading, installation, and system skill management
- `src/klaude_code/tui/`: Terminal UI components and state machine
- `src/klaude_code/web/`: Web frontend backend (FastAPI routes, WebSocket)
- `web/`: Web frontend (React + TypeScript)

Python tests are located in the `tests/` directory. Web frontend tests are in `web/src/` alongside source files (`*.test.ts`).

## Build, Test, and Development Commands

- `make lint`: Run ruff + pyright + import-linter + web eslint
- `make format`: Auto-fix with ruff check --fix + ruff format + prettier
- `make test`: Run all tests (vitest + pytest)
- `make web-test`: Run web frontend tests only (vitest)
- `uv run pytest tests/test_foo.py -x -q --tb=short`: Run a single test file quickly
- `git submodule update --init --recursive`: Sync required submodule before build/test/release (`src/klaude_code/skill/assets`)
- Use `tmux-test` skill to test UI interactive features

## Coding Style & Naming Conventions

- Python 3.13+ required
- Line length: 120 characters (enforced by ruff)
- Type checking: Strict mode with Pyright
- Naming conventions: Follow PEP 8 for Python code
- Follow existing patterns exactly
- Public APIs must have concise docstrings
- Functions must be focused and small

## Testing Guidelines

### Python (pytest)

- Test files should be placed in `tests/` directory
- Test naming convention: `test_*.py`
- Run tests with `make test` or `uv run pytest`
- For tests that create or persist `Session` data, use the `isolated_home` fixture from `tests/conftest.py` so `HOME`/`Path.home()` point to a per-test temp directory and do not pollute the real `~/.klaude` session store

### Web frontend (vitest)

- Test files are co-located with source: `web/src/**/*.test.ts`
- Run tests with `make web-test` or `cd web && pnpm test`
- Pure logic tests (reducers, store helpers) are preferred — no DOM or browser required

## Python Type Hints

- Prefer `str | None` over `Optional[str]`
- Prefer `list[str]` over `typing.List[str]`
- For complex function inputs or outputs, define a Pydantic model rather than returning tuples

## Architecture Constraints

- Layered architecture enforced by import-linter: `cli > tui/web > app > agent > tool/prompts/control > skill > session > config > llm > protocol > auth > log/const`
- `agent` can import from `tool`, `prompts`, `control`; reverse direction is forbidden
- Sub-agent profiles are registered in `protocol/sub_agent/`, runtime logic lives in `agent/`
- Prompt files live in `prompts/`, loaded via `load_prompt_by_path()`
- Context management (compaction, handoff, rewind) lives in `agent/compaction/`, `agent/handoff/`, `agent/rewind/`

## Commit Message Convention

Always use the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
<type>(<scope>): <description>
```

## Module-Specific Docs

- `src/klaude_code/auth/AGENTS.md` - Adding new OAuth authentication providers
- `src/klaude_code/agent/context/compaction/AGENTS.md` - Context window compaction logic and triggers
- `src/klaude_code/protocol/sub_agent/AGENTS.md` - Sub-agent profiles, registration, fork context mode
- `src/klaude_code/skill/AGENTS.md` - Skill submodule management and loading
- `src/klaude_code/tui/input/AGENTS.md` - REPL input handling, markers, and special syntax
- `web/AGENTS.md` - Web frontend component rules and design system