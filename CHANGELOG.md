# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.2.6] - 2025-12-01

### Changed

- adjust base and large font sizes for improved readability (`02ad9fe`)

### Fixed

- update font family for improved typography and readability (`ce53f31`)
## [1.2.5] - 2025-11-30

### Added

- remove todo-write tool for gemini-3-pro (`bc88acf`)

### Changed

- simplify metadata layout and update typography (`a807f20`)
- extract executor responsibilities into dedicated managers (`a3cfc81`)

### Fixed

- unify empty tool output handling across all LLM providers (`2332cf7`)

### Other

- format (`d3521c2`)
- remove useless bash command check (`a965fa1`)
- remove useless bash command check (`172cfb4`)
## [1.2.4] - 2025-11-30

### Added

- add TOC sidebar navigation to HTML export (`38b2927`)
- add /status command to display session usage statistics (`93fd5cc`)
## [1.2.3] - 2025-11-30

### Added

- add image reminder for user-attached images (`069c4a1`)
- add cost display and improve tool args collapse in HTML export (`d87227c`)
- add cost calculation and display for LLM API calls (`fa9cd2f`)
- add --stream-json option to stream all events as JSON (`7f28d05`)
- display timestamps for messages and tool calls in HTML export (`2581bfb`)
- add created_at timestamp field to all message items (`9bd3d37`)
- add inline Mermaid diagram rendering in exported HTML (`9758655`)

### Changed

- align sub-agent ops with protocol layer and add lint-imports check (`c68687b`)
- rename and consolidate slash command utilities (`f9793c4`)
- update HTML template font and sizing (`15c98ea`)
- update prompt commands and rename dev-docs files (`d239e43`)
- normalize shimmer animation speed across text lengths (`2f565bf`)
- extract convert_usage to usage.py and rename metadata_tracker (`580faaa`)
- introduce InputAction to decouple command results from executor logic (`2182ce5`)

### Fixed

- escape bash ansi output (`9867416`)
- update system prompt rendering and adjust user input styles (`2bc18dd`)
- improve slash command rendering and update theme style (`9687883`)
- preserve existing session model_name when applying profile (`74df8bd`)
- use JSON mode for datetime serialization (`c98ddf4`)
- reset spinner status on task completion and interruption (`8dbd621`)

### Other

- format (`bab3cae`)
- format & ruff check (`04227b7`)
## [1.2.2] - 2025-11-29

### Added

- show tool call names in spinner during streaming (`04f1c9f`)
- add style for welcome in debug mode (`57c7c38`)
- replace clipboard manifest with UserInputPayload for multimodal input (`4a0c233`)

### Changed

- simplify submission API and agent initialization (`0cc1271`)
- cover cancellation propagation for Explore (`a44faa5`)
- split PromptToolkitInput into modular components (`e1b3e37`)
- extract ReasoningStreamHandler and MetadataTracker (`e5fa591`)
- move status.py to ui/rich and encapsulate spinner in REPLRenderer (`c4d0268`)
- extract event handlers and move display logic to renderer (`4e09677`)
- simplify REPLRenderer with unified renderer entry points (`eaffb74`)
- rename llm_parameter module to llm_param for brevity (`642b538`)
- standardize protocol module imports across LLM clients (`a842ff9`)
- reorganize UI module structure for clearer separation of concerns (`b57186c`)
- add ui display factory (`8f7c4fa`)
- update import paths for Agent to use module-level imports (`f78646a`)
- reorganize prompts and update agent architecture (`56e60e3`)
- use module-level imports for protocol submodules (core.tool) (`c3ab1f0`)
- move apply_config_defaults from protocol to llm/input_common (`2c18ddb`)
- use module-level imports for protocol submodules (config/command/const) (`9817611`)
- use module-level imports for protocol submodules (`32e0ac8`)
- extract common call_with_logged_payload (`ce09314`)

### Fixed

- update spinner text to use ellipsis character (`4e313b6`)
- propagate CancelledError in tool execution loop (`3bcebed`)
- show original file path instead of /dev/null for deleted files in diff view (`8c4193e`)

### Other

- Merge branch 'fix/subagent-cancel' of github.com:inspirepan/klaude-code (`d8e6af7`)
- sort & format (`e04e77e`)
- migrate pyright config from pyrightconfig.json to pyproject.toml (`5e1ec5b`)
- format (`fb10ad0`)
## [1.2.1] - 2025-11-29

### Added

- prioritize non-gitignored files in @ completion (`92d564c`)
- auto-detect terminal theme in list_models command (`66e2a0e`)
- add Write tool for file creation and overwriting (`664e78b`)
- add response metadata rendering in HTML export (`61e218a`)
- add session clean commands for managing sessions (`a76dd6f`)
- add link following capability and improve response format (`bd653eb`)
- improve source traceability for WebFetchAgent (`44af42b`)

### Changed

- split main.py into runtime, session_cmd, and terminal_control modules (`360a529`)
- simplify LLMClients initialization and cleanup (`bd09560`)
- hardcode colors in template and update font styles (`2e0ed76`)
- centralize history grouping and fix OpenRouter reasoning order (`2bae405`)
- extract MetadataAccumulator class (`2edd655`)
- use profile.llm_client.model_name as runtime source of truth (`11aa6c5`)
- simplify Agent and LLM client management (`2273952`)
- split agent.py into TaskExecutor, TurnExecutor (`fa21b67`)
- remove legacy manifest format support (`3d6649e`)
- delegate tool execution to ToolExecutor (`1e7791c`)
- decouple tool context from Session (`bcb3c6e`)
- move constant package (`f04a954`)
- split tool desc to md file (`9d8c8b6`)
- switch from hatchling to uv_build (`b415ca9`)
- switch to light theme and add collapsible sections (`1428fbf`)
- improve HTML export with better template organization (`64ca042`)
- update readme (`e87b9de`)

### Fixed

- responses api empty summary (`16958e6`)
- update GitHub username in changelog (`ca33f5a`)
- update GitHub username in changelog script (`ce7e022`)

### Other

- Refactor tool context management with context manager pattern (`d64d9da`)
- remove docs (`8b1a9ad`)
- memories (`2fa1ab3`)
- clarify memory tool project scope (`8b1016a`)
## [1.2.0] - 2025-11-27

### Added

- add WebFetchAgent sub-agent for fetching and analyzing web content (`82e2e87`)
- add Memory tool for persistent context storage (`cbbb17b`)
- add cache control support for Gemini models via OpenRouter (`ca403cd`)
- add cache control support for Claude models via OpenRouter (`5e010f1`)
- press 'c' to copy selected text to system clipboard (`2689cbd`)

### Changed

- add input shortcuts section to README (`ea4b5ba`)

### Fixed

- update model text bullet style in response metadata rendering (`f138846`)
- Move dev docs back to dev/active (`f620ff4`)
- update memory tool mark (`67ba1cc`)
- improve sub-agent color handling and replay rendering (`80ce897`)
- update memory tool mark (`c0a0417`)
- style welcome metadata prefixes (`e298e3b`)
- handle text selection when pressing backspace (`c4ad37b`)
## [1.1.0] - 2025-11-27

### Added

- enable dynamic mouse support based on input content (`483a3e1`)
- support arrow key wrapping across lines in multiline input (`93069de`)

### Changed

- update installation instructions to use uv tool (`d69311b`)

### Fixed

- update bullet style and spinner mark for consistency; clean up markdown rendering (`968041f`)

### Other

- adjust shimmer and spinner animation timings for consistency (`c6dc386`)
## [1.0.6] - 2025-11-27

### Added

- add syntax highlighting to markdown code blocks (`65e7c19`)
- add breathing spinner animation and improve streaming stability (`a778c63`)
- add --version option and organize help panels (`27e3d22`)
- add PaddedStatus wrapper for improved status display (`62a55d1`)

### Fixed

- update spinner animation duration and color for consistency (`ab2ff3e`)
- remove ellipsis in stream markdown (`b29e88d`)
- improve streaming stability (`bfa064a`)
- improve session selector UI and fix message count calculation (`8fada4a`)
- improve markdown code block styling with panel (`5e3181e`)

### Other

- Revert "feat(ui): add PaddedStatus wrapper for improved status display" (`63b06af`)
## [1.0.5] - 2025-11-26

### Added

- add shimmer animation effect to status text (`0a9e3f9`)
- add copy button for Mermaid code (`fb3565f`)

### Changed

- update marker character (`5cae7a3`)
- remove unused Rule import and grid line separator (`3b47ed3`)
- use softer diff highlight colors (`7b3684f`)
- use tree-style prefixes for welcome panel config items (`9dd5460`)

### Fixed

- change default spinner name from 'copilot' to 'claude' (`05d4c31`)
- reduce flicker during spinner-to-stream transition (`b4c3055`)
- reduce maximum lines for sub-agent result display from 30 to 12 (`49d92f2`)
- cursor disappears after double ctrl+c in Ghostty (`b86b753`)

### Other

- format imports (`3beefa9`)
## [1.0.4] - 2025-11-25

### Added

- show Klaude Code version in welcome panel (`c708383`)

### Changed

- adjust welcome panel theme colors and styling (`2477d80`)
- async version check to avoid blocking status bar (`24ab994`)
## [1.0.3] - 2025-11-25

### Fixed

- correct hatch build configuration to include Python files (`1c45516`)
## [1.0.2] - 2025-11-25

### Added

- add version update check in bottom toolbar (`a54cdfd`)
- enhance tool details display with expandable parameters (`06ae101`)
- add copy button for raw assistant message content in HTML export (`1195d61`)
- show diff for file creation in HTML export (`b8dd4c4`)
- improve todo list display in HTML export (`45e9640`)
- add publish skill for version release workflow (`24a5af2`)

### Changed

- increase tool output max length and simplify gemini prompt (`796c0c6`)
- simplify collapsible details styling in HTML export (`73fc471`)

### Fixed

- switch font to IBM Plex Mono and fix meta value overflow (`70465c1`)
## [1.0.1] - 2025-11-25

### Added

- add support message for unsupported PDF file reading (`9babe56`)
- implement smart truncation strategy with head/tail display (`3bfbcc0`)
- use logging (`3bd72f6`)

### Changed

- centralize constants into dedicated module (`06e26ec`)
- simplify skill loading by consolidating directory management (`586edf2`)

[Unreleased]: https://github.com/inspirepan/klaude-code/compare/v1.2.6...HEAD
[1.2.6]: https://github.com/inspirepan/klaude-code/compare/v1.2.5...v1.2.6
[1.2.5]: https://github.com/inspirepan/klaude-code/compare/v1.2.4...v1.2.5
[1.2.4]: https://github.com/inspirepan/klaude-code/compare/v1.2.3...v1.2.4
[1.2.3]: https://github.com/inspirepan/klaude-code/compare/v1.2.2...v1.2.3
[1.2.2]: https://github.com/inspirepan/klaude-code/compare/v1.2.1...v1.2.2
[1.2.1]: https://github.com/inspirepan/klaude-code/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/inspirepan/klaude-code/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/inspirepan/klaude-code/compare/v1.0.6...v1.1.0
[1.0.6]: https://github.com/inspirepan/klaude-code/compare/v1.0.5...v1.0.6
[1.0.5]: https://github.com/inspirepan/klaude-code/compare/v1.0.4...v1.0.5
[1.0.4]: https://github.com/inspirepan/klaude-code/compare/v1.0.3...v1.0.4
[1.0.3]: https://github.com/inspirepan/klaude-code/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/inspirepan/klaude-code/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/inspirepan/klaude-code/compare/v1.0.0...v1.0.1
