# Repository Guidelines

## Concepts

- Session: A conversation between user and agent
  - SubAgents has their own conversation history and session
- Task: When a user provides an input, the Agent executes ReAct until there are no more tool calls. This entire process constitutes a Task
- Turn: Each round where the Agent responds with Reasoning, Text, and ToolCalls. If there are ToolCalls, the execution of the toolcall and generation of ToolResults is considered one Turn
- Response: Each call to the LLM API is considered a Response

## Project Structure & Module Organization

The project follows a Python package structure with source code located in `src/codex_mini/`. Main modules include:
- `src/codex_mini/cli/`: Command-line interface
- `src/codex_mini/core/`: Core application logic
- `src/codex_mini/llm/`: LLM integrations
- `src/codex_mini/ui/`: User interface components
- `src/codex_mini/protocol/`: Communication structures and event definitions

Tests are located in the `tests/` directory. Configuration files include `pyproject.toml` for project settings and `pyrightconfig.json` for TypeScript-style checking.

## Build, Test, and Development Commands

- `uv run isort . && uv run ruff format`: Format and sort imports
- `uv run pytest`: Run tests
- `uv run pyright`: Type checking in strict mode
- `uv run cdx ...`: Execute CLI with the project's virtual environment

## Coding Style & Naming Conventions

- Python 3.13+ required
- Line length: 120 characters (enforced by ruff)
- Type checking: Strict mode with Pyright
- Use `isort` for import sorting and `ruff` for formatting
- Naming conventions: Follow PEP 8 for Python code

## Testing Guidelines

- Use pytest as the testing framework
- Test files should be placed in `tests/` directory
- Test naming convention: `test_*.py`
- Run tests with `pytest` command

## Commit & Pull Request Guidelines

- Commit messages follow the format: `type(scope): description`
- Common types: `feat`, `fix`, `refactor`, `chore`
- Examples: `feat(core): support model switching during runtime`, `fix(ui): slash command completion`
- Keep commits atomic and focused on single changes
- **Use English only** for commit messages
