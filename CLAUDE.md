# CLAUDE.md

This file provides guidance to Klaude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Installation & Setup
```bash
# Install dependencies
uv sync

# Install in development mode
uv pip install -e .
```

### Running
```bash
# Run the CLI directly
klaude

# Run with prompt (headless mode)
klaude --print "your prompt here"

# Continue latest session
klaude --continue

# Edit configuration
klaude config edit

# Enable MCP (Model Context Protocol) support
klaude --mcp
```

### Interactive Features
```bash
# Available slash commands in interactive mode:
/status      # Show current configuration
/today       # Show today's tasks
/recent      # Show recent tasks
/clear       # Clear chat history
/compact     # Toggle compact view
/continue    # Continue previous session

# Input modes (prefix with key):
!            # Bash mode - execute bash commands directly
*            # Plan mode - planning interface

# File reference syntax:
@filename    # Reference files with auto-completion
```

### Code Quality
```bash
# Format code (order matters - isort first, then ruff format)
isort src/ && ruff format src/

# Lint code
ruff check src/

# Run all quality checks
isort src/ && ruff format src/ && ruff check src/

# Type checking (no mypy - relies on IDE/editor for type checking)
```

### Testing
```bash
# No test framework configured - verify functionality manually
klaude --print "test prompt"

# Test specific functionality
klaude config show  # Verify configuration
klaude --continue   # Test session resumption
```

# Check configuration
klaude config show
```

## Architecture Overview

### Core Components

**CLI Entry Point** (`cli.py:16`): Uses Typer for command-line interface with both interactive and headless modes. Supports MCP integration via `--mcp` flag.

**Session Management** (`session.py:57`): Manages conversation history, todo lists, and persistent state. Sessions are automatically saved to `.klaude/sessions/` and can be resumed or forked.

**Agent System** (`agent.py:51`): The main Agent class that orchestrates tool execution and LLM interactions. Supports both interactive chat and headless execution modes. Agent itself is a Tool that can spawn sub-agents for complex tasks.

**Tool System** (`tool.py:19`): Base Tool class with automatic schema generation from Pydantic models. All tools are parallelizable by default and have configurable timeouts.

**Agent-as-Tool**: The Agent class implements the Tool interface (`agent.py:51`), enabling recursive agent execution with different tool sets and scopes.

**Tool Categories**: 
- BASIC_TOOLS (`agent.py:45`): Full file system and bash access for general development
- READ_ONLY_TOOLS (`agent.py:46`): Limited tools for sub-agents to prevent unsafe operations

**LLM Integration** (`llm.py`): Handles communication with language models (Anthropic Claude, OpenAI). Supports prompt caching and token counting.

**Message System** (`message.py`): Rich message types (SystemMessage, UserMessage, AIMessage, ToolMessage) with rendering support for the terminal interface.

**Session Persistence**: Sessions are automatically saved to `.klaude/sessions/` with structured filenames including timestamps and conversation titles for easy retrieval.

**MCP Support** (`mcp/`): Model Context Protocol integration for external tool providers and enhanced capabilities.

### Project Structure

```
src/klaudecode/
├── prompt/          # System prompts and AI behavior configuration
├── tools/           # Individual tool implementations
├── agent.py         # Main Agent orchestrator 
├── cli.py           # Typer-based CLI entry point
├── session.py       # Session persistence and management
├── tool.py          # Base Tool class and execution framework
├── config.py        # Configuration management
├── llm.py           # LLM integration (Anthropic/OpenAI)
└── tui.py           # Terminal UI components with Rich
```

Key architectural patterns:
- Tool-based architecture where even the Agent is a Tool
- Async/await throughout for parallel tool execution
- Pydantic models for all data structures and validation
- Rich library for all terminal output and formatting

### Tool Architecture

Tools are defined in `src/klaudecode/tools/` and inherit from the base `Tool` class. Each tool:
- Defines an `Input` Pydantic model for parameters
- Implements `call()` method for execution
- Automatically generates JSON schema for LLM function calling
- Can be marked as parallelizable or not (default: True)
- Has configurable timeout (default: 300s)

**Available Tools**: BashTool, EditTool, GlobTool, GrepTool, LsTool, MultiEditTool, ReadTool, TodoReadTool, TodoWriteTool, WriteTool

**Tool Sets**: 
- `BASIC_TOOLS`: Full read/write access
- `READ_ONLY_TOOLS`: Limited to read operations

### Session System

Sessions store:
- Message history (SystemMessage, UserMessage, AIMessage, ToolMessage)
- Todo lists with status tracking
- Working directory context
- Unique session IDs for persistence

Sessions support forking for creating new branches from existing conversations.

### Configuration System

Configuration uses a priority system: CLI args > Environment variables > Config file > Default values

Key configuration options:
- `model_name`: AI model to use (default: claude-sonnet-4-20250514)
- `api_key`: API credentials
- `max_tokens`: Response length limit (default: 8196)
- `context_window_threshold`: Context management (default: 200000)

### System Prompt Structure

The system prompt consists of:
1. **Static System Prompt**: Core instructions and behavior (cached)
2. **Dynamic System Prompt**: Environment-specific context including:
   - Working directory and git status
   - Directory structure
   - Current date and platform info
   - Model-specific guidance

## Key Development Patterns

### Tool Parallelization
Tools marked as `parallelable=True` can run concurrently using `ToolHandler.run_tools_parallel()`. This is essential for performance when reading multiple files or running independent operations.

### Error Handling Patterns
- Tools should catch exceptions and return meaningful error messages
- LLM errors (AnthropicError, OpenAIError) are handled at the agent level
- Use Rich formatting for error output in terminal

### Agent-as-Tool Pattern
The Agent class itself implements the Tool interface (`agent.py:50`), enabling recursive agent execution with different tool sets and scopes. Sub-agents typically use READ_ONLY_TOOLS to prevent unsafe operations.

### Adding New Tools
1. Create new file in `src/klaudecode/tools/`
2. Inherit from `Tool` base class
3. Define `Input` Pydantic model for parameters
4. Implement `call()` method
5. Add to `__init__.py` exports
6. Include in appropriate tool sets in `agent.py`

### Python Version Requirements
- Requires Python 3.13+ (as specified in pyproject.toml)
- Target version for ruff: py313
- Note: README.md incorrectly states 3.11+ - should be updated to match pyproject.toml

### Known Issues
- README.md states Python 3.11+ requirement but pyproject.toml requires 3.13+ - use 3.13+

### Message Flow
1. User input → UserMessage
2. Agent processes with LLM → AIMessage with tool calls
3. Tools execute → ToolMessage results
4. Loop continues until completion

### Error Handling
- Tools should handle their own exceptions gracefully
- Agent catches LLM errors (AnthropicError, OpenAIError)
- Session management includes interruption handling

### Testing
Tests should be organized by component and use the existing tool patterns for file operations. Currently no test framework is configured - tests would need to be added as needed.

## Development Patterns

### Code Style Guidelines
- Use single quotes for strings (configured in ruff)
- Line length limit: 180 characters
- Target Python 3.13+
- Import sorting with isort before formatting with ruff

### Configuration System
Configuration follows priority: CLI args > Environment variables > Config file (~/.klaude/config.json) > Default values

Key configuration files:
- Global config: `~/.klaude/config.json`
- Project instructions: `CLAUDE.md` (this file)

Default model: `claude-sonnet-4-20250514`

### Session and Message System
- Sessions persist automatically in the working directory
- Message types: SystemMessage, UserMessage, AIMessage, ToolMessage
- SystemMessage can be cached for performance
- Sessions support forking for branching conversations

### Prompt System Architecture
Prompts are modular and located in `src/klaudecode/prompt/`:
- `system.py`: Core system prompts (static + dynamic)
- `tools.py`: Tool-specific prompt components  
- `reminder.py`: Context-aware reminders (todo, language, etc.)
- `commands.py`: User command handling prompts

Dynamic system prompts include environment context (working directory, git status, date/time, platform info).