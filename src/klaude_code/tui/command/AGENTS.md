# TUI Slash Commands

Slash commands available during interactive TUI sessions.

## Adding a New Command

### 1. Create the command file

Create `<name>_cmd.py` in this directory:

```python
from klaude_code.tui.command.command_abc import Agent, CommandABC, CommandResult
from klaude_code.protocol import message
from .types import CommandName

class MyCommand(CommandABC):
    @property
    def name(self) -> CommandName:
        return CommandName.MY_COMMAND  # or a plain string for non-enum commands

    @property
    def summary(self) -> str:
        return "Brief description of what this command does"

    async def run(self, agent: Agent, user_input: message.UserInputPayload) -> CommandResult:
        # user_input.text contains arguments after the command name (e.g. "/my-command arg1 arg2" -> "arg1 arg2")
        return CommandResult(events=[...])
```

### 2. Add to CommandName enum (optional but preferred)

In `types.py`:

```python
class CommandName(str, Enum):
    MY_COMMAND = "my-command"
```

### 3. Register the command

In `__init__.py`, inside `ensure_commands_loaded()`:

1. Import the command class
2. Call `register(MyCommand())` at the desired position

Registration order determines display order in slash command completion.

## Key Conventions

### CommandResult

Commands return `CommandResult` with optional fields:
- `events` - UI events to display immediately (notices, errors, model changes)
- `operations` - Operations to submit to the runtime (e.g. `RunAgentOperation`)
- `web_mode_request` - Request to switch to web UI mode

### Optional properties

- `is_interactive` (default `False`) - If `True`, the command handles its own interactive UI (e.g. model picker)
- `support_addition_params` (default `False`) - If `True`, shows a parameter hint in completion
- `placeholder` (default `"instructions"`) - Placeholder text for the parameter hint

### Agent protocol

Commands receive an `Agent` protocol object with:
- `agent.session` - The current Session (history, config, file tracker)
- `agent.profile` - The active model profile (LLM client, system prompt, tools)
- `agent.get_llm_client()` - Get the current LLM client

### String-based vs enum command names

Built-in commands use `CommandName` enum values. Both enum and plain string keys work for registration and dispatch. The registry supports prefix matching (e.g. typing `/mod` resolves to `/model`).
