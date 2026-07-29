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
    "\n\n> This memory file was truncated to the first {max_lines} lines "
    "(file has {total_lines} lines total). "
    "Use the Read tool to view the complete file at: {path}"
)

MEMORY_FILE_BYTE_TRUNCATED_TEMPLATE = (
    "\n\n> This memory file was truncated at {max_bytes} bytes while loading it "
    "(file has {total_lines} lines total). The last visible line may be incomplete. "
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

SKILL_CONTENT_TRUNCATED_TEMPLATE = (
    "\n\n> SKILL.md inlined up to the first {max_lines} lines "
    "(file has {total_lines} lines total). "
    "Use the Read tool to view the complete file at: {path}"
)

SKILL_ALREADY_IN_CONTEXT_TEMPLATE = (
    'The user activated the "{skill_name}" skill. Its SKILL.md at {path} is already in context and unchanged. '
    "If needed, use the {read_tool_name} tool to re-read it."
)

DYNAMIC_AVAILABLE_SKILLS_TEMPLATE = """The following skills are available from directories you have accessed.

<available_skills>
{skills_xml}
</available_skills>"""

AVAILABLE_SKILLS_TEMPLATE = """# Skills

Skills are optional task-specific instructions stored as `SKILL.md` files. Each entry below is metadata only -- the tag body is the skill's description and `path` points at the full instructions.

How to use skills:
- Use the descriptions to decide whether a skill applies, and only use skills listed here.
- When the task matches one, `Read` its `path` to load the instructions.
- Treat the directory containing that SKILL.md as the working directory, and resolve relative paths inside it (`scripts/...`, `references/...`, `assets/...`) against that directory. A `base_dir` attribute, when present, overrides it.
- Keep context small: do NOT load skill files unless needed.

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

FILE_CHANGED_DIFF_TRUNCATED_TEMPLATE = (
    "\n\n... ({hidden_lines} more diff lines omitted; total {total_lines} lines of diff. "
    "Use the Read tool with offset/limit to inspect the current file at: {file_path})"
)

FILE_CHANGED_DIFF_SKIPPED_TEMPLATE = (
    "[diff skipped: combined old+new content is {total_bytes} bytes, exceeding the "
    "{limit_bytes}-byte limit. Use the Read tool with offset/limit to inspect the current file at: {file_path}]"
)

PASTE_REFERENCE_TEMPLATE = (
    "<system-reminder>The user pasted a large text block. It was saved to {path}. "
    "Use the Read tool to inspect it.</system-reminder>"
)
