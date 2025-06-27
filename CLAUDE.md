# CLAUDE.md

This file provides guidance to Klaude Code (claude.ai/code) when working with code in this repository.

## Development Commands

```bash
# Install dependencies 
uv sync

# Install in development mode
uv pip install -e .

# Format code
isort src/ && ruff format src/

# Lint code
ruff check src/
```

## Architecture Overview

Klaude Code is a Python-based CLI tool that brings Claude AI coding capabilities to the terminal. The architecture is modular with clear separation of concerns:

### Core Components

- **CLI Entry** (`cli.py`): Typer-based command interface with support for interactive and headless modes
- **Agent System** (`agent.py`): Core AI orchestration with step limits (80 headless, 100 interactive) and token management
- **Session Management** (`session.py`): Persistent conversation history with fork/resume capabilities
- **Tool Framework** (`tool.py`): Extensible tool system with automatic JSON schema generation
- **LLM Integration** (`llm.py`): Multi-provider support (Anthropic/OpenAI/Azure) with thinking mode

### Tool Categories

The tool system is organized into functional groups:

- **File Operations**: Read, Write, Edit, MultiEdit tools for file manipulation
- **Search Tools**: Grep, Glob, Ls tools for code discovery
- **System Integration**: Bash tool for command execution
- **Project Management**: TodoRead, TodoWrite for task tracking
- **Special Tools**: ExitPlanMode for workflow control

Tools inherit from `Tool` base class and define input parameters via Pydantic models.

### Input Modes

The CLI supports multiple input modes identified by prefixes:
- `!`: Bash mode for direct command execution
- `*`: Plan mode for structured planning interface  
- `#`: Memory mode for session context management
- `@filename`: File reference with auto-completion

### MCP Integration

Model Context Protocol support is available via the `--mcp` flag, allowing integration with external MCP servers for extended capabilities.

## Key Design Patterns

- **Session Forking**: Sessions can be forked to create branches for different conversation paths
- **Tool Registration**: Tools are automatically discovered and registered via decorators
- **Message Rendering**: Extensible message rendering system with custom renderers for different content types
- **Configuration Management**: Hierarchical config system with global user settings at `~/.klaude/config.json`

## Entry Points

Main entry point is `klaude` command which maps to `klaudecode.cli:app`. The CLI supports both interactive chat mode and headless execution via the `--print` flag.