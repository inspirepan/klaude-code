from rich import box
from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.panel import Panel
from rich.text import Text

from klaude_code import const
from klaude_code.ui.renderers.common import create_grid
from klaude_code.ui.rich.theme import ThemeKey


def _make_diff_prefix(line: str, new_ln: int | None, width: int) -> tuple[str, int | None]:
    kind = line[0]

    number = " " * width
    if kind in {"+", " "} and new_ln is not None:
        number = f"{new_ln:>{width}}"
        new_ln += 1

    if kind == "-":
        marker = "-"
    elif kind == "+":
        marker = "+"
    else:
        marker = " "

    prefix = f"{number} {marker}"
    return prefix, new_ln


def render_diff(diff_text: str, show_file_name: bool = False) -> RenderableType:
    if diff_text == "":
        return Text("")

    lines = diff_text.split("\n")
    grid = create_grid()
    grid.padding = (0, 0)

    # Track line numbers based on hunk headers
    new_ln: int | None = None
    # Track if we're in untracked files section
    in_untracked_section = False
    # Track whether we've already rendered a file header
    has_rendered_file_header = False
    # Track whether we have rendered actual diff content for the current file
    has_rendered_diff_content = False
    # Track the "from" file name from --- line (used for deleted files)
    from_file_name: str | None = None

    for i, line in enumerate(lines):
        # Check for untracked files section header
        if line == "git ls-files --others --exclude-standard":
            in_untracked_section = True
            grid.add_row("", "")
            grid.add_row("", Text("Untracked files:", style=ThemeKey.TOOL_MARK))
            grid.add_row("", "")
            continue

        # Handle untracked files
        if in_untracked_section:
            # If we hit a new section or empty line, we're done with untracked files
            if line.startswith("diff --git") or line.strip() == "":
                in_untracked_section = False
            elif line.strip():  # Non-empty line in untracked section
                file_text = Text(line.strip(), style=ThemeKey.TOOL_PARAM_BOLD)
                grid.add_row(
                    Text(f"{'+':>{const.DIFF_PREFIX_WIDTH}}", style=ThemeKey.TOOL_PARAM_BOLD),
                    file_text,
                )
                continue

        # Capture "from" file name from --- line (needed for deleted files)
        if line.startswith("--- "):
            raw = line[4:].strip()
            if raw != "/dev/null":
                from_file_name = raw[2:] if raw.startswith(("a/", "b/")) else raw
            continue

        # Parse file name from diff headers
        if show_file_name and line.startswith("+++ "):
            # Extract file name from +++ header with proper handling of /dev/null
            raw = line[4:].strip()
            if raw == "/dev/null":
                # File was deleted, use the "from" file name
                file_name = from_file_name or raw
            elif raw.startswith(("a/", "b/")):
                file_name = raw[2:]
            else:
                file_name = raw

            file_text = Text(file_name, style=ThemeKey.DIFF_FILE_NAME)

            # Count actual +/- lines for this file from i+1 onwards
            file_additions = 0
            file_deletions = 0
            for remaining_line in lines[i + 1 :]:
                if remaining_line.startswith("diff --git"):
                    break
                elif remaining_line.startswith("+") and not remaining_line.startswith("+++"):
                    file_additions += 1
                elif remaining_line.startswith("-") and not remaining_line.startswith("---"):
                    file_deletions += 1

            # Create stats text
            stats_text = Text()
            if file_additions > 0:
                stats_text.append(f"+{file_additions}", style=ThemeKey.DIFF_STATS_ADD)
            if file_deletions > 0:
                if file_additions > 0:
                    stats_text.append(" ")
                stats_text.append(f"-{file_deletions}", style=ThemeKey.DIFF_STATS_REMOVE)

            # Combine file name and stats
            file_line = Text(style=ThemeKey.DIFF_FILE_NAME)
            file_line.append_text(file_text)
            if stats_text.plain:
                file_line.append(" (")
                file_line.append_text(stats_text)
                file_line.append(")")

            if has_rendered_file_header:
                grid.add_row("", "")

            if file_additions > 0 and file_deletions == 0:
                file_mark = "+"
            elif file_deletions > 0 and file_additions == 0:
                file_mark = "-"
            else:
                file_mark = "±"

            grid.add_row(
                Text(f"{file_mark:>{const.DIFF_PREFIX_WIDTH}}  ", style=ThemeKey.DIFF_FILE_NAME),
                file_line,
            )
            has_rendered_file_header = True
            has_rendered_diff_content = False
            continue

        if line.startswith("diff --git"):
            has_rendered_diff_content = False
            continue

        # Parse hunk headers to reset counters: @@ -l,s +l,s @@
        if line.startswith("@@"):
            try:
                parts = line.split()
                plus = parts[2]  # like '+12,4'
                new_start = int(plus[1:].split(",")[0])
                new_ln = new_start
            except Exception:
                new_ln = None
            if has_rendered_diff_content:
                grid.add_row(Text(f"{'⋮':>{const.DIFF_PREFIX_WIDTH}}", style=ThemeKey.TOOL_RESULT), "")
            continue

        # Skip +++ lines (already handled above)
        if line.startswith("+++ "):
            continue

        # Only handle unified diff hunk lines; ignore other metadata like
        # "diff --git" or "index ..." which would otherwise skew counters.
        if not line or line[:1] not in {" ", "+", "-"}:
            continue

        # Compute line number prefix and style diff content
        prefix, new_ln = _make_diff_prefix(line, new_ln, const.DIFF_PREFIX_WIDTH)

        if line.startswith("-"):
            text = Text(line[1:])
            text.stylize(ThemeKey.DIFF_REMOVE)
        elif line.startswith("+"):
            text = Text(line[1:])
            text.stylize(ThemeKey.DIFF_ADD)
        else:
            text = Text(line, style=ThemeKey.TOOL_RESULT)
        grid.add_row(Text(prefix, ThemeKey.TOOL_RESULT), text)
        has_rendered_diff_content = True

    return grid


def render_diff_panel(
    diff_text: str,
    *,
    show_file_name: bool = True,
    heading: str = "Git Diff",
    indent: int = 2,
) -> RenderableType:
    lines = diff_text.splitlines()
    truncated_notice: Text | None = None
    if len(lines) > const.MAX_DIFF_LINES:
        truncated_lines = len(lines) - const.MAX_DIFF_LINES
        diff_text = "\n".join(lines[: const.MAX_DIFF_LINES])
        truncated_notice = Text(f"… truncated {truncated_lines} lines", style=ThemeKey.TOOL_MARK)

    diff_body = render_diff(diff_text, show_file_name=show_file_name)
    renderables: list[RenderableType] = [
        Text(f" {heading} ", style="bold reverse"),
        diff_body,
    ]
    if truncated_notice is not None:
        renderables.extend([Text(""), truncated_notice])

    panel = Panel.fit(
        Group(*renderables),
        border_style=ThemeKey.LINES,
        title_align="center",
        box=box.ROUNDED,
    )
    if indent <= 0:
        return panel
    return Padding.indent(panel, level=indent)
