# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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
```

### Code Quality
```bash
# Format code (order matters - isort first, then ruff format)
isort src/ && ruff format src/

# Lint code
ruff check src/

# Run all quality checks
isort src/ && ruff format src/ && ruff check src/
```

### Debugging & Development
```bash
# Run with verbose output
klaude --print "your prompt" --verbose

# Check configuration
klaude config show
```

## Architecture Overview

### Core Components

**CLI Entry Point** (`cli.py:15`): Uses Typer for command-line interface with both interactive and headless modes.

**Session Management** (`session.py:17`): Manages conversation history, todo lists, and persistent state. Sessions are automatically saved and can be resumed.

**Agent System** (`agent.py:50`): The main Agent class that orchestrates tool execution and LLM interactions. Supports both interactive chat and headless execution modes.

**Tool System** (`tool.py:20`): Base Tool class with automatic schema generation from Pydantic models. All tools are parallelizable by default and have configurable timeouts.

### Tool Architecture

Tools are defined in `src/klaudecode/tools/` and inherit from the base `Tool` class. Each tool:
- Defines an `Input` Pydantic model for parameters
- Implements `call()` method for execution
- Automatically generates JSON schema for LLM function calling
- Can be marked as parallelizable or not

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

### Adding New Tools
1. Create new file in `src/klaudecode/tools/`
2. Inherit from `Tool` base class
3. Define `Input` Pydantic model for parameters
4. Implement `call()` method
5. Add to `__init__.py` exports
6. Include in appropriate tool sets in `agent.py`

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
- Target Python 3.11+
- Import sorting with isort before formatting with ruff

### Configuration System
Configuration follows priority: CLI args > Environment variables > Config file (~/.klaude/config.json) > Default values

Key configuration files:
- Global config: `~/.klaude/config.json`
- Project instructions: `CLAUDE.md` (this file)

Default model: `claude-sonnet-4-20250514`

### Tool Development Pattern
Each tool in `src/klaudecode/tools/` follows this structure:
```python
class YourTool(Tool):
    name = "tool_name"
    desc = "Tool description"
    
    class Input(BaseModel):
        param: str = Field(description="Parameter description")
    
    async def call(self, input: Input, agent: Agent) -> str:
        # Implementation
        return "Result"
```

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