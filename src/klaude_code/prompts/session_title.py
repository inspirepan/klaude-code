SESSION_TITLE_SYSTEM_PROMPT = (
    "You generate short, specific conversation titles from user messages. "
    "Use the same language as the user's messages and do not translate. "
    "Reply with only the title, no quotes, no markdown, no explanation."
)

SESSION_TITLE_USER_PROMPT = """Generate a short session title that captures the specific task.

Rules:
- be specific: name the concrete thing being done, not the broad area (BAD: 'TUI 开发', GOOD: '修复终端标题截断问题')
- reflect user intent, not tool usage or internal operations
- use the same language as the user's messages; do not translate
- maximum 80 characters; prefer concise phrasing
- single line, imperative or noun phrase, no filler words
- if a previous title exists and the topic hasn't changed, refine it rather than replace it

{previous_title_block}<previous_user_messages>
{previous_user_messages}
</previous_user_messages>

<current_user_message>
{current_user_message}
</current_user_message>"""
