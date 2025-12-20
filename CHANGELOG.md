# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.2.23] - 2025-12-20

### Added
- add system skills auto-installation from bundled assets (`ca20403`)
- extract skill module and add $skill UX (`880c468`)
- sort skills by priority (project > user > system) (`2c4dfb3`)
- add adaptive placeholder styles based on terminal background (`ac98eb7`)
- support metadata.short-description for REPL completions (`2dd3127`)

### Changed
- support ¥ as skill trigger prefix for Chinese input (`3bb3655`)
- improve skill loading and terminology (`2198796`)
- convert prompt commands to built-in system skills (`9cc04d9`)
- improve diff color contrast for better readability (`f39b30c`)
- update diff header (`4c406f0`)
- unify UI marker constants and improve prompt styling (`8a5bf91`)
- update spinner glyph (`9cabc31`)
- exclude default and none in session (`6be03fa`)
- update readme (`29b6ccc`)
- update display limits and add separator in REPL (`cdaf23f`)
- update tool marks (`3772402`)

### Fixed

- reserve markdown margins for wrapping (`38475a0`)
- emit partial metadata on task cancellation (`9cb8731`)
- retry sub-agent when task result is empty (`e2c7fd3`)

### Other

-  (`c7206e3`)
## [1.2.22] - 2025-12-19

### Added

- track file access for cat/sed/mv commands (`e5d74b0`)
- use content hash instead of mtime for change detection (`7775e60`)
- show head and tail lines when truncating long output (`61a16a4`)
- add context lines and hunk separators to structured diff (`2596d19`)
- add character-level diff highlighting (`b5e8a6a`)
- add spacing after horizontal rules in markdown (`8ad6091`)
- update gpt-5.2-codex prompt (`52ee2e1`)

### Changed

- truncate large files instead of returning error (`1fb966c`)
- improve diff color contrast for better readability (`41c5ee7`)
- remove /diff command (`44c894a`)
- remove MemoryTool (`02589a0`)
- remove MultiEditTool (`bd17a58`)
- simplify GPT codex prompt (`896c457`)

### Fixed

- add type annotation to satisfy pyright strict mode (`56e011f`)
- exclude hint text from shimmer effect (`120bed0`)
- update debug log editor (`ae711c8`)
## [1.2.21] - 2025-12-18

### Added

- add /thinking gemini-3-flash-preview's minimal thinking level (`4f62bd3`)
- add --resume-by-id (`beb0323`)
- add syntax constraint for quoting node labels in Mermaid diagrams (`cae251a`)

### Other

- update agents.md & fix pyright (`616e6c3`)
## [1.2.20] - 2025-12-17

### Added

- tx-02 (`90872ed`)
- add new operation types for commands (`e00af52`)
- add tool metadata for concurrency policy (`cbac822`)
- async JSONL store v2 with background writer (`d3c6786`)
- add codec for conversation item serialization (`d5c4f6d`)
- add jj (jujutsu) to available CLI tools (`20459d2`)
- add /jj-workspace for parallel workflow (`de15c23`)
- add create tool for web-agent to create file (`0d51437`)

### Changed

- remove raw param (`a18ac97`)
- unify file tracking with FileStatus model (`aaa4eac`)
- update tests for async session and tool metadata (`aad3286`)
- handle new operation types (`d5891df`)
- return operations instead of actions (`b025d4d`)
- remove debouncer from streaming (`ac62bd5`)
- add jj workflow decision tree (`5533404`)
- update publish skill with correct jj workflow (`3dce39c`)

### Fixed

- render update_plan (`020d139`)
- make BashTool non-interactive and handle cancellation properly (`f6c4f9a`)
- remove 'v2' in session path (`375d17a`)
- improve Rich wrapping for mixed CJK/ASCII (`fb6dcf9`)
- adjust inline code font size (`ca2935a`)
- patch rich CJK wrapping (`44b83b8`)
- include URL in all error messages (`e801376`)
- handle non-UTF-8 encoded web pages (`a58c09b`)
- fix web fetch tool handling chinese url (`673a952`)

### Other

- minor fixes and cleanup (`bfb5e5f`)
- unify @ completer rg fallback with fd behavior: respect ignore rules (`04277e0`)
- Show (empty) indicator for empty working directory in env info (`ef83b7d`)
- move jj workflow to user claudemd (`c379500`)
- update AGENTS.md jj workflow (`ca2d078`)
## [1.2.19] - 2025-12-13

### Added

- show model name in terminal title (`2b1f971`)
- improve first token latency tracking and display (`9dd2678`)
- add read to gpt-5 for images (`c17429a`)
- support prefix matching for slash commands (`f68a02b`)
- persist and restore model config on session resume (`2f425a8`)
- update explore prompt (`a6089e4`)
- add update aliases and version flag (`fcfd5b0`)

### Changed

- add jj workflow decision tree and commit format (`50dbcfc`)
- add agent workflow rule to create jj change before coding (`9f028a4`)
- add status when exporting online (`9e0d42a`)
- optimize @-files completer with git index caching (`f17edb8`)
- move truncate_display to renderers/common and return rich.Text (`b3476e9`)
- update to jetbrains mono (`f3151fa`)

### Fixed

- preserve dotfile paths in @ completion (`a619cbc`)
- resolve pyright errors in test_command_registry.py (`a274b85`)
- don't save empty sessions on startup (`628dc7f`)
- prevent sending thinking config when type is disabled (`dedd090`)
- prevent ANTHROPIC_AUTH_TOKEN from conflicting with third-party API auth (`e127929`)
- clarify metadata labels as average values (`75078f4`)
- update version available hint text (`6daaa05`)

### Other

- remove finished dev docs (`05cd82f`)
- update dependencies (`0077d6d`)
- add .jj to .gitignore (`8f49725`)
- switch to jj, update AGENTS.md and SKILL.md (`e32db2d`)
- remove memory docs (`218b244`)
## [1.2.18] - 2025-12-12

### Added

- add GPT-5.2 thinking levels (`4bd003e`)
- support normalized model aliases (`3398b34`)
- add debug logging for file completion commands (`dd71edd`)
- trigger model selection when --model is specified (`390c461`)
- add placeholder property and improve /model filtering (`2f850af`)
- add /debug slash command (`1eb200e`)
- always save web content to local files and improve read error diagnostics (`dcb0d15`)
- run WebSearch and WebFetch tools concurrently (`06c543b`)
- add CodePanel for code blocks with top/bottom borders only (`18a0cea`)
- persist partial assistant output on interrupt (`37d3e5f`)

### Changed

- clarify --model interactive selection (`ca90772`)
- rename _normalize_thinking_content to public API (`159f143`)
- use file_tracker for memory loading (`610dd60`)
- tweak ui of status tool names and export (`5f41cbd`)
- update export html style (`8c467b8`)
- inline agent manager into executor (`e0edb91`)

### Fixed

- skip terminal color detection in exec mode to prevent TTY race (`bd8b065`)
- include ToolCallItem in messages_count and isolate test home dir (`ef3b108`)
- normalize thinking stream formatting for OpenRouter (`0cf216a`)
- minor UI adjustments and formatting improvements (`ca3b96e`)
- strip all ANSI/terminal control sequences from output (`4a0aca1`)

### Other

- align test tooling and import layers (`bbf22eb`)
- misc UI and prompt improvements (`dc8ed57`)
## [1.2.17] - 2025-12-10

### Added

- refactor WebFetchAgent to WebAgent with search capability (`6af0058`)
- add /export-online command to deploy session to surge.sh (`5c81f84`)
- display real-time context usage percentage in spinner (`5c387e1`)

### Changed

- enhance markdown hyperlink styling (`342a201`)
- improve session export template markdown styling (`138f0e4`)
- remove obsolete get_example_config tests (`1e59c63`)
- update example config with better defaults (`30795e6`)

### Fixed

- simplify operation label handling in render_write_tool_call (`f826084`)
- fix issue of /clear not working - dynamically retrieve active session ID to handle session changes (`60920ad`)
- improve sub-agent output_format and rendering (`03bd61b`)
- normalize JSON schema type values to lowercase for Gemini compatibility (`c2ad2c6`)

### Other

- update readme.md (`0122e99`)
## [1.2.16] - 2025-12-09

### Added

- add report_back tool for sub-agent structured output (`b35f96b`)
- shuffle spinner glyphs on module load for variety (`70f420e`)
- show WelcomeEvent after changing thinking level (`780f999`)
- update web_fetch agent desc (`4ca4d35`)
- add thinking prefix display in replay (`4be1e50`)
- preserve thinking content when switching models (`e50590d`)
- add recursive @ file loading with cycle detection (`006511b`)
- add handoff command (`0b0315d`)

### Changed

- move sub-agent prompt file mapping to SubAgentProfile (`bf7f5c0`)
- extract reusable helper functions across CLI and protocol modules (`ef0fbd9`)
- update markdown code style (`b72a967`)
- remove Rich private SPINNERS API dependency and increase markdown window (`97fb3fc`)
- use hex color codes for consistent rendering (`ade2dda`)
- tweak spinner and metadata (`6f0efad`)
- spilt sub_agent package, rename subagent to sub_agent (`d805925`)
- update metadata (`cdaeb29`)
- update thinking style (`ad2a10d`)

### Fixed

- improve spinner status width calculation and format cleanups (`41c9d53`)
- dynamically truncate spinner status based on terminal width (`ccd2474`)
- prevent spinner jitter during markdown streaming (`f4f1e38`)
- add padding spaces around reversed h1 headings (`ff4ef9a`)

### Other

- add handoff source (`8e4e94c`)
## [1.2.15] - 2025-12-08

### Added

- support custom markdown class in MarkdownStream (`5d5ae77`)
- update style of export and metadata (`220e49f`)
- update code block style (`605e889`)
- add dedicated markdown renderer for thinking content (`8f60728`)
- display bash timeout in seconds for readability (`0af058b`)

### Fixed

- thinking markdown code style (`3498693`)
- fix thinking command setting anthropic thinking budget 0 (`d1c1828`)
- add missing markdown.code.block style to thinking theme (`8e95cec`)

### Other

- tweak metadata layout and palette (`06a1b07`)
- tweak metadata layout and palette (`e06ed9d`)
## [1.2.14] - 2025-12-06

### Added

- include sub-agent session history in HTML exports (`f72f75e`)
- replay sub-agent history events recursively (`8122256`)
- improve debug logging with per-session files and auto-rotate (`92e3fc4`)

### Changed

- use lazy imports to improve CLI startup time (`dd0d420`)
- modularize CLI commands into separate modules (`a9e5df3`)
- update theme (`844b94b`)

### Fixed

- only cache successful config parses (`06ed727`)
- address pyrefly type checking issues (`13b4c65`)
## [1.2.13] - 2025-12-05

### Added

- add streaming reasoning/thinking output support (`2f23159`)
- support interleaved thinking claude header on openrouter (`0f52bcf`)

### Changed

- remove lazy loading from AgentProfile and LLMClients (`53d29ea`)

### Other

- ruff check (`50f1042`)
- ruff check --fix (`0314923`)
- format (`3adc227`)
## [1.2.12] - 2025-12-05

### Added

- add /thinking command to toggle reasoning mode (`cd06a2d`)
- remove cache ratio (`49943e5`)

### Changed

- improve column width handling in session selection (`8283730`)
- use manual command registration for custom display order (`e18b089`)
- rename context_token -> context_size (`7087dbc`)
- use llm sdk's param type hint; remove useless param option (`1f9f207`)
## [1.2.11] - 2025-12-04

### Added

- remove mouse support in prompt_toolkit input (`9c187ea`)
- add cache ratio display (`3ddbf5f`)
- support fullscreen mermaid (`07dd1f7`)
- add OSC 8 hyperlink detection for Mermaid tool (`0d56261`)
- add turn_count to TaskMetadata (`c1abd7f`)
- use claude code prompt (`4f90dcf`)
- simplify prompts and adjust tool configurations (`8b5b355`)
- disable claude code marketplace skills (`60e7d2b`)
- disable memory tool (`76c8280`)

### Changed

- centralize session ID generation in Session.create() (`4d166e9`)

### Fixed

- unify cache ratio calculation across export and UI (`97f61b8`)
- stabilize spinner position by adjusting padding logic (`e181770`)
- use context_delta for accurate cache ratio calculation (`4ca0d85`)
- issue of haiku explore missing tools  - enabled_for_model should only be applied for main_model_name (`4cfad31`)

### Other

- update agents.md (`53935e5`)
## [1.2.10] - 2025-12-03

### Changed

- optimize startup time with lazy loading (`2c2c343`)
- optimize LLM client loading and increase display lines (`c3e38b9`)
- lazy import (`a15a989`)
- rename context_window_size to context_token for clarity in usage tracking (`ec43ea9`)
- add test coverage for tool, session, and config modules (`5a34919`)
- improve exception handling specificity and extract shared file utils (`ac6e777`)

### Fixed

- correct context usage percentage calculation (`f61dfb0`)

### Other

- remove some pyright ignore (`9a95847`)
## [1.2.9] - 2025-12-02

### Added

- add italic variants for IBM Plex fonts (`12f9b8c`)
- add aggregated usage statistics with per-model breakdown (`369673e`)
- add experimental responses header to Codex API configuration (`b874fbe`)
- add release notes viewer (`2ad2e43`)

### Changed

- use discriminated union for ToolResultUIExtra (`e144a0d`)
- improve state management with encapsulated state classes (`b0aecb5`)
- extract SessionContext for shared session state (`13ac7ca`)
- convert derived state to computed fields (`0548428`)
- replace ModelUsageStats with TaskMetadata aggregation (`1f50839`)

### Fixed

- truncate spinner status text to 30 chars preserving words (`7c31d8c`)
- guard against redundant derived task metadata state (`6ec2213`)
- sort keys in JSON output for consistent formatting (`157506f`)
## [1.2.8] - 2025-12-01

### Changed

- extract TurnResult dataclass and simplify error handling (`aa568e7`)

### Fixed

- persist StreamErrorItem to history for replay (`3dfc33c`)
- catch API errors during stream creation for proper retry (`8c3bde8`)
- send conversation headers for better caching (`a5a95b2`)
- expand error handling to catch all API errors for retry (`8f0c48b`)
## [1.2.7] - 2025-12-01

### Added

- add currency support for cost display and calculation (`974bdd8`)
- adapt for deepseek api by merging multiple toolresult blocks into single user message (`ce08afe`)
- add Codex integration with OAuth authentication (`095bf96`)
- improve explore agent prompt and encourage parallel execution (`0171a46`)
- improve explore agent prompt and encourage parallel execution (`6f90a4e`)

### Changed

- improve spinner status update granularity (`a236c0d`)
- simplify status state management for turn transitions (`1a14a5f`)

### Fixed

- prevent truncation of Read tool outputs in SmartTruncationStrategy (`726d9ca`)
- support filenames with spaces in @-file references (`13ca4f1`)
- trim whitespace from pre-wrap content to avoid formatting artifacts (`aa40aa0`)

### Other

- format (`f04c929`)
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

[Unreleased]: https://github.com/inspirepan/klaude-code/compare/v1.2.23...HEAD
[1.2.23]: https://github.com/inspirepan/klaude-code/compare/v1.2.22...v1.2.23
[1.2.22]: https://github.com/inspirepan/klaude-code/compare/v1.2.21...v1.2.22
[1.2.21]: https://github.com/inspirepan/klaude-code/compare/v1.2.20...v1.2.21
[1.2.20]: https://github.com/inspirepan/klaude-code/compare/v1.2.19...v1.2.20
[1.2.19]: https://github.com/inspirepan/klaude-code/compare/v1.2.18...v1.2.19
[1.2.18]: https://github.com/inspirepan/klaude-code/compare/v1.2.17...v1.2.18
[1.2.17]: https://github.com/inspirepan/klaude-code/compare/v1.2.16...v1.2.17
[1.2.16]: https://github.com/inspirepan/klaude-code/compare/v1.2.15...v1.2.16
[1.2.15]: https://github.com/inspirepan/klaude-code/compare/v1.2.14...v1.2.15
[1.2.14]: https://github.com/inspirepan/klaude-code/compare/v1.2.13...v1.2.14
[1.2.13]: https://github.com/inspirepan/klaude-code/compare/v1.2.12...v1.2.13
[1.2.12]: https://github.com/inspirepan/klaude-code/compare/v1.2.11...v1.2.12
[1.2.11]: https://github.com/inspirepan/klaude-code/compare/v1.2.10...v1.2.11
[1.2.10]: https://github.com/inspirepan/klaude-code/compare/v1.2.9...v1.2.10
[1.2.9]: https://github.com/inspirepan/klaude-code/compare/v1.2.8...v1.2.9
[1.2.8]: https://github.com/inspirepan/klaude-code/compare/v1.2.7...v1.2.8
[1.2.7]: https://github.com/inspirepan/klaude-code/compare/v1.2.6...v1.2.7
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
