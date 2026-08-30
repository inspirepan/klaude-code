SESSION_TITLE_SYSTEM_PROMPT = (
    "You maintain a very short, specific title for a conversation between a user and a coding agent. "
    "The title names the main task of the whole conversation, not the latest message. "
    "Use the same language as the user's messages and do not translate. "
    "Reply with only the title, no quotes, no markdown, no explanation."
)

SESSION_TITLE_USER_PROMPT = """Return the session title for the conversation below.

Rules:
- the title names the main task of the whole conversation; the latest message is only one step of it
- a follow-up step to earlier messages never becomes the title and never changes an existing one: commit, push, run tests, fix lint or types, format, retry, 'continue', a confirmation, a small tweak to the same work
- if a previous title exists, return it unchanged; replace it only when the recent messages ask for work the previous title does not cover at all, such as a different feature or bug
- when the main task did change, name the new task; if the conversation holds several unrelated tasks, name the one the user spent the most messages on
- be specific: name the concrete thing being done, not the broad area (BAD: 'TUI 开发', GOOD: '修复终端标题截断问题')
- reflect user intent, not tool usage or internal operations
- use the same language as the user's messages; do not translate
- prefer 4-10 Chinese characters or 2-5 English words; never exceed 40 characters
- omit repository names, implementation details, and words already implied by context
- single line, imperative or noun phrase, no filler words or redundant qualifiers

{previous_title_block}<user_messages>
{user_messages}
</user_messages>"""
