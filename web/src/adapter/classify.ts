/**
 * Which persisted messages a human actually wrote, and which context rows the
 * ledger hides.
 *
 * klaude writes several `UserMessage`s the user never typed. Only `bash_mode`
 * is tagged in the payload (`UserMessage.source`); the rest are recognized by
 * their constant text, exactly as the plan's entry-mapping table specifies:
 *
 * - `prompts/messages.py: EMPTY_RESPONSE_CONTINUATION_PROMPT` (empty step retry)
 * - `agent/step.py: _build_continuation_prompt` (stream-error retry)
 * - `prompts/sub_agents.py: FORK_CONTEXT_{WITH_ROLE,GENERAL}_PROMPT`, wrapped in
 *   `<system-reminder>` by `agent/runtime/sub_agent.py`
 *
 * Only human messages open a turn, so this classification drives turn numbering
 * as well as the `auto` row tag.
 */

/** `prompts/messages.py: EMPTY_RESPONSE_CONTINUATION_PROMPT`. */
export const EMPTY_RESPONSE_CONTINUATION_PROMPT =
  'The previous model response was empty, likely due to a transient network or provider issue. '
  + 'Continue the task from the current conversation state. Do not treat this reminder as a reason to stop; '
  + 'only provide a final response if the task is genuinely complete.'

/** Stable fragment of `agent/step.py: _build_continuation_prompt`. */
export const STREAM_ERROR_CONTINUATION_FRAGMENT =
  'Your previous response was interrupted due to a transient error'

/** Stable fragment of `prompts/sub_agents.py: FORK_CONTEXT_WITH_ROLE_PROMPT`. */
export const FORK_CONTEXT_ROLE_FRAGMENT =
  'You are no longer the main coding agent.'

/** Stable fragment of `prompts/sub_agents.py: FORK_CONTEXT_GENERAL_PROMPT`. */
export const FORK_CONTEXT_GENERAL_FRAGMENT =
  'You are a newly spawned agent with the full conversation context'

/** Legacy `prompts/messages.py: CHECKPOINT_TEMPLATE`, deleted in M0. */
const CHECKPOINT_REMINDER = /<system-reminder>\s*Checkpoint \d+\s*<\/system-reminder>/

/** Why a user row is machine-written, or null when a human wrote it. */
export type AutoUserReason =
  | 'bash_mode'
  | 'empty_response_retry'
  | 'stream_error_retry'
  | 'fork_context'

/**
 * Classify one persisted user message.
 * @param source - `UserMessage.source` from the payload.
 * @param text - The message's joined text parts.
 * @returns The synthesis reason, or null for a human message.
 */
export function autoUserReason(
  source: string | undefined,
  text: string,
): AutoUserReason | null {
  if (source === 'bash_mode') return 'bash_mode'
  const trimmed = text.trim()
  if (trimmed === EMPTY_RESPONSE_CONTINUATION_PROMPT) return 'empty_response_retry'
  if (trimmed.startsWith('<assistant>') && trimmed.includes(STREAM_ERROR_CONTINUATION_FRAGMENT)) {
    return 'stream_error_retry'
  }
  if (
    trimmed.startsWith('<system-reminder>')
    && (trimmed.includes(FORK_CONTEXT_ROLE_FRAGMENT)
      || trimmed.includes(FORK_CONTEXT_GENERAL_FRAGMENT))
  ) return 'fork_context'
  return null
}

/**
 * Whether a developer message is a legacy checkpoint reminder.
 *
 * The checkpoint mechanism was deleted in M0; old sessions still carry the
 * reminders, and the plan hides them (they are pure bookkeeping).
 * @param text - The message's joined text parts.
 * @returns True when the row must not render.
 */
export function isCheckpointReminder(text: string): boolean {
  return CHECKPOINT_REMINDER.test(text)
}
