# CLAUDE.md

This file provides guidance to Klaude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Klaude Code is a Python CLI tool that provides an interactive coding assistant powered by Claude AI. It features both interactive chat mode and headless automation mode, with persistent sessions and extensive tool integration.

## Development Commands

### Environment Setup
```bash
# Install dependencies
uv sync

# Install in development mode  
uv pip install -e .
```

### Code Quality
```bash
# Lint code
ruff check --fix src/

# Format and lint together
isort src/ && ruff format src/
```

### Testing
There are no automated tests in this repository. Test functionality manually using:
```bash
# Test basic functionality
klaude --print "hello world"

# Test interactive mode
klaude
```

## Architecture

### Core Components

- **CLI Entry Point** (`cli.py`): Typer-based command interface with subcommands for config and MCP management
- **Agent System** (`agent.py`): Orchestrates AI interactions, tool execution, and conversation flow
- **Session Management** (`session.py`): Handles persistent conversation history with JSONL storage
- **Tool Framework** (`tool.py`): Base class and execution framework for all tools
- **LLM Integration** (`llm/`): Abstracts multiple LLM providers (Anthropic, OpenAI) with unified interface
- **Message System** (`message/`): Type-safe message handling with tool calls and results

### Tool System

Tools inherit from `Tool` base class and define:
- Input parameters via Pydantic models
- Execution logic in `call()` method
- Automatic JSON schema generation for LLM function calling
- Parallel execution support (configurable per tool)

Available tools:
- File operations: `ReadTool`, `WriteTool`, `EditTool`, `MultiEditTool`
- Code search: `GrepTool`, `GlobTool`, `LsTool`
- System integration: `BashTool` (with proper path quoting)
- Task management: `TodoWriteTool`, `TodoReadTool`
- Planning: `ExitPlanModeTool`

### Session Persistence

Sessions are stored as JSONL files in `.klaude/sessions/` with:
- Incremental message storage
- File change tracking
- Session metadata (title, message count, timestamps)
- Context window management with automatic compaction

### Configuration System

Three-tier configuration with priority:
1. CLI arguments (highest)
2. Environment variables
3. Config file `~/.klaude/config.json`

Supports multiple LLM providers and deployment types (standard, Azure).

### Input Modes

Special input prefixes in interactive mode:
- `!` - Bash mode (direct command execution)
- `*` - Plan mode (structured planning interface)
- `#` - Memory mode (session context management)
- `@filename` - File reference with auto-completion

### MCP Integration

Model Context Protocol support for external tools:
- Configuration in `~/.klaude/mcp.json`
- Dynamic tool discovery and registration
- Async client management

## Key Design Patterns

1. **Async-First**: All core operations use async/await for better concurrency
2. **Pydantic Models**: Type-safe data structures throughout
3. **Rich UI**: Terminal UI with themes, formatting, and progress indicators
4. **Tool Parallelization**: Tools can run concurrently when marked as parallelable
5. **Error Recovery**: Graceful handling of API errors and interruptions
6. **Context Management**: Automatic token counting and conversation compaction

## Important Notes

- Minimum Python 3.13 required
- Uses `uv` as primary package manager
- No traditional test suite - relies on manual testing
- Rich terminal UI with theming support
- Supports both Claude and OpenAI models
- Session files use JSONL format for streaming
- File operations include external change detection