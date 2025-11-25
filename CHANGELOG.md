# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/user/klaude-code/compare/v1.0.3...HEAD
[1.0.3]: https://github.com/user/klaude-code/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/user/klaude-code/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/user/klaude-code/compare/v1.0.0...v1.0.1
