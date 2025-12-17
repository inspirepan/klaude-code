from pathlib import Path

from klaude_code.command.command_abc import Agent, CommandABC, CommandResult
from klaude_code.protocol import commands, events, model


def _read_changelog() -> str:
    """Read CHANGELOG.md from project root."""
    changelog_path = Path(__file__).parent.parent.parent.parent / "CHANGELOG.md"
    if not changelog_path.exists():
        return "CHANGELOG.md not found"
    return changelog_path.read_text(encoding="utf-8")


def _extract_releases(changelog: str, count: int = 1) -> str:
    """Extract release sections from changelog in reverse order (oldest first).

    Args:
        changelog: The full changelog content.
        count: Number of releases to extract (default 1).

    Returns:
        The content of the specified number of releases, with newest at bottom.
    """
    lines = changelog.split("\n")
    releases: list[list[str]] = []
    current_release: list[str] = []
    version_count = 0

    for line in lines:
        # Skip [Unreleased] section header
        if line.startswith("## [Unreleased]"):
            continue

        # Check for version header (e.g., ## [1.2.8] - 2025-12-01)
        if line.startswith("## [") and "]" in line:
            if current_release:
                releases.append(current_release)
            version_count += 1
            if version_count > count:
                break
            current_release = [line]
            continue

        if version_count > 0:
            current_release.append(line)

    # Append the last release if exists
    if current_release and version_count <= count:
        releases.append(current_release)

    if not releases:
        return "No release notes found"

    # Reverse to show oldest first, newest last
    releases.reverse()
    return "\n".join("\n".join(release) for release in releases).strip()


class ReleaseNotesCommand(CommandABC):
    """Display the latest release notes from CHANGELOG.md."""

    @property
    def name(self) -> commands.CommandName:
        return commands.CommandName.RELEASE_NOTES

    @property
    def summary(self) -> str:
        return "Show the latest release notes"

    async def run(self, agent: Agent, user_input: model.UserInputPayload) -> CommandResult:
        del user_input  # unused
        changelog = _read_changelog()
        content = _extract_releases(changelog, count=10)

        event = events.DeveloperMessageEvent(
            session_id=agent.session.id,
            item=model.DeveloperMessageItem(
                content=content,
                command_output=model.CommandOutput(command_name=self.name),
            ),
        )

        return CommandResult(events=[event])
