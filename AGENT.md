# AGENT.md - Klaude Code Development Guide

## Build/Test Commands
- **Format**: `ruff format .`
- **Lint**: `ruff check . --fix`  
- **All tests**: `uv run python -m pytest tests/ -q` (quick) or `uv run python -m pytest tests/ -v` (verbose)
- **Single test**: `uv run python -m pytest tests/tools/test_read.py -v`
- **Test by category**: `uv run python tests/run_tests.py tools`
- **With coverage**: `uv run python -m pytest tests/ --cov=src/klaudecode --cov-report=html`
- **Dependencies**: `uv sync` (requires Python 3.13+)

## Architecture
- **Session system** (`session/`): Message history, persistence, compaction, todo tracking
- **Agent orchestration** (`agent/`): LLM coordination, tool execution, sub-agents, interrupt handling
- **Tool framework** (`tool/`, `tools/`): Base classes with JSON schema, concrete implementations
- **LLM integration** (`llm/`): Multi-provider proxy (Anthropic, OpenAI, Azure) with streaming
- **MCP support** (`mcp/`): Model Context Protocol for external tool integration
- **CLI interface** (`cli/`): Commands, config management, file editing, updates
- **Message system** (`message/`): Type-safe classes for all roles with custom rendering

## Code Conventions
- **Imports**: Standard library → third-party → local (relative imports preferred)
- **Naming**: PascalCase classes, snake_case functions/vars, UPPER_SNAKE_CASE constants
- **Types**: Full annotations, Pydantic models, `typing` module, `TYPE_CHECKING` for circulars
- **Async**: Generators for streaming, ThreadPoolExecutor for CPU tasks, proper cancellation
- **Errors**: Specific exception handling, validation before execution, graceful degradation
- **Style**: Ruff configured for Python 3.13, no specific line length in config
