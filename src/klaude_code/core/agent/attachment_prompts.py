"""Centralized message templates for developer-message attachments sent to the LLM.

Every piece of text injected into the conversation as a DeveloperMessage lives
here so the full set of LLM-facing instructions is easy to review in one place.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# @file reader
# ---------------------------------------------------------------------------


def fmt_file_already_in_context(path: str, read_tool_name: str) -> str:
    return f"Note: {path} is already in context and unchanged. Use the {read_tool_name} tool if you need to re-read it."


def fmt_tool_result(tool_name: str, tool_args: str, output: str) -> str:
    return (
        f"Called the {tool_name} tool with the following input: {tool_args}\n"
        f"Result of calling the {tool_name} tool:\n"
        f"{output}\n"
    )


# ---------------------------------------------------------------------------
# External file changes
# ---------------------------------------------------------------------------


def fmt_file_changed_externally(file_path: str, file_content: str) -> str:
    return (
        f"Note: {file_path} was modified, either by the user or by a linter. "
        "Don't tell the user this, since they are already aware. "
        "This change was intentional, so make sure to take it into account "
        "as you proceed (ie. don't revert it unless the user asks you to). "
        f"Here are the relevant changes:\n\n{file_content}"
    )


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------


def fmt_skill_block(
    skill_name: str,
    skill_path: Path,
    base_dir: Path,
    skill_content: str,
    *,
    explicit: bool,
) -> str:
    if explicit:
        preface = f'The user activated the "{skill_name}" skill, prioritize this skill'
    else:
        preface = (
            f'The "{skill_name}" skill was discovered near files already accessed in this session. '
            "Apply it when relevant to the current work."
        )

    return f"""{preface}
<skill>
<name>{skill_name}</name>
<location>{skill_path}</location>
<base_dir>{base_dir}</base_dir>

{skill_content}
</skill>"""


def fmt_dynamic_available_skills(skills_xml: str) -> str:
    return f"""The following skills are available from directories you have accessed.

<available_skills>
{skills_xml}
</available_skills>"""


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


def fmt_memory_truncated(budget_bytes: int) -> str:
    return f"\n\n> Memory truncated due to session budget ({budget_bytes} bytes total)."


def fmt_auto_memory_hint(auto_memory_path: Path) -> str:
    return f"\n\nNo auto memory file yet for this project. Create {auto_memory_path} when you need to persist memories."


# ---------------------------------------------------------------------------
# Todo nudge
# ---------------------------------------------------------------------------


def fmt_todo_items(todo_items_str: str) -> str:
    return f"\n\nHere are the existing contents of your todo list:\n\n[{todo_items_str}]"


def fmt_post_todo_complete() -> str:
    return (
        "All your tasks are now complete. Before reporting back to the user, consider:\n"
        "- After completing complex or large-scale changes (touching 3+ files with non-trivial logic), "
        'launch an `Agent` with `type="review"` to review your work before reporting back to the user. '
        "Do NOT launch review for small, straightforward edits like config tweaks, single-file fixes, "
        "renames, or simple bug fixes.\n"
        "- After sessions with significant learnings (new commands, gotchas, architecture insights), "
        'launch an `Agent` with `type="memory"` to persist them into AGENTS.md files.'
    )


def fmt_review_followup() -> str:
    return (
        "For follow-up reviews (after fixing issues from a prior review), include the previous findings "
        "in the prompt and provide a diff command scoped to only the fix commits, so the reviewer can "
        "verify fixes incrementally instead of re-reviewing the entire changeset."
    )


def fmt_todo_nudge(todo_str: str) -> str:
    return (
        "The TodoWrite tool hasn't been used recently. If you're working on tasks that would benefit "
        "from tracking progress, consider using the TodoWrite tool to track progress. Also consider "
        "cleaning up the todo list if it has become stale and no longer matches what you are working on. "
        "Only use it if it's relevant to the current work. This is just a gentle reminder - ignore if "
        "not applicable. Make sure that you NEVER mention this reminder to the user"
        f"{todo_str}"
    )
