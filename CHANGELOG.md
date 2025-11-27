# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/inspirepan/klaude-code/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/inspirepan/klaude-code/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/inspirepan/klaude-code/compare/v1.0.6...v1.1.0
[1.0.6]: https://github.com/inspirepan/klaude-code/compare/v1.0.5...v1.0.6
[1.0.5]: https://github.com/inspirepan/klaude-code/compare/v1.0.4...v1.0.5
[1.0.4]: https://github.com/inspirepan/klaude-code/compare/v1.0.3...v1.0.4
[1.0.3]: https://github.com/inspirepan/klaude-code/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/inspirepan/klaude-code/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/inspirepan/klaude-code/compare/v1.0.0...v1.0.1
