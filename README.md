# Klaude Code

A powerful coding agent CLI that brings Claude AI's coding capabilities directly to your terminal. Klaude Code provides an interactive assistant for software development tasks with persistent sessions, tool integration, and both interactive and headless modes.

## Features

- **Interactive Chat Mode**: Natural conversation interface for coding assistance
- **Headless Mode**: Direct command execution for automation and scripting
- **Persistent Sessions**: Resume conversations across multiple sessions
- **Rich Tool Integration**: File operations, code search, bash execution, and more
- **Todo Management**: Built-in task tracking and planning
- **Code-Aware**: Understands project structure and follows existing conventions

## Installation

### Requirements
- Python 3.13 or higher
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Install from PyPI (Recommended)

```bash
# Install with uv (recommended)
uv tool install klaude-code

# Or install with pip
pip install klaude-code
```

### Install from Source

```bash
# Clone the repository
git clone https://github.com/inspirepan/klaude-code.git
cd klaude-code

# Install dependencies with uv (recommended)
uv sync

# Install in development mode
uv tool install -e .
```

## Usage

### Quick Start

```bash
# Interactive mode
klaude

# Headless mode (run once and exit)
klaude --print "Fix the type errors in src/main.py"

# Continue previous session
klaude --continue

# Enable MCP (Model Context Protocol) support
klaude --mcp
```

### Interactive Mode

Start an interactive coding session:

```bash
klaude
```

This opens a chat interface where you can ask for help with coding tasks, request code changes, debug issues, and more.

#### Slash Commands

In interactive mode, use these slash commands for quick actions:

```bash
/status      # Show current configuration and model info
/clear       # Clear current chat history
/compact     # Compact conversation and freeup context window
/theme       # Switch between light and dark themes
/init        # Initialize project CLAUDE.md
```

#### Input Modes

Prefix your input with special characters for different modes:

```bash
!            # Bash mode - execute bash commands directly
             # Example: ! ls -la
             # Example: ! git status
             
*            # Plan mode - enter planning interface
             # Example: * plan the user authentication feature
             # Example: * design the database schema

#            # Memory mode - access session memory and context
             # Example: # do not add comments
             # Example: # do not use emoji

@filename    # File reference with auto-completion
             # Example: @src/main.py to reference a file
             # Example: @package.json to reference package file
```

### Headless Mode

Execute a single prompt and exit:

```bash
klaude --print "Fix the type errors in src/main.py"
```

Useful for automation and scripting:

```bash
# Run tests and fix errors
klaude --print "run tests and fix any failing tests"
```

### Continue Previous Session

Resume your latest session:

```bash
klaude --continue
```

### Command Line Options

#### Main Options

- `-p, --print <prompt>`: Run in headless mode with the given prompt
- `-r, --resume`: Choose from previous sessions to resume
- `-c, --continue`: Continue the latest session
- `--mcp`: Enable Model Context Protocol support

#### Model Configuration

- `--api-key <key>`: Override API key from config
- `--model <name>`: Override model name from config
- `--base-url <url>`: Override base URL from config
- `--max-tokens <num>`: Override max tokens from config
- `--model-azure`: Use Azure OpenAI model
- `--extra-header <header>`: Add extra HTTP header
- `--thinking`: Enable Claude Extended Thinking capability (Anthropic API only)

#### Subcommands

```bash
# Configuration management
klaude config show    # Show current configuration
klaude config edit    # Edit configuration file

# MCP (Model Context Protocol) management
klaude mcp show       # Show MCP configuration and available tools
klaude mcp edit       # Edit MCP configuration file
```


## Configuration

Klaude Code uses configuration files to manage settings like API keys and model preferences. Configuration is automatically loaded from global user settings: `~/.klaude/config.json`.

Init and edit your configuration via:


```bash
klaude config edit
```


## Available Tools

Klaude Code comes with a comprehensive set of tools for software development:

- **File Operations**: Read, write, edit, and search files
- **Code Search**: Grep, glob patterns, and intelligent code search
- **System Integration**: Bash command execution with proper quoting
- **Project Management**: Todo lists and task tracking
- **Multi-file Operations**: Batch edits and operations

## Development

### Setup Development Environment

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

## Architecture

Klaude Code is built with a modular architecture:

- **CLI Entry Point** (`cli.py`): Typer-based command interface
- **Session Management** (`session.py`): Persistent conversation history
- **Agent System** (`agent.py`): Core AI agent orchestration
- **Tool System** (`tool.py`): Extensible tool framework
- **LLM Integration** (`llm.py`): Claude API integration

### Tool Development

Tools inherit from the base `Tool` class and define:
- Input parameters via Pydantic models
- Execution logic in the `call()` method
- Automatic JSON schema generation for LLM function calling