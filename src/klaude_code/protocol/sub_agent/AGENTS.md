# Sub-Agent Protocol

Sub-agents are specialized agent types invoked by the Task tool. Routing is done by Task's `type` parameter. This module defines profiles and registration.

## Key Constraint

The `protocol` layer cannot import from `config` or `core` (enforced by import-linter).

## Core Files

- `__init__.py` - `SubAgentProfile` dataclass and registration.
- `task.py`, `explore.py` - Individual sub-agent type definitions.

## Model Selection

Sub-agent model priority is:
1. Explicit config in `sub_agent_models` for the specific type
2. Fallback to the Task model config (if present)
3. Otherwise inherit the main agent model
