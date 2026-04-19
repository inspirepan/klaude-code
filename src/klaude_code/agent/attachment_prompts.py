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

def fmt_available_skills(skills_xml: str) -> str:
    return f"""# Skills

Skills are optional task-specific instructions stored as `SKILL.md` files.

How to use skills:
- Use the metadata in <available_skills> to decide whether a skill applies.
- When the task matches a skill's description, use the `Read` tool to load the `SKILL.md` at the given <location>.
- Treat the skill <base_dir> as the working directory when following the skill instructions.
- Resolve any relative paths in SKILL.md (such as `scripts/...`, `references/...`, `assets/...`) against that <base_dir>.

Important:
- Only use skills listed in <available_skills> below.
- Keep context small: do NOT load skill files unless needed.

The list below is metadata only. The full instructions live in the referenced file.

<available_skills>
{skills_xml}
</available_skills>"""

def fmt_available_skills_added(skills_xml: str) -> str:
    return f"""The available skill metadata changed. Apply the same skill-loading rules from the earlier skill listing.

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

# ---------------------------------------------------------------------------
# Paste files
# ---------------------------------------------------------------------------

def fmt_paste_file_hint(pasted_files: dict[str, str]) -> str:
    mapping = "\n".join(f"- <{tag}> saved to: {path}" for tag, path in pasted_files.items())
    return (
        "The user's message contains pasted content wrapped in XML tags. "
        "Each paste has been saved to a file for convenient editing:\n"
        f"{mapping}\n\n"
        "When you need to execute the pasted content in Bash or write it into a code file, "
        "use Bash commands (cp, mv, cat, etc.) to operate on the file directly instead of repeating it."
    )

# ---------------------------------------------------------------------------
# Todo nudge
# ---------------------------------------------------------------------------

def fmt_todo_nudge(todo_str: str) -> str:
    return (
        "The TodoWrite tool hasn't been used recently. If you're working on tasks that would benefit "
        "from tracking progress, consider using the TodoWrite tool to track progress. Also consider "
        "cleaning up the todo list if it has become stale and no longer matches what you are working on. "
        "Only use it if it's relevant to the current work. This is just a gentle reminder - ignore if "
        "not applicable. Make sure that you NEVER mention this reminder to the user"
        f"{todo_str}"
    )
