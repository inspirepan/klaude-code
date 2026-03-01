# Sub-Agent Protocol

Sub-agents are specialized agent types invoked by the Agent tool. Routing is done by Agent's `type` parameter. This module defines profiles and registration.

## Key Constraint

The `protocol` layer cannot import from `config` or `core` (enforced by import-linter).

## Core Files

- `__init__.py` - `SubAgentProfile` dataclass and registration.
- `general_purpose.py`, `explore.py` - Individual sub-agent type definitions.

## Model Selection

Sub-agent model priority is:
1. Explicit config in `sub_agent_models` for invoker role (for example `general-purpose`, `explore`)
2. Otherwise inherit the main agent model
