AWAY_SUMMARY_SYSTEM_PROMPT = (
    "Write a concise, neutral recap for the returning user. Reply entirely in the natural language used in "
    "the [User] messages: if the user wrote Chinese, reply in Chinese. Never translate to English, and ignore "
    "the language of assistant messages, tool calls, and tool output when choosing the reply language. "
    "Address the reader directly or omit the subject, and never speak as the assistant. "
    "Return only plain recap text."
)

AWAY_SUMMARY_USER_PROMPT = """Language rule (highest priority): write the entire reply in the natural language used in the [User] messages. If the user wrote Chinese, reply in Chinese. Do not translate to English or choose a language from assistant or tool content.

Summarize where the work stopped in 1-2 short sentences: name the task, current state, and immediate next step. Omit implementation details, status/commit history, evaluation, and encouragement.

<conversation>
{transcript}
</conversation>"""
