# CLAUDE.md

This file provides guidance to Klaude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Build and Install
```bash
# Install dependencies
uv sync

# Install in development mode
uv pip install -e .
```

### Code Quality
```bash
# Format code
isort src/ && ruff format src/

# Lint code
ruff check src/
```

### Package Management
```bash
# Build package
uv build

# Upload to PyPI
twine upload dist/*
```

### Testing
This project currently does not have a formal test suite. When adding tests, follow standard Python testing patterns.

## Architecture Overview

Klaude Code is a CLI tool that provides an AI coding assistant powered by Claude. The architecture follows a modular design:

### Core Components

**Entry Point & CLI (`cli.py`)**
- Typer-based command interface with subcommands for config and MCP management
- Supports interactive mode, headless mode, and session continuation
- Handles both synchronous CLI operations and asynchronous agent execution

**Agent System (`agent.py`)**
- `Agent` class serves as the main orchestrator and implements the `Tool` interface for sub-agents
- Manages conversation flow, tool execution, and interrupt handling
- Supports both interactive chat and headless execution modes
- Includes specialized `CodeSearchTaskTool` for read-only code analysis
- Handles plan mode activation/deactivation and user confirmations

**Session Management (`session.py`)**
- `Session` class manages conversation history, metadata, and persistence
- Uses JSONL format for incremental message storage with proper state tracking
- Integrates `TodoList` and `FileTracker` for task and file change management
- Supports session resumption and conversation compacting

**Tool System (`tool.py`)**
- Base `Tool` class with JSON schema generation for LLM function calling
- `ToolHandler` manages parallel and sequential tool execution with interrupt support
- `ToolInstance` provides runtime state management and cancellation capabilities
- Automatic timeout handling and error recovery

**LLM Integration (`llm.py`)**
- Abstracted LLM client supporting both OpenAI and Anthropic APIs
- Configurable model parameters, token limits, and thinking mode
- Handles streaming responses and tool calling protocols

### Tool Organization

**Core Tools (`tools/`)**
- File operations: `ReadTool`, `WriteTool`, `EditTool`, `MultiEditTool`
- System integration: `BashTool`, `LsTool`
- Code search: `GrepTool`, `GlobTool`
- Task management: `TodoWriteTool`, `TodoReadTool`
- Special: `ExitPlanModeTool` for plan mode workflow

**MCP Integration (`mcp/`)**
- Model Context Protocol support for extending tool capabilities
- `MCPManager` handles server connections and tool discovery
- `MCPTool` wraps external MCP tools for seamless integration

### Input and User Interface

**User Input (`user_input.py`)**
- `InputSession` handles different input modes (normal, bash, plan, memory)
- `UserInputHandler` processes special prefixes and command routing
- Integration with file auto-completion and command execution

**Terminal UI (`tui.py`)**
- Rich-based console interface with theming support
- Message rendering with syntax highlighting and formatting
- Live status updates and interactive elements

### Key Design Patterns

**Message Flow**
- Messages flow through: UserInput → Agent → LLM → Tools → ToolHandler → Agent
- Each message type (`UserMessage`, `AIMessage`, `ToolMessage`, `SystemMessage`) has specific rendering and storage behavior
- Session persistence uses incremental JSONL storage for efficiency

**Tool Execution**
- Tools can be parallelable or sequential
- Interrupt handling at multiple levels (tool, handler, agent)
- Automatic schema generation from Pydantic models for LLM function calling

**Configuration Management**
- Global config in `~/.klaude/config.json`
- MCP config in `~/.klaude/mcp_config.json`
- Project-specific sessions in `.klaude/sessions/`

## File Structure Patterns

- `command/`: Slash commands for interactive mode
- `prompt/`: System prompts and templating
- `tools/`: Individual tool implementations
- `utils/`: Utility functions for file operations, string processing
- `mcp/`: Model Context Protocol integration

## Special Notes

- The project uses Python 3.13+ and modern async/await patterns throughout
- Tool calling uses both OpenAI and Anthropic function calling formats
- Session files use JSONL format for append-only message storage
- The agent can spawn sub-agents for complex tasks while maintaining proper isolation
- Plan mode provides a special workflow for task planning and approval