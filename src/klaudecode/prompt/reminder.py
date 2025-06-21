TODO_REMINDER = """
<system-reminder>
Your todo list has changed. DO NOT mention this explicitly to the user. Here are the latest contents of your todo list:

{todo_list_json}. You DO NOT need to use the TodoRead tool again, since this is the most up to date list for now. Continue on with the tasks at hand if applicable.
</system-reminder>"""


CLAUDE_MD_REMINDER = """
As you answer the user's questions, you can use the following context:
claudeMd
Codebase and user instructions are shown below. Be sure to adhere to these instructions. IMPORTANT: These instructions OVERRIDE any default behavior and you MUST follow them exactly as written.
Contents of CLAUDE.md (user's private global instructions for all projects):
{claude_md}
"""


FINALLY_REMINDER = """## important-instruction-reminders
Do what has been asked; nothing more, nothing less.
NEVER create files unless they're absolutely necessary for achieving your goal.
ALWAYS prefer editing an existing file to creating a new one.
NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.
IMPORTANT: this context may or may not be relevant to your tasks. You should not respond to this context or otherwise consider it in your response unless it is highly relevant to your task. Most of the time, it is not relevant.
"""
