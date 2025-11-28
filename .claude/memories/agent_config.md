# Agent Configuration for Different Models

- Prompts: configured via `get_system_prompt` in `src/klaude_code/core/prompt.py`
- Tools: configured via `get_main_agent_tools` and `get_sub_agent_tools` in `src/klaude_code/core/tool/tool_registry.py`
- Reminders: configured via `get_main_agent_reminders` and `get_sub_agent_reminders` in `src/klaude_code/core/reminders.py`
- Changes to tools under `src/klaude_code/core/tool/` require a system restart to take effect
