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
2. `core/agent_profile.py#_check_availability_requirement()` checks if requirement is met
3. `core/manager/llm_clients_builder.py#_resolve_model_for_requirement()` finds a suitable model when none is configured
4. `config/config.py` provides query methods (`has_available_image_model()`, `get_first_available_image_model()`)

## Model Selection

For sub-agents with `availability_requirement`, priority is:
1. Explicit config in `sub_agent_models`
2. Auto-resolve via requirement
3. If neither found, sub-agent is unavailable (no fallback to main agent model)
