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
from klaude_code.tool.core.context import ToolContext
from klaude_code.tool.core.abc import ToolABC, load_desc
from klaude_code.tool.core.registry import register

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
        return message.ToolResultMessage(status="success", output_text="done")
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
- `todo_context` - Restricted read/replace access to the current todo list
- `session_id` - Session that owns the tool call
- `request_user_interaction` - Callback for asking the user questions
- `run_subtask` - Callback for spawning sub-agent tasks
- `handoff_manager` - Session-control interface
- `emit_tool_output_delta` - Optional callback for streaming tool output

Tools must not import from `agent`, `app`, `tui`, `server`, or `cli` (enforced by the layering contract in `pyproject.toml`).

### ToolMetadata

Override `metadata()` to change defaults:
- `concurrency_policy`: `SEQUENTIAL` (default) or `CONCURRENT`. Concurrent tools can run in parallel when the LLM issues multiple tool calls.
- `has_side_effects`: Whether the tool modifies external state.
- `requires_tool_context`: Set `False` for tools that don't need context (rare).

### Result format

Return `message.ToolResultMessage` with:
- `status`: `"success"`, `"error"`, or `"aborted"`
- `output_text`: Text shown to the LLM
- `ui_extra`: Optional structured data for richer TUI/web rendering
- `side_effects`: Optional list of file operations for tracking

Keep internal state separate from model-facing results:
- Keep runtime state, persistence, and UI data structured; do not dump internal models as JSON into `output_text`.
- Format `output_text` as concise, readable text with facts and identifiers needed for the next action.
- UI consumers must use structured data such as `ui_extra`, not parse the model-facing text.
- Preserve JSON when it is the requested content, such as a file, API response, or task report.
- Apply the same separation to automatic notifications that deliver tool or task results to the model.

### Tool name constants

All tool names live in `protocol/tools.py`. Never hardcode tool name strings elsewhere.
