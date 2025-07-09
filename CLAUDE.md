# CLAUDE.md

This file provides guidance to Klaude Code (claude.ai/code) when working with code in this repository.

## Build and Development Commands

### Install Dependencies
```bash
# Install with uv (recommended)
uv sync

# Install in development mode
uv pip install -e .
```

### Code Quality Commands
```bash
# Format code
ruff format .

# Run linter
ruff check . --fix
```

### Testing
```bash
# First time setup: create virtual environment
uv venv

# Activate virtual environment (needed every time)
source .venv/bin/activate

# Install dependencies (only needed once or when dependencies change)
uv sync

# Run all tests (detailed output)
uv run python -m pytest tests/ -v

# Run all tests (quick/concise output, recommended for regular checks)
uv run python -m pytest tests/ -q

# Alternative test runner (also available)
uv run python tests/run_tests.py

# Run specific test file
uv run python -m pytest tests/tools/test_read.py -v

# Run specific test category
uv run python tests/run_tests.py tools

# Run with short error messages (useful for debugging)
uv run python -m pytest tests/ -v --tb=short

# Run with coverage
uv run python -m pytest tests/ --cov=src/klaudecode --cov-report=html
# Or using the test runner
uv run python tests/run_tests.py --cov
```

### Development Tips
- Python 3.13+ is required
- Use `uv` package manager for dependency management
- Ruff is configured with line-length 180 and single quotes
- Always run tests in a virtual environment to ensure proper dependency isolation
- The main package is `klaudecode` under `src/`
- Entry point is `klaudecode.cli:app` defined in pyproject.toml
- **When asked to run all tests**: Use `uv run python -m pytest tests/ -q` for quick overview, then fix any failures with `uv run python -m pytest tests/ -v --tb=short` for detailed debugging

## Architecture Overview

### Core Components

1. **Session Management** (`session.py`)
   - Manages persistent conversation history with JSONL storage
   - Tracks message states and implements automatic compaction
   - Handles todo list persistence and file tracking

2. **Agent System** (`agent.py`)
   - Central orchestrator that coordinates LLM, tools, and user interaction
   - Manages interrupt handling and usage tracking
   - Supports both interactive and headless modes

3. **Tool Framework** (`tool.py` and `tools/`)
   - Base `Tool` class with automatic JSON schema generation
   - Tools implement `call()` method for execution logic
   - Tool results can have custom renderers via decorators

4. **LLM Integration** (`llm/`)
   - Proxy pattern for multiple providers (Anthropic, OpenAI, Azure)
   - Streaming support with status tracking
   - Configurable via global config or command-line overrides

5. **Message System** (`message/`)
   - Type-safe message classes for all roles (user, assistant, tool, system)
   - Registry pattern for custom rendering based on message type
   - Special handling for tool calls and results
