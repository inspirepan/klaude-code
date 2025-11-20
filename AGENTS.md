# Repository Guidelines

## Concepts

- Session: A conversation between user and agent
  - SubAgents has their own conversation history and session
- Task: When a user provides an input, the Agent executes ReAct until there are no more tool calls. This entire process constitutes a Task
- Turn: Each round where the Agent responds with Reasoning, Text, and ToolCalls. If there are ToolCalls, the execution of the toolcall and generation of ToolResults is considered one Turn
- Response: Each call to the LLM API is considered a Response

## Project Structure & Module Organization

The project follows a Python package structure with source code located in `src/klaude_code/`. Main modules include:
- `src/klaude_code/cli/`: Command-line interface
- `src/klaude_code/core/`: Core application logic
- `src/klaude_code/llm/`: LLM integrations
- `src/klaude_code/ui/`: User interface components
- `src/klaude_code/protocol/`: Communication structures and event definitions

Tests are located in the `tests/` directory. Configuration files include `pyproject.toml` for project settings and `pyrightconfig.json` for TypeScript-style checking.

## Build, Test, and Development Commands

- `uv run isort . && uv run ruff format`: Format and sort imports
- `uv run pytest`: Run tests
- `uv run pyright`: Type checking in strict mode
- `uv run klaude ...`: Execute CLI with the project's virtual environment

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


## Agent Configuration for Different Models

- Prompts are configured via `get_system_prompt` in `src/klaude_code/core/prompt.py`
- Tools are configured via `get_main_agent_tools` and `get_sub_agent_tools` in `src/klaude_code/core/tool/tool_registry.py`
- Reminders are configured via `get_main_agent_reminders` and `get_sub_agent_reminders` in `src/klaude_code/core/reminders.py`
- Changes to tools located under `src/klaude_code/core/tool/` are not applied immediately; ask the user to restart the system for them to take effect.

## Python Type Hints

- Prefer `str | None` over `Optional[str]`
- Prefer `list[str]` over `typing.List[str]`
- For complex function inputs or outputs, define a Pydantic model rather than returning tuples