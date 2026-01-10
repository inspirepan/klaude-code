# Repository Guidelines

## Project Structure & Module Organization

Python package with source code located in `src/klaude_code/`. Main modules include:
- `src/klaude_code/cli/`: Command-line interface
- `src/klaude_code/core/`: Core application logic
- `src/klaude_code/llm/`: LLM integrations
- `src/klaude_code/tui/`: User interface components
- `src/klaude_code/protocol/`: Communication structures and event definitions

Tests are located in the `tests/` directory.

## Build, Test, and Development Commands

- `make lint`: Run ruff + pyright + import-linter
- `make format`: Auto-fix with ruff check --fix + ruff format
- `make test`: Run tests (pytest)
- use `tmux-test` skill to test UI interactive features

## Coding Style & Naming Conventions

- Python 3.13+ required
- Line length: 120 characters (enforced by ruff)
- Type checking: Strict mode with Pyright
- Naming conventions: Follow PEP 8 for Python code
- Follow existing patterns exactly
- Public APIs must have concise docstrings
- Functions must be focused and small

## Testing Guidelines

- Use pytest as the testing framework
- Test files should be placed in `tests/` directory
- Test naming convention: `test_*.py`
- Run tests with `pytest` command

## Python Type Hints

- Prefer `str | None` over `Optional[str]`
- Prefer `list[str]` over `typing.List[str]`
- For complex function inputs or outputs, define a Pydantic model rather than returning tuples

## Commit Message Convention

Always use the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
<type>(<scope>): <description>
```