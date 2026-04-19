"""Attachment reminder templates injected as <system-reminder> content.

These are the text templates used by agent/attachments/ to build
DeveloperMessage content.  Keep them dependency-free.
"""

# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

MEMORY_HEADER = (
    "Loaded memory files. Follow these instructions. Do not mention them to the user unless explicitly asked."
)

MEMORY_TRUNCATED_TEMPLATE = "\n\n> Memory truncated due to session budget ({budget_bytes} bytes total)."

MEMORY_FILE_TRUNCATED_TEMPLATE = (
    "\n\n> This memory file was truncated ({max_bytes} byte limit). "
    "Use the Read tool to view the complete file at: {path}"
)

AUTO_MEMORY_HINT_TEMPLATE = (
    "\n\nNo auto memory file yet for this project. Create {auto_memory_path} when you need to persist memories."
)

USER_MEMORY_INSTRUCTION = "user's private global instructions for all projects"
PROJECT_MEMORY_INSTRUCTION = "project instructions, checked into the codebase"
DISCOVERED_MEMORY_INSTRUCTION = "project instructions, discovered near last accessed path"
AUTO_MEMORY_INSTRUCTION = "auto memory, persisted across sessions"

# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------

SKILL_EXPLICIT_PREFACE_TEMPLATE = 'The user activated the "{skill_name}" skill, prioritize this skill'

SKILL_DISCOVERED_PREFACE_TEMPLATE = (
    'The "{skill_name}" skill was discovered near files already accessed in this session. '
    "Apply it when relevant to the current work."
)

SKILL_BLOCK_TEMPLATE = """{preface}
<skill>
<name>{skill_name}</name>
<location>{skill_path}</location>
<base_dir>{base_dir}</base_dir>

{skill_content}
</skill>"""

DYNAMIC_AVAILABLE_SKILLS_TEMPLATE = """The following skills are available from directories you have accessed.

<available_skills>
{skills_xml}
</available_skills>"""

AVAILABLE_SKILLS_TEMPLATE = """# Skills

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

AVAILABLE_SKILLS_ADDED_TEMPLATE = """The available skill metadata changed. Apply the same skill-loading rules from the earlier skill listing.

<available_skills>
{skills_xml}
</available_skills>"""

# ---------------------------------------------------------------------------
# Files (@-file references)
# ---------------------------------------------------------------------------

FILE_ALREADY_IN_CONTEXT_TEMPLATE = (
    "Note: {path} is already in context and unchanged. Use the {read_tool_name} tool if you need to re-read it."
)

TOOL_RESULT_TEMPLATE = (
    "Called the {tool_name} tool with the following input: {tool_args}\n"
    "Result of calling the {tool_name} tool:\n"
    "{output}\n"
)

FILE_CHANGED_EXTERNALLY_TEMPLATE = (
    "Note: {file_path} was modified, either by the user or by a linter. "
    "Don't tell the user this, since they are already aware. "
    "This change was intentional, so make sure to take it into account "
    "as you proceed (ie. don't revert it unless the user asks you to). "
    "Here are the relevant changes:\n\n{file_content}"
)

PASTE_FILE_HINT_TEMPLATE = (
    "The user's message contains pasted content wrapped in XML tags. "
    "Each paste has been saved to a file for convenient editing:\n"
    "{mapping}\n\n"
    "When you need to execute the pasted content in Bash or write it into a code file, "
    "use Bash commands (cp, mv, cat, etc.) to operate on the file directly instead of repeating it."
)

# ---------------------------------------------------------------------------
# Todo
# ---------------------------------------------------------------------------

TODO_ITEMS_TEMPLATE = "\n\nHere are the existing contents of your todo list:\n\n[{todo_items_str}]"

TODO_NUDGE_TEMPLATE = (
    "The TodoWrite tool hasn't been used recently. If you're working on tasks that would benefit "
    "from tracking progress, consider using the TodoWrite tool to track progress. Also consider "
    "cleaning up the todo list if it has become stale and no longer matches what you are working on. "
    "Only use it if it's relevant to the current work. This is just a gentle reminder - ignore if "
    "not applicable. Make sure that you NEVER mention this reminder to the user"
    "{todo_str}"
)
