"""Model-facing message literals shared across layers.

This module centralizes short text strings that are injected into the LLM
context at runtime (tool results, synthetic user messages, system reminders).
Keep it dependency-free so every layer can import from it.
"""

# Identity
CLAUDE_CODE_IDENTITY = "You are Claude Code, Anthropic's official CLI for Claude."

# Tool result placeholders
CANCEL_OUTPUT = "[Request interrupted by user for tool use]"
EMPTY_TOOL_OUTPUT_MESSAGE = "<system-reminder>Tool ran without output or errors</system-reminder>"
FILE_UNCHANGED_STUB = (
    "File unchanged since last read. The content from the earlier Read tool_result "
    "in this conversation is still current -- refer to that instead of re-reading."
)

# Session interruption
TOOL_INTERRUPTED_MESSAGE = "Tool call was interrupted before completing (session was interrupted or restarted)."

# Checkpoint / rewind
CHECKPOINT_TEMPLATE = "<system-reminder>Checkpoint {checkpoint_id}</system-reminder>"

REWIND_REMINDER_TEMPLATE = (
    "<system-reminder>After this, some operations were performed and context was "
    "refined via Rewind. Rationale: {rationale}. Summary: {note}. "
    "Please continue.</system-reminder>"
)

# Empty LLM response recovery
# Injected as a user message when the model returns an empty turn (no text and no
# tool calls), usually caused by transient provider availability issues. The empty
# turn is not persisted to history, so the model has no visible trace of it -- the
# prompt is phrased as a direct instruction rather than a reference to prior state.
EMPTY_RESPONSE_CONTINUATION_PROMPT = (
    "Please continue. If the task is already complete and there is nothing more "
    "to do, reply with exactly `[DONE]`."
)
