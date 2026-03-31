# Sub-Agent Protocol

Sub-agents are specialized agent types invoked by the Agent tool. Routing is done by Agent's `type` parameter. This module defines profiles and registration.

## Key Constraint

The `protocol` layer cannot import from `config` or `core` (enforced by import-linter).

## Core Files

- `__init__.py` - `SubAgentProfile` dataclass and registration.
- `general_purpose.py`, `finder.py`, `review.py`, `memory.py` - Individual sub-agent type definitions.

## Model Selection

Sub-agent model priority is:
1. Explicit config in `sub_agent_models` by profile name (e.g. `general-purpose`, `finder`)
2. Otherwise inherit the main agent model

## Fork Context Mode

Profiles with `fork_context=True` inherit the parent agent's full conversation history and profile (system prompt + tools). This maximizes prefix cache hits since the system prompt and tool definitions remain identical.

Runtime behavior (in `core/agent/runtime_sub_agent.py`):
- System prompt and tools: inherited from the parent agent (profile's `tool_set` is ignored)
- Conversation history: forked up to the last AssistantMessage
- Identity switch: injected as a `<system-reminder>` appended after the forked history

### Identity Switch Prompt Pattern

Fork-context sub-agents use an **identity switch** pattern rather than a separate system prompt. The forked history preserves cache, and a trailing `<system-reminder>` tells the model it is no longer the main agent.

**With `prompt_file`** (e.g. review agent used with fork): the prompt_file content is inlined directly after the identity preamble -- no "Your role instructions:" header.

```
<system-reminder>You are no longer the main coding agent. You are now acting as
a specialized sub-agent. The conversation history above was forked from the parent
session -- use it as background context only. Do NOT use the Agent tool to spawn
sub-agents.

[prompt_file content here, with $workingDirectory/$workspaceRoot substituted]
</system-reminder>
```

**Without `prompt_file`** (e.g. `general-purpose-fork-context`): a generic identity switch.

```
<system-reminder>You are a newly spawned agent with the full conversation context
from the parent session. Treat the next user message as your new task, and use
the conversation history as background context. Do NOT use the Agent tool to spawn
sub-agents.</system-reminder>
```

When writing prompt files for fork-context sub-agents, write them as if they are the agent's self-description, not as instructions addressed to a third party. The content will be read by the model immediately after "You are now acting as a specialized sub-agent."
