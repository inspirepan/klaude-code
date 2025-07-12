# Klaude Code

Klaude Code is a powerful CLI tool that provides an AI-powered coding assistant. It offers an interactive interface to Claude (and OpenAI models) with advanced coding capabilities including file manipulation, code editing, task automation, and more.

## Features

- **Interactive AI Assistant**: Chat with Claude or GPT models for coding help
- **File Operations**: Read, write, edit, and search files with precision
- **Code Refactoring**: Multi-file edits, pattern replacement, and automated refactoring
- **Shell Integration**: Execute bash commands directly within the chat
- **Task Management**: Built-in todo list for tracking coding tasks
- **Session Persistence**: Resume conversations and maintain context across sessions
- **MCP Support**: Extend functionality with Model Context Protocol servers
- **Custom Commands**: Create reusable command patterns for common workflows
- **Image Support**: View and analyze images with multimodal AI capabilities

## Quick Start

### Installation

```bash
# Install with pip
pip install klaude-code

# Or install with uv (recommended)
uv tool install klaude-code
```

### Basic Usage

```bash
# Start interactive mode
klaude

# Run a single command (headless mode)
klaude --prompt "Fix the type errors in main.py"

# Resume your last session
klaude --continue

# Choose from previous sessions
klaude --resume
```

### Configuration

Configure your API keys and preferences:

```bash
# Edit configuration
klaude config edit

# View current configuration
klaude config show
```

## Usage

### Interactive Commands

Once in interactive mode, you can use various slash commands:

- `/status` - Show current configuration and model info
- `/clear` - Clear conversation history
- `/compact` - Compact conversation to free up context
- `/cost` - Show token usage and costs
- `/theme` - Switch between light, dark, light_ansi, and dark_ansi themes
- `/init` - Create a CLAUDE.md file for project-specific instructions
- `/memory` - Manage project/user memory
- `/save_custom_command` - Save conversation as reusable command

### Input Modes

Special prefixes activate different input modes:

- **Bash Mode** (`!`): Execute shell commands
  ```
  ! git status
  ! npm test
  ```

- **Plan Mode** (`*`): Enter planning interface for complex tasks
  ```
  * design the authentication system
  ```

- **Memory Mode** (`#`): Save instructions to memory
  ```
  # always use TypeScript strict mode
  ```

- **File Reference** (`@`): Reference files with auto-completion
  ```
  @main.py fix the syntax errors
  ```

- **Image Reference**: Paste images with Ctrl+V or reference image files
  ```
  [Image #1] what's in this screenshot?
  @path/to/image.png explain this diagram
  ```

### Custom Commands

Create reusable command patterns in:
- Project commands: `.claude/commands/`
- Global commands: `~/.claude/commands/`

Example custom command (`create_git_commit.md`):
```markdown
---
description: Create a git commit with context analysis
---

## Context
- Current git status: !`git status`
- Current git diff: !`git diff HEAD`

## Your task
Create a single git commit with a descriptive message.

Additional instructions: $ARGUMENTS
```

Use it as: `/create_git_commit add error handling`

## Available Tools

Klaude Code provides a comprehensive set of tools:

### File Operations
- **Read**: Read file contents with line numbers and view images
- **Write**: Create or overwrite files
- **Edit**: Make precise edits to specific lines
- **MultiEdit**: Batch multiple edits to a single file

### Search Tools
- **Grep**: Search file contents using regex patterns
- **Glob**: Find files by name patterns
- **LS**: List directory contents

### System Tools
- **Bash**: Execute shell commands with timeout support
- **TodoWrite/TodoRead**: Manage task lists
- **Task**: Spawn sub-agents for complex operations

### Usage Examples

```bash
# Refactor code
> refactor the authentication module to use JWT tokens

# Fix failing tests
> ! npm test
> fix the failing tests

# Search and replace
> rename all instances of getUserData to fetchUserData

# Create a new feature
> implement user profile management with CRUD operations

# Analyze images
> @screenshot.png what UI components are shown here?
> [paste image with Ctrl+V] explain this error message
```

## Session Management

Sessions are automatically saved and can be resumed:

```bash
# Start a new session
klaude
> implement user authentication

# Later, continue the same session
klaude --continue
> add password reset functionality
```

Sessions store:
- Complete message history
- Todo lists and their states
- File tracking information
- Working directory context

## Debugging

### Session Inspection

Sessions are stored in `.klaude/sessions/` with human-readable formats:

1. **Metadata files** (`*.metadata.*.json`): Session info, todo lists, file tracking
2. **Message files** (`*.messages.*.jsonl`): Complete conversation history

### Viewing Sessions

```bash
# List all sessions with metadata
klaude --resume

# Manually inspect session files
cd .klaude/sessions/
cat *.metadata.*.json | jq .
```

### Session File Structure

Metadata includes:
- Session ID and timestamps
- Working directory
- Message count
- Todo list with status
- Tracked file modifications

Messages are stored in JSONL format with:
- Role (user/assistant/tool)
- Content and tool calls
- Timestamps and metadata

## Requirements

- Python 3.13 or higher
- API key for Claude (Anthropic) or OpenAI
- Unix-like environment (macOS, Linux, WSL)

### Python Dependencies

Core dependencies include:
- `anthropic` - Claude API client
- `openai` - OpenAI API client
- `typer` - CLI framework
- `rich` - Terminal formatting
- `pydantic` - Data validation
- `prompt-toolkit` - Input handling
- `pillow` - Image processing
- `pyperclip` - Clipboard operations

## Model Context Protocol (MCP)

Enable MCP servers for extended functionality:

```bash
# Start with MCP enabled
klaude --mcp

# Configure MCP servers
klaude mcp edit
```

MCP allows integration with external tools and services beyond the built-in toolset.

## Tips and Best Practices

1. **Use Plan Mode** for complex tasks: `* plan the refactoring approach`
2. **Track Changes**: The AI automatically tracks file modifications
3. **Session Management**: Use `--continue` to maintain context across work sessions
4. **Custom Commands**: Create project-specific commands for repetitive tasks
5. **Context Window**: Use `/compact` when conversations get too long
6. **Cost Tracking**: Monitor usage with `/cost` command
7. **Image Analysis**: Copy screenshots to clipboard and paste with Ctrl+V for instant analysis
8. **Multimodal Workflows**: Combine code and visual elements for comprehensive development

## Command Line Options

```bash
klaude [OPTIONS] [PROMPT]

Options:
  --continue, -c              Continue from the latest session
  --resume, -r               Resume from a session
  --prompt, -p               Run in headless mode
  --model TEXT              Override the configured model
  --api-key TEXT             API key
  --api-key-env TEXT         Environment variable for API key
  --mcp                      Enable Model Context Protocol
  --theme [light|dark|light_ansi|dark_ansi]       Color theme
  --compact-mode             Minimal output mode
```

## Project Structure

```
.klaude/
├── config.json          # Global configuration
├── mcp_servers.json     # MCP server configs
├── commands/            # Custom commands
├── memory/              # Saved instructions
└── sessions/            # Conversation history
```

## Getting Help

- Use `/status` to check your configuration
- Run `klaude --help` for command options
- Check session files in `.klaude/sessions/` for debugging
- Create project-specific instructions in `CLAUDE.md`