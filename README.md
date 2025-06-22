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
- Python 3.11 or higher
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Install from Source

```bash
# Clone the repository
git clone <repository-url>
cd klaude-code

# Install dependencies with uv (recommended)
uv sync

# Install in development mode
uv pip install -e .
```

## Usage

### Interactive Mode

Start an interactive coding session:

```bash
klaude
```

This opens a chat interface where you can ask for help with coding tasks, request code changes, debug issues, and more.

### Headless Mode

Execute a single prompt and exit:

```bash
klaude --print "Fix the type errors in src/main.py"
```

### Continue Previous Session

Resume your latest session:

```bash
klaude --continue
```

### Command Line Options

- `-p, --print <prompt>`: Run in headless mode with the given prompt
- `-c, --continue`: Continue the latest session
- `-v, --verbose`: Enable verbose output (shows tool execution traces)
- `--config <path>`: Use custom configuration file

## Configuration

Klaude Code uses configuration files to manage settings like API keys and model preferences. Configuration is automatically loaded from global user settings: `~/.config/klaude/config.json`.

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
ruff format src/

# Lint code
ruff check src/

# Sort imports
isort src/
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