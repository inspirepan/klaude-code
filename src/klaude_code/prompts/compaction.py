SUMMARIZATION_SYSTEM_PROMPT = (
    "You are a context summarization assistant. Your task is to read a conversation between a user and an AI "
    "coding assistant, then produce a structured summary following the exact format specified.\n\n"
    "Do NOT continue the conversation. Do NOT respond to any questions in the conversation. ONLY output the "
    "structured summary."
)

SUMMARIZATION_PROMPT = """The messages above are a conversation to summarize. Create a structured context checkpoint summary that another LLM will use to continue the work.

Use this EXACT format:

## Goal
[What is the user trying to accomplish? Can be multiple items if the session covers different tasks.]

## Constraints & Preferences
- [Any constraints, preferences, or requirements mentioned by user]
- [Or "(none)" if none were mentioned]

## Progress
### Done
- [x] [Completed tasks/changes]

### In Progress
- [ ] [Current work]

### Blocked
- [Issues preventing progress, if any]

## Key Decisions
- **[Decision]**: [Brief rationale]

## Next Steps
1. [Ordered list of what should happen next]

## Critical Context
- [Any data, examples, or references needed to continue]
- [Or "(none)" if not applicable]

IMPORTANT: Do NOT include any content from <system-reminder> tags in your summary. These contain system-injected instructions (memory files, skill listings, project guidelines) that are re-injected automatically and must not be summarized.

Keep each section concise. Preserve exact file paths, function names, and error messages."""

UPDATE_SUMMARIZATION_PROMPT = """The messages above are NEW conversation messages to incorporate into the existing summary provided in <previous-summary> tags.

Update the existing structured summary with new information. RULES:
- PRESERVE all existing information from the previous summary
- ADD new progress, decisions, and context from the new messages
- UPDATE the Progress section: move items from "In Progress" to "Done" when completed
- UPDATE "Next Steps" based on what was accomplished
- PRESERVE exact file paths, function names, and error messages
- If something is no longer relevant, you may remove it

Use this EXACT format:

## Goal
[Preserve existing goals, add new ones if the task expanded]

## Constraints & Preferences
- [Preserve existing, add new ones discovered]

## Progress
### Done
- [x] [Include previously done items AND newly completed items]

### In Progress
- [ ] [Current work - update based on progress]

### Blocked
- [Current blockers - remove if resolved]

## Key Decisions
- **[Decision]**: [Brief rationale] (preserve all previous, add new)

## Next Steps
1. [Update based on current state]

## Critical Context
- [Preserve important context, add new if needed]

IMPORTANT: Do NOT include any content from <system-reminder> tags in your summary. These contain system-injected instructions (memory files, skill listings, project guidelines) that are re-injected automatically and must not be summarized.

Keep each section concise. Preserve exact file paths, function names, and error messages."""

TASK_PREFIX_SUMMARIZATION_PROMPT = """This is the PREFIX of a task that was too large to keep. The SUFFIX (recent work) is retained.

Summarize the prefix to provide context for the retained suffix:

## Original Request
[What did the user ask for in this task?]

## Early Progress
- [Key decisions and work done in the prefix]

## Context for Suffix
- [Information needed to understand the retained recent work]

Be concise. Focus on what's needed to understand the kept suffix."""

COMPACTION_SUMMARY_PREFIX = """The conversation history before this point was compacted into the following summary:
"""

COMPACTION_CONTINUATION_INSTRUCTION = (
    "Continue the task from the current conversation state. Do not stop because of this summary; "
    "keep going with the user's latest request."
)

COMPACT_FORK_PROMPT = """This is a meta-instruction for context compaction, not part of the conversation to summarize. Produce a structured context summary of the conversation before this message. Another LLM (or a fresh instance of yourself) will use this summary to continue the session.

Do NOT call any tools. Do NOT continue the task. ONLY output the structured summary text in the exact format below.
Do NOT include this meta-instruction, these tool/continuation/output-format rules, or any wording from this message as user constraints, preferences, progress, decisions, next steps, or critical context.

## Goal
[What is the user trying to accomplish? Can be multiple items if the session covers different tasks.]

## Constraints & Preferences
- [Any constraints, preferences, or requirements mentioned by user in the conversation before this message]
- [Or "(none)" if none were mentioned]

## Progress
### Done
- [x] [Completed tasks/changes]

### In Progress
- [ ] [Current work]

### Blocked
- [Issues preventing progress, if any]

## Key Decisions
- **[Decision]**: [Brief rationale]

## Next Steps
1. [Ordered list of what should happen next]

## Critical Context
- [Any data, examples, or references needed to continue]
- [Or "(none)" if not applicable]

IMPORTANT: Do NOT include any content from <system-reminder> tags in your summary. These contain system-injected instructions (memory files, skill listings, project guidelines) that are re-injected automatically and must not be summarized.

Keep each section concise. Preserve exact file paths, function names, and error messages."""

COMPACT_FORK_UPDATE_PROMPT = """This is a meta-instruction for context compaction, not part of the conversation to summarize. Update the structured context summary. The first user message in this conversation is the PREVIOUS summary; messages after it and before this message are NEW progress to incorporate. Produce a new summary that merges them.

Do NOT call any tools. Do NOT continue the task. ONLY output the updated structured summary.
Do NOT include this meta-instruction, these tool/continuation/output-format rules, or any wording from this message as user constraints, preferences, progress, decisions, next steps, or critical context.

RULES:
- PRESERVE all existing information from the previous summary
- ADD new progress, decisions, and context from the messages after the previous summary
- UPDATE the Progress section: move items from "In Progress" to "Done" when completed
- UPDATE "Next Steps" based on what was accomplished
- PRESERVE exact file paths, function names, and error messages
- If something is no longer relevant, you may remove it

Use this EXACT format:

## Goal
[Preserve existing goals, add new ones if the task expanded]

## Constraints & Preferences
- [Preserve existing, add new ones discovered in messages before this message]

## Progress
### Done
- [x] [Include previously done items AND newly completed items]

### In Progress
- [ ] [Current work - update based on progress]

### Blocked
- [Current blockers - remove if resolved]

## Key Decisions
- **[Decision]**: [Brief rationale] (preserve all previous, add new)

## Next Steps
1. [Update based on current state]

## Critical Context
- [Preserve important context, add new if needed]

IMPORTANT: Do NOT include any content from <system-reminder> tags in your summary. Keep each section concise. Preserve exact file paths, function names, and error messages."""

# ---------------------------------------------------------------------------
# /rewind (fork-with-summary)
# ---------------------------------------------------------------------------

# Prependended to the ForkSummaryEntry summary when it is translated to a
# UserMessage in the new session's LLM-facing view. Covers continuation so the
# entry text itself stays pure summary (unlike CompactionEntry, whose stored
# text carries COMPACTION_CONTINUATION_INSTRUCTION).
FORK_SUMMARY_USER_PREFIX = (
    "The messages above are kept verbatim from before a rewind. The notes below summarize "
    "everything that happened after them in the original session. Continue the work from "
    "where the notes leave off; do not redo completed work.\n\n"
)

FORK_SUMMARY_PROMPT = """This is a meta-instruction for conversation rewind, not part of the conversation to summarize. The user rewound this session to an earlier point. Everything from the following boundary ONWARD — every user message, assistant reply, tool call, and result since — is about to be removed from the session and replaced by your summary. Nothing BEFORE this boundary may be summarized:

__PIVOT_QUOTE__

__SCOPE_NOTE__

Produce a structured context summary of the work done from the pivot boundary onward, so a fresh instance can continue the session without the removed tail.

Do NOT call any tools. Do NOT continue the task. ONLY output the structured summary text in the exact format below.
Do NOT include this meta-instruction, these tool/continuation/output-format rules, or any wording from this message as user constraints, preferences, progress, decisions, next steps, or critical context.

Your summary should include the following sections:

1. Primary Request and Intent: Capture the user's explicit requests and intents from the summarized portion (the pivot message and everything after it).
2. Key Technical Concepts: List important technical concepts, technologies, and frameworks discussed in the summarized portion.
3. Files and Code Sections: Enumerate specific files and code sections examined, modified, or created. Include full code snippets where applicable and a note on why each file matters.
4. Errors and fixes: List errors encountered and how they were fixed. Pay special attention to feedback where the user told you to do something differently.
5. Problem Solving: Document problems solved and any ongoing troubleshooting.
6. All user messages: List ALL user messages from the summarized portion that are not tool results, in order, starting at the pivot boundary. These carry the user's evolving intent.
7. Pending Tasks: Outline tasks that were explicitly requested but are not finished.
8. Current Work: Describe precisely what was being worked on immediately before the rewind.
9. Optional Next Step: List the next step directly in line with the most recent work. Include verbatim quotes showing where the work left off. If the last task was concluded, say so instead of inventing next steps.

IMPORTANT: Do NOT include any content from <system-reminder> tags in your summary. These contain system-injected instructions (memory files, skill listings, project guidelines) that are re-injected automatically and must not be summarized.

Keep each section concise. Preserve exact file paths, function names, and error messages."""


def build_user_pivot_quote(text: str) -> str:
    """Boundary quote block for a user-message pivot (truncated by the caller)."""
    return f"<pivot-user-message>\n{text}\n</pivot-user-message>"



def build_fork_summary_prompt(*, pivot_quote: str, inline_conversation: bool = False) -> str:
    """Build the /rewind summary instruction.

    ``pivot_quote`` is the verbatim boundary block (see the builders above) so
    the model locates the boundary deterministically instead of guessing where
    the kept prefix ends. ``inline_conversation=True`` selects the wording for
    the non-cache-sharing fallback, where the serialized tail is embedded in
    the same request message instead of living in the transcript above.
    """
    if inline_conversation:
        scope_note = (
            "The conversation to summarize is provided below, inside <conversation> tags. "
            "It contains the entire tail being removed; nothing else from the session is "
            "available to you."
        )
    else:
        scope_note = (
            "The conversation to summarize is the part of the transcript above this message "
            "that follows the pivot boundary. The kept prefix is already in context; do not "
            "restate it beyond what the sections below require."
        )
    return FORK_SUMMARY_PROMPT.replace("__PIVOT_QUOTE__", pivot_quote).replace("__SCOPE_NOTE__", scope_note)
