CONTEXT_REMINDER_HEAD = """<system-reminder>
As you answer the user's questions, you can use the following context:
"""


CLAUDE_MD_REMINDER = """
# claudeMd
Codebase and user instructions are shown below. Be sure to adhere to these instructions. IMPORTANT: These instructions OVERRIDE any default behavior and you MUST follow them exactly as written.

Contents of /Users/bytedance/.claude/CLAUDE.md (user's private global instructions for all projects):
{claude_md}
"""


CONTEXT_REMINDER_TAIL = """
# important-instruction-reminders
Do what has been asked; nothing more, nothing less.
NEVER create files unless they're absolutely necessary for achieving your goal.
ALWAYS prefer editing an existing file to creating a new one.
NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.

IMPORTANT: this context may or may not be relevant to your tasks. You should not respond to this context or otherwise consider it in your response unless it is highly relevant to your task. Most of the time, it is not relevant.
</system-reminder>
"""


def get_context_reminder(claude_md: str) -> str:
    return CONTEXT_REMINDER_HEAD + '\n\n' + CLAUDE_MD_REMINDER.format(claude_md=claude_md) + '\n\n' + CONTEXT_REMINDER_TAIL


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
