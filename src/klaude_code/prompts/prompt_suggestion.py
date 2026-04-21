PROMPT_SUGGESTION_PROMPT = """[SUGGESTION MODE: Predict what the user will naturally type next in this chat.]

Read the recent messages and predict what the user would type — not what you think they should do.
Format: 2-12 words, one short sentence, no formatting. Match the user's natural language (if they wrote Chinese, reply Chinese).

Good suggestions (based on the test "would they think 'I was just about to type that'?"):
- After tests pass → "commit this" or "run the full suite"
- After code written → "try it out"
- After you ask to continue → "yes" / "go ahead"
- Task done, obvious follow-up → "push it"

Never suggest:
- Evaluative ("looks good", "thanks", "great")
- Questions ("what about...?")
- Assistant-voice ("Let me...", "I'll...", "Here's...", "That's...")
- New ideas the user didn't mention
- Multiple sentences or formatting (*, **, newlines, lists)

If the next step is not obvious from the user's own words — the conversation is at a dead end, the user needs to assess, or any recent message was an error — reply with exactly:

[DONE]

Reply with ONLY the suggestion text or [DONE]. No quotes, no explanation, no leading label."""
