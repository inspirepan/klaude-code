# Repository Guidelines

Python CLI coding agent (`src/klaude_code/`) with a React web frontend (`web/`).

Module-level `AGENTS.md` files are loaded automatically when you touch files near them, so
there is no index to maintain here — put area-specific rules next to the code they govern.

## Commands

- `make lint` / `make format` / `make test` — Python + web. `make web-test` for vitest only.
- `uv run pytest tests/<area>/test_foo.py -x -q --tb=short` — single file.
- `git submodule update --init --recursive` — **required** before build/test/release; the
  bundled skills live in the `src/klaude_code/skill/assets` submodule.

## Usage Model Semantics

Internal `Usage` model (`protocol/models/usage.py`) uses **inclusive counts** — consumers must subtract when they want net values:

- `input_tokens` is the **total prompt** and includes `cached_tokens + cache_write_tokens` (for most providers: Anthropic, OpenAI responses, OpenAI chat, Google). The **exception** is Anthropic-Bedrock, whose upstream `inputTokens` is "non-cached only"; consumers that need the true total across providers use `max(input_tokens, cached_tokens + cache_write_tokens)` as a robust normalization (see `agent/cache_break_detection.py`, `agent/cache_safe.py`, `agent/prompt_suggestion/`).
- `output_tokens` is the **total output** and includes `reasoning_tokens` (thinking / Google thoughts / OpenAI reasoning). Net text output = `output_tokens - reasoning_tokens`.

TUI display (`tui/components/metadata.py`) subtracts to show net values: `input = input_tokens - cached_tokens - cache_write_tokens`, `output = output_tokens - reasoning_tokens`. New display or aggregation code must apply the same subtraction (or the `max(...)` normalization for cross-provider totals) — never treat `input_tokens` as "just the non-cached portion".

## Architecture Constraints

Layering is enforced by import-linter (`[tool.importlinter]` in `pyproject.toml`):

```
cli > tui/web > app > agent > tool/control > skill > session > config > llm > protocol > auth > log > prompts/const
```

- `prompts` is a bottom-layer pure-text package: text resources only, no logic. The system
  prompt is assembled in `agent/system_prompt.py`.
- Tools must not import from `agent`, `app`, `tui`, or `web`; they receive everything through
  `ToolContext`.
- Sub-agent profiles are declared in `protocol/sub_agent/` (bottom-up registration) while their
  runtime lives in `agent/` — adding a sub-agent means touching both.

## Model-Facing Text

Anything the model reads is context budget, so it is written once, in one place:

- Guidance about a single tool belongs in that tool's own description, not the system prompt.
  `tests/agent/test_system_prompt.py` asserts specific phrases stay out of the system prompt.
- Cross-tool orchestration (which tool to reach for, what to do after a result) belongs in
  `build_dynamic_tool_strategy_prompt`.
- Prefer expressing a constraint in the tool schema (enums, required fields, parameter
  descriptions) or enforcing it in code over restating it in prose.
- Run `/context` to see what the window is actually spent on before adding more.

## Push Workflow

- Push completed changes directly to `main`; do not create a pull request or use the `submit-pr` skill.
- Before every push, inspect the commits being pushed relative to `origin/main` and run formatting, linting, tests, and a build. All checks must pass before pushing.
- If any file under `web/` is included in the push, run the full project checks:

  ```bash
  make pre-push
  ```

- If no file under `web/` is included in the push, skip Web checks and run the Python-only equivalents:

  ```bash
  make pre-push-python
  ```

- If formatting changes files, include those changes in the commit and rerun the affected checks before pushing.

## Python Conventions

- For complex function inputs or outputs, define a Pydantic model rather than returning tuples.
- Style, line length, import order, and type-hint modernization are enforced by `ruff` and `ty`;
  run `make format` rather than hand-matching a style.
