# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.5.3] - 2026-01-07

### Added

- preserve partial content on stream error for retry prefill (`bb9c05df`)
- fix google gemini protocol support (`77aafaa5`)
- update model selector style with provider group (`5f4b2253`)
- add gpt-5.2 openai builtin config (`8633c893`)

### Changed

- update metadata style (`91110460`)
- centralize stream part helpers (`c6c92ae1`)
- refactor Anthropic & Chat Completion API client to accumulating-parts style && fix summary part spacing (`2d160706`)
- refactor responses API client to accumulating-parts style && fix summary part spacing (`d39d73fc`)
- unify picker styles and improve model display (`261f2c96`)

### Fixed

- correct quote width measurement (`54ecc6df`)
- update spinner status line style (`e8706c89`)
- fixed responses API degrade other model's thinking text logic & update builtin openai reasoning summary level (`721b8ab4`)
- show full error traceback (`98e266d6`)
- fix responses API output_text (`6763846e`)
- update cost command wrap logic (`08a427ad`)

### Other

- update --help ENV vars (`c19d1347`)
- fix lint (`b5d2f30c`)
## [2.5.2] - 2026-01-06

### Added

- add model disabled support and stream error handling (`50d5feb3`)
- add collapse step UI in export html (`2c697b15`)
- show skill in welcome event (`bc30d041`)
- add jq to available CLI tools in agent profile (`f2e490c3`)

### Fixed

- update config for opus (`54dd0844`)

### Other

- polish export and TUI rendering (`0c142cea`)
## [2.5.1] - 2026-01-06

### Changed

- centralize model_id in session state for model-specific feature flags (`1bc6daec`)

### Fixed

- fix thinking_tail not being reset on new turn causing stale reasoning headers (`1bc6daec`)

## [2.5.0] - 2026-01-06

### Added

- add flux builtin model (`6e814e10`)
- pop up input window height when triggering completion (`1b7fc2f6`)
- display sub-agent description in metadata (`308a1551`)
- update metadata style (`2a3b7669`)
- reduce bash tool prompt (`b43065fb`)
- reduce to-do tool instructions (`bba1f757`)
- extrace common prompt (`4c34a4a3`)

### Changed

- move file saving logic from offload to tool itself (`be6074d5`)
- introduce LLMStreamABC for partial message access on cancel (`17a3c0a8`)
- rename truncation module to offload (`e3a46044`)
- update markdown / export fonts (`849891d6`)
- remove sub-agent model in welcome (`a53d4a98`)
- update --banana implement (`76245715`)

### Fixed

- add blank line before metadata when interrupting (`6b5332e6`)
- collect sub-agent partial metadata on cancellation (`11720d7d`)
## [2.4.2] - 2026-01-05

### Added

- apply sub-agent color to task result description (`9de47cd4`)

### Fixed

- skip activity state for fast tools on non-streaming models (`a6a5a8b6`)
## [2.4.1] - 2026-01-05

### Changed

- update model picker style (`ae3c3976`)
- derive sub-agent types from profile tools instead of separate methods (`c19d4821`)
## [2.4.0] - 2026-01-04

### Added

- sort model selection and rename model_matcher and model_picker (`0d6d3a5c`)
- emit replacement blocks in unified-diff style (`11dc856f`)
- add seedream image gen model (`7d9ec9d2`)

### Changed

- add commandOutputEvent (`1d0160aa`)
- reduce nested model levels in config by flattening model_params. (`eaae7dda`)

### Fixed

- fixing fork command ui and behavior (`0f856c8b`)
- unify command event emit logic, do not persist command output (`bdf6b456`)
## [2.3.0] - 2026-01-04

### Added

- add /sub-agent-model command for runtime model configuration (`4a992d21`)
- support model@provider selectors (`719b2ba4`)
- display sub-agent models in welcome message (`fc678899`)
- add keyword-based model filtering and interactive selection for banana mode (`3685c5a3`)
- add availability requirement system for conditional sub-agent loading (`710a131d`)
- update nano banana config (`0db595e9`)

### Changed

- remove help and release-notes commands, simplify model switching (`9cf0c13e`)
- remove target_model_filter and enabled_for_model (`4ec31fcc`)

### Fixed

- truncate left for status line (`aaf711c1`)

### Other

- use ty (`81903aa8`)
- update commit skill (`14b4aa72`)
## [2.2.0] - 2026-01-04

### Added

- add --banana (`fe1d0641`)
- remove exec mode (`52c43636`)

### Changed

- unify command persistence flag (`5bd04d60`)
- update command style (`9f2b84bc`)
- extract and reuse format_model_params function (`8647a39d`)
- simplify command safety checks to only rm and trash (`55a9113b`)

### Other

- update README.md (`9c516995`)
- add commit skill (`7b760989`)
## [2.1.1] - 2026-01-04

### Added

- add /copy command to copy last assistant message (`7ea14649`)

### Changed

- remove Skill tool (`a2542ac9`)

### Fixed

- duplicate interrupted event (`78afa968`)
## [2.1.0] - 2026-01-03

### Added

- track sub-agent tool calls in spinner status (`971ac278`)

### Changed

- consolidate agent profile related code into agent_profile module (`f0cef29a`)
- extract AgentRuntime and ModelSwitcher from ExecutorContext (`1f2d49d5`)
- improve spinner status text clarity (`ad0fff84`)
- extract app layer for runtime coordination (`286ed756`)
- use command registry for slash highlighting (`38dfed08`)
- change trace to log.py (`333234fc`)
- move command to tui (`6fd0e167`)
- separate tui from ui (`7b66bbe2`)
- restructure events and rewrite REPL rendering pipeline (`7b74e244`)
- make tool execution context explicit (`052e3d6e`)
- update sub-agent result style (`48fca1cd`)

### Fixed

- change thinking mdstream to no live repaint && add check for spinner update (`82251feb`)
- show double Ctrl+C hint without breaking prompt input (`c5eaecfa`)

### Other

- replace dev-docs skill with create-plan skill (`34875646`)
- add Makefile (`ee1f6ac4`)
## [2.0.2] - 2026-01-03

### Added

- update sub-agent params and add background for bash command (`e7746641`)
- remove Move tool (`62ac4c5e`)

### Changed

- update dark background (`b85d922b`)
- update welcome style (`dfe9b89e`)
- update developer ui extra model (`b5b68cb9`)
- remove osc94 effect (`586d0c36`)
- add window around selector overlay and extract constant DIFF_DEFAULT_CONTEXT_LINES (`ccd0c5fe`)

### Fixed

- use synchronized output (2026) for markdown stream (`dc719829`)
## [2.0.1] - 2026-01-02

### Added

- move cursor visually within wrapped line (`aaeb111f`)
- truncate heredoc in bash and remove bash git diff render (`28d13100`)

### Changed

- remove unused UserInputOperation (`14c41ffc`)
- remove unused activeForm parameter from TodoWrite tool (`e01deb86`)
- soften light theme backgrounds (`fa244432`)

### Fixed

- clamp tool output display and update codex pricing (`139a85fa`)
## [2.0.0] - 2026-01-02

### Added

- add tree quote for tool result and tool call (`ce6e6881`)
- update image-gen prompt (`de7e1cf1`)
- show sub-agent thoughts header (`3cf6c3b5`)
- add image token tracking and cost calculation (`43e1b904`)
- add total cost in metadata (`59555da7`)
- support assistant images in multi-turn conversations (`ae86f23f`)
- add resume capability for continuing suspended sub-agent work (`13f334a4`)
- show Mermaid diagrams as images in terminal (`ee37bcc8`)
- add ImageGen sub-agent with OpenRouter Nano Banana Pro support (`20a31841`)
- add PDF file handling support (`9a5f6911`)
- update web search agent prompot (`2d14a65e`)
- improve clear command and session selector display (`f7358b76`)

### Changed

- reduce Hypothesis filtering in replace properties (`848396e5`)
- update truncate hint color (`f5a48117`)
- move ProjectPaths to const module for layer compliance (`2b2a794e`)
- extract format_saved_images helper (`3c38da7b`)
- replace ... with unicode ellipsis (…) for consistent typography (`4af9652d`)
- consolidate constants and extract common input utilities (`fb58de7d`)
- move agentId footer styling to render layer (`3f735931`)
- simplify stream state rendering logic & update /commit prompt (`9ddeb28b`)
- improve error message truncation strategies and extract const (`a5d4f703`)
- use direct imports from klaude_code.const (`d854950c`)
- rename AssistantTextDelta (`08b64bfc`)
- remove redundant startItem & usage emit (`98017ea5`)
- split message.py from model.py (`bb17ac3d`)
- use message + part instead of responses item protocol (`1f20cde3`)

### Fixed

- render Mermaid images via live-safe terminal output (`3566cecd`)
- render banana's thought only (`451866ba`)
- preserve session id when tool call is cancelled (`e92cbe33`)
- remove empty lines around markdown table (`b6bab7df`)
- prioritize basename match quality over depth in @ file completion (`c86699f7`)
- live markdown window max height reset (`5d63dcae`)
- reponses API thinking and tool call id (`ddb2c21f`)

### Other

- plan for message + part protocol (`0e14c396`)
## [1.9.0] - 2026-01-01

### Added

- support anthropic claude oauth login (`aa3cedf8`)
- add weekday to date display in cost summary table (`64cf51f9`)

### Changed

- update list-model style (`2453ad4e`)
- replace jj-describe with unified commit command (`103747dd`)
- remove Oracle sub-agent (`829504c7`)
## [1.8.0] - 2026-01-01

### Added

- add cost command for aggregated usage statistics (`d55e393f`)
- add alias support for terminal selector search (`ac52c7be`)
## [1.7.1] - 2025-12-31

### Added

- add gpt-5.2-medium gpt-5.2-low (`692f0670`)
- cache user messages in meta and restore welcome event (`2024a251`)
- add collapsible headings to sub-agent export results (`502d3a98`)
- allow configuring read limits via environment variables (`e93edeb3`)

### Changed

- simplify mermaid configuration (`7d5e3c15`)
- replace Geist Sans with Inter font (`aa30af80`)
- apply sans-serif font to tool-name elements (`d6802d9b`)
- improve custom model configuration documentation (`2d26be42`)
- move 'Klaude Code' to end of HTML title (`ea5548e1`)

### Fixed

- add cross-platform support for _open_file (`7465ea24`)
- add session_id to ErrorEvent for sub-agent color styling (`2a9befb7`)
- fork session auto copy new command (`865a03eb`)
- allow git push command (`21dc6e0a`)
## [1.7.0] - 2025-12-30

### Added

- support google gen ai protocol (`d0e40901`)
- support aws bedrock protocol (`ebbe5564`)

### Changed

- add new features and CLI commands documentation (`47335593`)

### Other

- fix pytest and ruff check (`e6c575d4`)
## [1.6.0] - 2025-12-30

### Added

- show multiple user messages in session selection (`7d3bfbc5`)
- add interactive fork point selection for /fork command (`3a16877f`)

### Changed

- update context style (`e036fdea`)
- update status, move timecounter to right (`4e4aa5ec`)
- add pbt tests (`7ac68fa7`)
- disable persistence for refresh terminal command (`8cf5b0e3`)
- add hypotheis test for md stream (`3bc7f27f`)

### Fixed

- change TPS calculation to use full request duration (`39defbdf`)
## [1.5.0] - 2025-12-29

### Added

- add ctrl-t thinking picker overlay in REPL prompt (`384d225f`)
- add ctrl-l model picker overlay in REPL prompt (`ef7541f9`)
- display sub-agent metadata individually and add tmux test signal (`b827c19f`)

### Changed

- extract shared thinking picker logic to config module (`cdf08fdb`)
- elevate command layer above ui layer (`9fe0f3b9`)
- apply bold style to question text (`3e27ab0e`)
- change grey_yellow color to green tones (`d3acff25`)

### Fixed

- add number before model list; update /help command (`f09b1053`)
## [1.4.3] - 2025-12-28

### Changed

- simplify completion menu styling with arrow indicator (`bb0613ed`)
## [1.4.2] - 2025-12-28

### Added

- align path completion display (`1e17ab9a`)

### Changed

- improve completion menu styling and sorting (`5b8257b4`)

### Fixed

- keep completion menu left-aligned instead of following cursor (`0badf2ee`)

### Other

- Merge pull request #1 from inspirepan/codex/update-completer-file-path-display (`1a9138b0`)
## [1.4.1] - 2025-12-28

### Changed

- improve model selector display layout (`07202e00`)

### Fixed

- pyright (`790ccf74`)
## [1.4.0] - 2025-12-28

### Added

- display task elapsed time in status line (`e91e9bee`)

### Changed

- group at_files by operation and mentioned_in (`d210c438`)
- replace questionary with custom prompt_toolkit selector (`557567d1`)
- improve session selector with relative time and search filter (`3c887b19`)

### Fixed

- submit immediately when exact completion candidate is typed (`6da43a31`)
- change move tool marker to ± (`c44bcfa7`)
## [1.3.0] - 2025-12-27

### Added

- show replace all param for Edit tool UX (`8e6a551a`)
- add MoveTool for moving code between files (`61a0a8ba`)
- align completion menu UX (`6b890e18`)

### Changed

- add dedicated theme key for mermaid result display (`18128d61`)
- clarify default model save confirmation text (`9c82e382`)
## [1.2.30] - 2025-12-27

### Added

- highlight subcommands in bash syntax highlighting (`b40e7b2a`)
- add confirmation to save model as default (`560e9cd0`)
- add /resume command for session resumption (`6b53d016`)
- use CodePanel for long bash commands (`2d9f78fd`)
- add syntax highlighting for bash tool calls (`33e6a043`)
- add gpt-5-mini (`5942fb44`)

### Changed

- adjust bash syntax highlighting colors for better contrast (`f4de1620`)
- update thinking mark (`ea52a171`)

### Fixed

- retry when agent returns empty result (`d8d609ad`)
- preserve leading whitespace and expand tabs for proper tool result alignment (`5e2049de`)
## [1.2.29] - 2025-12-25

### Added

- create local HTML viewer for Mermaid.live links (`1b3480dd`)
- add example config file and avoid auto-creating user config (`56b6ddd9`)

### Changed

- refresh message and tool markers (`66f6e23e`)
- improve viewer and store code directly (`acd3f7a2`)

### Fixed

- duplicate turn start item when replay history (`9422613b`)
## [1.2.28] - 2025-12-25

### Added

- add klaude-code as alternative command entry point (`21d1d5bd`)
- add color palette guide for Mermaid diagrams (`13b9b25d`)
- support rendering markdown documents in HTML export (`8489c56a`)
- add /fork-session (`acbe85a7`)

### Changed

- separate bold and bold-italic status text styles (`c8a98523`)
- split render_error into separate functions for events and tools (`1ca5369b`)
- show bottom toolbar only for updates (`c6032b87`)

### Fixed

- prioritize shallow @-path completions (`02474453`)
- skip unchanged @ file reminders (`ff619fd5`)
- avoid truncation marker for small overflows (`1ccac87d`)
- correctly track which memory file contains @ references (`8387620b`)
- hide duplicate path in Write tool call for markdown files (`3f25960a`)
- detach stdin from subprocess to prevent terminal state interference (`ad6a49fa`)
- show status spinner during surge login check (`fa330bef`)
- normalize Gemini-3 tool names in accumulator (`24234298`)

### Other

- untrack .vscode/settings.json (`75be5ddb`)
## [1.2.27] - 2025-12-23

### Added

- persist model selection as default (`edadc21c`)
- show thinking config in model selector and reduce default budget (`c2914782`)
- add builtin provider configs with smart merging (`05065080`)
- make main_model configuration optional (`59542281`)
- support ${ENV_VAR} syntax for API key configuration (`b03b074f`)

### Changed

- update bash glyph and spinner status state (`7350368f`)
- nest model_list under each provider (`fcffe898`)
- narrow broad exception catches (`9cd234dc`)

### Other

- remove docs (`d581cf80`)
## [1.2.26] - 2025-12-22

### Added

- enhance composing status with creative verbs and buffer length (`54bced12`)
- add custom table element with MARKDOWN box style (`2a5e8d27`)
- render markdown preview when adding .md files (`9e082581`)

### Changed

- update h2 heading style (`9b4fa47b`)
- simplify h2 heading rendering by removing trailing rule (`ea462b18`)
- remove red from sub-agent color palette (`4f69f1d9`)
- conditionally insert description heading based on output type (`5421b821`)

### Fixed

- gate live markdown streaming behind feature flag (`72ee1a69`)
## [1.2.25] - 2025-12-22

### Added

- auto-trigger thinking selection after model switch (`0179e7b9`)

### Changed

- unify bottom live display for spinner and markdown stream (`637271f5`)
- update status glyph (`e1f344d3`)
- rewrite MarkdownStream with block-level streaming using markdown-it-py (`35bd708f`)
- sync shimmer and breathing animation frequency (`fac8e9b8`)
- use blinking beam cursor in REPL input (`b5a89ab2`)

### Fixed

- keep live height monotonic across block transitions (`ac513ba6`)
- normalize stable/live boundary whitespace in markdown streaming (`fbf753e0`)
- improve code panel border width calculation and spinner stability (`b7ccb2f4`)
## [1.2.24] - 2025-12-21

### Added

- add color-matched backgrounds for sub-agent result panels (`c6625c53`)
- add description header for sub-agent result (`e7da395e`)
- show reasoning headers in status line (`ae362a6d`)
- render markdown files in panel when using Write tool (`2fba67d8`)
- add describe command (`448f18e4`)

### Changed

- update header rule character (`d0543d89`)
- unify thinking and assistant message rendering with left marks (`be0f253c`)
- change sub-agent result truncation from top to middle (`de7350c4`)
- consolidate STATUS_DEFAULT_TEXT and convert const package to module (`56aa1a6c`)
- unify stream processing for OpenAI-compatible and OpenRouter clients (`1b28790b`)
- add background colors to result panels (`0e1cb7fa`)
- bold user input (`f76cfb75`)
- fix status truncation to support cjk via rich cell len (`966c43a9`)
- update box style (`76bbbbb2`)
- update completion selected color (`86f3b5a3`)

### Fixed

- add traceback for error (`e9aec3d2`)
- detect binary files before reading as text (`3e8eed24`)
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

[Unreleased]: https://github.com/inspirepan/klaude-code/compare/v2.5.3...HEAD
[2.5.3]: https://github.com/inspirepan/klaude-code/compare/v2.5.2...v2.5.3
[2.5.2]: https://github.com/inspirepan/klaude-code/compare/v2.5.1...v2.5.2
[2.5.0]: https://github.com/inspirepan/klaude-code/compare/v2.4.2...v2.5.0
[2.4.2]: https://github.com/inspirepan/klaude-code/compare/v2.4.1...v2.4.2
[2.4.1]: https://github.com/inspirepan/klaude-code/compare/v2.4.0...v2.4.1
[2.4.0]: https://github.com/inspirepan/klaude-code/compare/v2.3.0...v2.4.0
[2.3.0]: https://github.com/inspirepan/klaude-code/compare/v2.2.0...v2.3.0
[2.2.0]: https://github.com/inspirepan/klaude-code/compare/v2.1.1...v2.2.0
[2.1.1]: https://github.com/inspirepan/klaude-code/compare/v2.1.0...v2.1.1
[2.1.0]: https://github.com/inspirepan/klaude-code/compare/v2.0.2...v2.1.0
[2.0.2]: https://github.com/inspirepan/klaude-code/compare/v2.0.1...v2.0.2
[2.0.1]: https://github.com/inspirepan/klaude-code/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/inspirepan/klaude-code/compare/v1.9.0...v2.0.0
[1.9.0]: https://github.com/inspirepan/klaude-code/compare/v1.8.0...v1.9.0
[1.8.0]: https://github.com/inspirepan/klaude-code/compare/v1.7.1...v1.8.0
[1.7.1]: https://github.com/inspirepan/klaude-code/compare/v1.7.0...v1.7.1
[1.7.0]: https://github.com/inspirepan/klaude-code/compare/v1.6.0...v1.7.0
[1.6.0]: https://github.com/inspirepan/klaude-code/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/inspirepan/klaude-code/compare/v1.4.3...v1.5.0
[1.4.3]: https://github.com/inspirepan/klaude-code/compare/v1.4.2...v1.4.3
[1.4.2]: https://github.com/inspirepan/klaude-code/compare/v1.4.1...v1.4.2
[1.4.1]: https://github.com/inspirepan/klaude-code/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/inspirepan/klaude-code/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/inspirepan/klaude-code/compare/v1.2.30...v1.3.0
[1.2.30]: https://github.com/inspirepan/klaude-code/compare/v1.2.29...v1.2.30
[1.2.29]: https://github.com/inspirepan/klaude-code/compare/v1.2.28...v1.2.29
[1.2.28]: https://github.com/inspirepan/klaude-code/compare/v1.2.27...v1.2.28
[1.2.27]: https://github.com/inspirepan/klaude-code/compare/v1.2.26...v1.2.27
[1.2.26]: https://github.com/inspirepan/klaude-code/compare/v1.2.25...v1.2.26
[1.2.25]: https://github.com/inspirepan/klaude-code/compare/v1.2.24...v1.2.25
[1.2.24]: https://github.com/inspirepan/klaude-code/compare/v1.2.23...v1.2.24
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
