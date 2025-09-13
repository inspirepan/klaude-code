from typing import Optional

from rich.console import RenderableType
from rich.text import Text

from codex_mini.ui.renderers.common import create_grid
from codex_mini.ui.theme import ThemeKey


def render_edit_diff(diff_text: str, show_file_name: bool = False) -> RenderableType:
    if diff_text == "":
        return Text("")

    lines = diff_text.split("\n")
    grid = create_grid()

    # Track line numbers based on hunk headers
    new_ln: Optional[int] = None

    for i, line in enumerate(lines):
        # Parse file name from diff headers
        if show_file_name and line.startswith("+++ "):
            # Extract file name from +++ header with proper handling of /dev/null
            raw = line[4:].strip()
            if raw == "/dev/null":
                file_name = raw
            elif raw.startswith(("a/", "b/")):
                file_name = raw[2:]
            else:
                file_name = raw

            file_text = Text(file_name, style="bold")

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
            file_line = Text()
            file_line.append_text(file_text)
            if stats_text.plain:
                file_line.append(" (")
                file_line.append_text(stats_text)
                file_line.append(")")

            grid.add_row("", "")
            grid.add_row(Text("   ±", style=ThemeKey.TOOL_MARK), file_line)
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
            grid.add_row(Text("   …", style=ThemeKey.TOOL_RESULT), "")
            continue

        # Skip file header lines entirely
        if line.startswith("--- ") or line.startswith("+++ "):
            continue

        # Only handle unified diff hunk lines; ignore other metadata like
        # "diff --git" or "index ..." which would otherwise skew counters.
        if not line or line[:1] not in {" ", "+", "-"}:
            continue

        # Hide completely blank diff lines (no content beyond the marker)
        if len(line) == 1:
            continue

        # Compute line number prefix and advance counters
        prefix = "    "
        kind = line[0]
        if kind == "-":
            pass
        elif kind == "+":
            if new_ln is not None:
                prefix = f"{new_ln:>4}"
                new_ln += 1
        else:  # context line ' '
            if new_ln is not None:
                prefix = f"{new_ln:>4}"
                new_ln += 1

        # Style only true diff content lines
        if line.startswith("-"):
            line_style = ThemeKey.DIFF_REMOVE
        elif line.startswith("+"):
            line_style = ThemeKey.DIFF_ADD
        else:
            line_style = ThemeKey.TOOL_RESULT
        text = Text(line)
        if line_style:
            text.stylize(line_style)
        grid.add_row(Text(prefix, ThemeKey.TOOL_RESULT), text)

    return grid
