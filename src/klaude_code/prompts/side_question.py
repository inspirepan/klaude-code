SIDE_QUESTION_PROMPT = """[SIDE QUESTION: answer only. Do not act.]

The user asked a question on the side while the work above continues elsewhere.
Answer it from the context you already have.

<side-question>
{question}
</side-question>

Rules for this reply:
- Do not call any tool and do not read or change any file. Text only.
- Do not continue, resume, plan, or comment on the task above unless the question asks about it.
- Answer from the conversation above and your own knowledge. Say what you cannot know from here instead of guessing.
- Be short: a few sentences, or a short list. Markdown is allowed.
- Reply in the language the user wrote the question in.
"""
