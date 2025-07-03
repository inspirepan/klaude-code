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
isort src/ && ruff format src/

# Run linter
ruff check src/ --fix
```

### Development Tips
- Python 3.13+ is required
- Use `uv` package manager for dependency management
- Ruff is configured with line-length 180 and single quotes

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

### Key Design Patterns

- **Interrupt Handling**: Global interrupt flag pattern with graceful cleanup
- **Streaming**: AsyncIterator pattern for real-time LLM responses
- **Tool Discovery**: Dynamic tool registration based on available imports
- **Message Rendering**: Visitor pattern for customizable output formatting

### Important Conventions

- All file paths in tools must be absolute, not relative
- Tool parameters use Pydantic models for validation
- Messages are stored incrementally in JSONL format
- Custom commands are discovered from `.klaude/commands/` directory