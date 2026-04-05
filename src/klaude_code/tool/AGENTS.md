# Tool Module

Tool implementations invoked by the LLM agent.

## Adding a New Tool

### 1. Define the tool name constant

Add to `protocol/tools.py`:

```python
MY_TOOL = "MyTool"
```

### 2. Create the tool class

Create a new file (e.g. `my_tool.py` or `category/my_tool.py`). Implement `ToolABC`:

```python
from klaude_code.protocol import llm_param, message, tools
from klaude_code.tool.context import ToolContext
from klaude_code.tool.tool_abc import ToolABC, load_desc
from klaude_code.tool.tool_registry import register

@register(tools.MY_TOOL)
class MyTool(ToolABC):
    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name=tools.MY_TOOL,
            description="...",
            input_schema={...},
        )

    @classmethod
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        # Parse arguments (JSON string), do work, return result
        return message.ToolResultMessage(status="ok", output_text="done")
```

### 3. Tool descriptions

For long descriptions, put them in a `.md` file next to the tool and load with `load_desc()`:

```python
_DESC = load_desc(Path(__file__).parent / "my_tool.md")
```

### 4. Register in `__init__.py`

Import the tool class in `tool/__init__.py` and add it to `__all__`.

### 5. Add to sub-agent tool sets

If the tool should be available to sub-agents, add the tool name to the relevant `tool_set` tuples in `protocol/sub_agent/` profile definitions.

## Key Conventions

### ToolABC interface

All tools are stateless classmethods:
- `schema()` - Returns the JSON schema shown to the LLM
- `call(arguments, context)` - Executes the tool; `arguments` is a raw JSON string
- `metadata()` - Optional. Override to declare concurrency policy or side effects

### ToolContext

Tools receive a `ToolContext` with:
- `work_dir` - Current working directory
- `file_tracker` - Tracks file read/write state for dedup and external change detection
- `todo` - Todo list context
- `request_user_interaction` - Callback for asking the user questions
- `run_subtask` - Callback for spawning sub-agent tasks
- `request_handoff` / `request_rewind` - Callbacks for session control

Tools should NOT import from `agent`, `app`, `tui`, or `web` layers (enforced by import-linter).

### ToolMetadata

Override `metadata()` to change defaults:
- `concurrency_policy`: `SEQUENTIAL` (default) or `CONCURRENT`. Concurrent tools can run in parallel when the LLM issues multiple tool calls.
- `has_side_effects`: Whether the tool modifies external state.
- `requires_tool_context`: Set `False` for tools that don't need context (rare).

### Result format

Return `message.ToolResultMessage` with:
- `status`: `"ok"` or `"error"`
- `output_text`: Text shown to the LLM
- `ui_extra`: Optional structured data for richer TUI/web rendering
- `side_effects`: Optional list of file operations for tracking

### Tool name constants

All tool names live in `protocol/tools.py`. Never hardcode tool name strings elsewhere.
