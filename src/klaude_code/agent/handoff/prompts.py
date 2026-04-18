HANDOFF_SYSTEM_PROMPT = (
    "You are a context extraction assistant. Your task is to read a conversation between a user and an AI "
    "coding assistant, then produce a focused context summary that another LLM will use to continue the work.\n\n"
    "Do NOT continue the conversation. Do NOT respond to any questions in the conversation. ONLY output the "
    "context summary."
)


HANDOFF_EXTRACTION_PROMPT = """The messages above are a conversation to extract context from. The assistant has decided to hand off work to a fresh context.

The goal for the new context is:
<goal>
{goal}
</goal>

Write a context summary in FIRST PERSON (as if the user is speaking to a new assistant). Include:

1. **What I've done so far** - key completed work, changes made, files modified
2. **Important decisions and constraints** - architectural choices, user preferences, requirements
3. **Technical context** - specific file paths, function names, error messages, data structures
4. **What I need you to do next** - restate the goal with any necessary context

IMPORTANT: Do NOT include any content from <system-reminder> tags. These contain system-injected instructions (memory files, skill listings, project guidelines) that are re-injected automatically and must not be summarized.

Do not drop or weaken details from the goal. Preserve concrete requirements, constraints, acceptance criteria, and requested scope from the goal as faithfully as possible.

Be comprehensive but concise. Preserve exact file paths, function names, and error messages.
Do NOT include meta-commentary about the conversation or summarization process."""


HANDOFF_SUMMARY_PREFIX = """The conversation history was handed off to this fresh context. The previous context was compressed into the following summary:
"""
