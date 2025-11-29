# Adding a New Sub Agent

1) Register the sub agent profile (`src/klaude_code/core/sub_agent.py`)

```python
MY_AGENT_DESCRIPTION = """Description shown to the main agent..."""

MY_AGENT_PARAMETERS = {
    "type": "object",
    "properties": {
        "description": {"type": "string", "description": "Short task description"},
        "prompt": {"type": "string", "description": "The task to perform"},
    },
    "required": ["description", "prompt"],
}

register_sub_agent(
    SubAgentProfile(
        name="MyAgent",                    # Used as tool name, config key, and prompt key
        description=MY_AGENT_DESCRIPTION,
        parameters=MY_AGENT_PARAMETERS,
        tool_set=(tools.BASH, tools.READ),  # Tools available to this sub agent
        # Optional fields:
        # prompt_builder=custom_prompt_builder,  # Custom function to build prompt from args
        # target_model_filter=lambda m: True,    # Filter which main models can use this agent
        # enabled_by_default=True,
        # show_in_main_agent=True,
    )
)
```

2) Add prompt file mapping (`src/klaude_code/core/prompt.py`)

```python
PROMPT_FILES: dict[str, str] = {
    # ... existing entries ...
    "MyAgent": "prompts/prompt-subagent-myagent.md",
}
```

3) Create the prompt file

Create `src/klaude_code/core/prompts/prompt-subagent-myagent.md` with the system prompt content.

4) Add prompt file to build config (`pyproject.toml`)

```toml
"src/klaude_code/core/prompts/prompt-subagent-myagent.md" = "klaude_code/core/prompts/prompt-subagent-myagent.md"
```

Notes:
- The `name` field is case-sensitive for prompt lookup but case-insensitive for user config (e.g., `myagent` in config maps to `MyAgent`)
- No need to modify `protocol/tools.py` or create separate tool files
- Sub agent tools are automatically registered at startup
