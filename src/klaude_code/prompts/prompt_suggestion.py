PROMPT_SUGGESTION_PROMPT = """[SUGGESTION MODE: Predict the next message this user is likely to send in this chat.]

Use the conversation to understand the user's current goal, what has just been completed, and what remains unresolved. Pay particular attention to the user's recent messages, wording, preferences, and constraints.

Write one complete message in the user's language and voice, ready to send. Preserve their terminology, file names, and other concrete references. Include scope restrictions when they are supported by the conversation and make the message more useful.

Use the length needed to express the likely intent naturally. Prefer concise wording, but do not omit useful details just to make the message shorter. Multiple sentences are fine when needed; write one plain-text paragraph without line breaks, lists, or formatting.

Predict what this user would say, rather than recommending what they should do. A natural next message may continue a discussion, ask a specific question, request an implementation, or finish the current task. Do not assume the user agrees with a proposal merely because it was presented.

Do not introduce new goals, invent preferences or decisions, repeat a completed request, or speak as the assistant. Avoid generic praise, thanks, and vague suggestions that do not identify a concrete next step.

If several substantially different replies are equally plausible, the user needs to assess the result, or there is not enough evidence for a useful prediction, return exactly [DONE]. Also return [DONE] when an error or misunderstanding leaves the next step unclear.

Output only the predicted user message or [DONE]. No quotes, explanation, or leading label."""
