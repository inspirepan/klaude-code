from pathlib import Path

CONTEXT_REMINDER_HEAD = """<system-reminder>As you answer the user's questions, you can use the following context:
"""


CLAUDE_MD_REMINDER = """# claudeMd
Codebase and user instructions are shown below. Be sure to adhere to these instructions. IMPORTANT: These instructions OVERRIDE any default behavior and you MUST follow them exactly as written.
{claude_md}
"""


CONTEXT_REMINDER_TAIL = """# important-instruction-reminders
Do what has been asked; nothing more, nothing less.
NEVER create files unless they're absolutely necessary for achieving your goal.
ALWAYS prefer editing an existing file to creating a new one.
NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.

IMPORTANT: this context may or may not be relevant to your tasks. You should not respond to this context or otherwise consider it in your response unless it is highly relevant to your task. Most of the time, it is not relevant.
</system-reminder>
"""


def get_context_reminder(workdir: str) -> str:
    user_claudemd_path = Path.home() / '.claude' / 'CLAUDE.md'
    project_claudemd_path = Path(workdir) / 'CLAUDE.md'
    claude_md_instructions = ''
    user_claudemd_remind = ''
    project_claudemd_remind = ''
    if user_claudemd_path.exists():
        user_claudemd_content = user_claudemd_path.read_text(encoding='utf-8')
        user_claudemd_remind = f"""Contents of {user_claudemd_path} (user's private global instructions for all projects):

{user_claudemd_content}
"""
    if project_claudemd_path.exists():
        project_claudemd_content = project_claudemd_path.read_text(encoding='utf-8')
        project_claudemd_remind = f"""Contents of {project_claudemd_path} (project instructions, checked into the codebase):

{project_claudemd_content}
"""
    if user_claudemd_remind or project_claudemd_remind:
        claude_md_instructions = CLAUDE_MD_REMINDER.format(claude_md=user_claudemd_remind + '\n\n' + project_claudemd_remind)
    return CONTEXT_REMINDER_HEAD + '\n\n' + claude_md_instructions + '\n\n' + CONTEXT_REMINDER_TAIL


EMPTY_TODO_REMINDER = """<system-reminder>This is a reminder that your todo list is currently empty. DO NOT mention this to the user explicitly because they are already aware. If you are working on tasks that would benefit from a todo list please use the TodoWrite tool to create one. If not, please feel free to ignore. Again do not mention this message to the user.</system-reminder>"""


TODO_REMINDER = """<system-reminder>Your todo list has changed. DO NOT mention this explicitly to the user. Here are the latest contents of your todo list:

{todo_list_json}

You DO NOT need to use the TodoRead tool again, since this is the most up to date list for now. Continue on with the tasks at hand if applicable.</system-reminder>"""


LANGUAGE_REMINDER = """<system-reminder>Respond in the same language as the user input entirely. DO NOT mention this explicitly to the user.</system-reminder>"""


FILE_MODIFIED_EXTERNAL_REMINDER = """<system-reminder>
Note: {file_path} was modified, either by the user or by a linter. Don't tell the user this, since they are already aware. This change was intentional, so make sure to take it into account as you proceed (ie. don't revert it unless the user asks you to). So that you don't need to re-read the file, here's the result of running `cat -n` on a snippet of the edited file:
{file_content}
</system-reminder>
"""

FILE_DELETED_EXTERNAL_REMINDER = """<system-reminder>
Note: {file_path} was deleted, either by the user or by a linter. Don't tell the user this, since they are already aware. This change was intentional, so make sure to take it into account as you proceed (ie. don't recreate it unless the user asks you to).
</system-reminder>
"""
