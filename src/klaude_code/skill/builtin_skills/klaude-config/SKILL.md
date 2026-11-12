---
name: klaude-config
description: Reference for klaude-code configuration, skill installation, memory file locations, and the background-agent CLI. Use when the user asks to configure a provider or model from an endpoint and API key, install skills, locate config/skill/memory files, or orchestrate background agents.
metadata:
  short-description: Config, skill, and CLI reference
---

# klaude-config

Read only the references relevant to the user's question:

- [Configuration file](references/config-file.md): configuration fields, model selection, credentials, and merging.
- [Builtin providers](references/builtin-providers.md): provider configuration, authentication, and model defaults.
- [Background agents](references/background-agents.md): background commands, session communication, and orchestration.
- [Skill system](references/skill-system.md): skill installation, directories, discovery, and precedence.
- [Memory files](references/memory-files.md): memory locations and discovery.

References describe particular versions and may be outdated. When the answer depends on the installed version, check `klaude --help`, the relevant `klaude <command> --help`, and `klaude agents` if available. Use the commands and model inventory exposed by that installation; do not assume the current source checkout represents every installation. If a command is unavailable, use the installed CLI's help to find the applicable alternative.

For an endpoint and API key, follow the custom provider workflow in [Configuration file](references/config-file.md). Guide the user or edit their configuration when authorized; do not expose the key or make a remote API request without authorization.
