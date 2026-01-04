# Sub-Agent Protocol

Sub-agents are specialized agents invoked by the main agent as tools. This module defines profiles and registration.

## Key Constraint

The `protocol` layer cannot import from `config` or `core` (enforced by import-linter). Availability checks are delegated to upper layers via string constants.

## Core Files

- `__init__.py` - `SubAgentProfile` dataclass and registration. Defines `AVAILABILITY_*` constants.
- `image_gen.py`, `task.py`, `explore.py`, `web.py` - Individual sub-agent definitions.

## Availability Requirement Flow

Some sub-agents require specific model capabilities (e.g., ImageGen needs an image model). The flow:

1. `SubAgentProfile.availability_requirement` stores a constant (e.g., `AVAILABILITY_IMAGE_MODEL`)
2. `config/sub_agent_model_helper.py` checks if the requirement is met based on `config/config.py`
3. `config/sub_agent_model_helper.py` resolves the default model when unset (e.g., first available image model)
4. Core builders/UI call into the helper to avoid dealing with requirement constants directly

## Model Selection

For sub-agents with `availability_requirement`, priority is:
1. Explicit config in `sub_agent_models`
2. Auto-resolve via requirement
3. If neither found, sub-agent is unavailable (no fallback to main agent model)
