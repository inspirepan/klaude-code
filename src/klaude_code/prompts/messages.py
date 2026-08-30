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

# Legacy: RewindEntry is no longer written; kept so old sessions load.
CHECKPOINT_TEMPLATE = "<system-reminder>Checkpoint {checkpoint_id}</system-reminder>"

REWIND_REMINDER_TEMPLATE = (
    "<system-reminder>After this, some operations were performed and context was "
    "refined via Rewind. Rationale: {rationale}. Summary: {note}. "
    "Please continue.</system-reminder>"
)

# Empty LLM response recovery
# Injected as a user message when the model returns an empty step (no text and no
# tool calls), usually caused by transient provider availability issues. The empty
# step is not persisted to history, so the model has no visible trace of it -- the
# prompt is phrased as a direct instruction rather than a reference to prior state.
EMPTY_RESPONSE_CONTINUATION_PROMPT = (
    "The previous model response was empty, likely due to a transient network or provider issue. "
    "Continue the task from the current conversation state. Do not treat this reminder as a reason to stop; "
    "only provide a final response if the task is genuinely complete."
)

# Stream error partial output recovery
# Injected as a user message when a step dies mid-stream after visible output:
# the partial text is echoed back so the model can resume it instead of
# repeating it. Gated by `RETRY_PRESERVE_PARTIAL_MESSAGE` in `agent/step.py`.
STREAM_ERROR_CONTINUATION_REMINDER = (
    "<system-reminder>"
    "Your previous response was interrupted due to a transient error "
    "(often network-related). "
    "Please continue from where it left off without repeating content you've already provided."
    "</system-reminder>"
)


def build_stream_error_continuation_prompt(partial_text: str) -> str:
    """Echo the partial assistant output back, then ask for a continuation."""
    return f"<assistant>\n{partial_text}\n</assistant>\n\n{STREAM_ERROR_CONTINUATION_REMINDER}"
