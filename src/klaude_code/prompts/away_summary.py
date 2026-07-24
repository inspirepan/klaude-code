AWAY_SUMMARY_SYSTEM_PROMPT = (
    "Write a concise, neutral recap for the returning user. Use the natural language of the [User] messages, "
    "address the reader directly or omit the subject, and never speak as the assistant. "
    "Return only plain recap text."
)

AWAY_SUMMARY_USER_PROMPT = """Summarize where the work stopped in 1-2 short sentences: name the task, current state, and immediate next step. Omit implementation details, status/commit history, evaluation, and encouragement.

<conversation>
{transcript}
</conversation>"""
