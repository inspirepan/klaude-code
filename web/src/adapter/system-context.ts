/**
 * `GET /api/web/sessions/{id}/system-context` -> the SYSTEM row's prompt snapshot.
 *
 * klaude never persists the system prompt or the tool catalogue (decision #16 /
 * plan "记录检查器"), so the viewer asks for them once per page load and the
 * adapter hangs the answer on the first request of the loaded window. That is
 * what makes `layout.ts` emit its `system` record ("Initial System Prompt")
 * with the System Prompt / Tools tabs.
 *
 * A `rebuilt` answer is not what the session sent: the server re-ran today's
 * prompt builders off the session meta. The snapshot therefore carries a
 * `caveat` the inspector prints, so nobody reads a cold session's SYSTEM row as
 * a recording.
 */

import type { ConversationPromptSnapshot, AssistantRequestConfig, ToolSchema } from '../contract/index.ts'
import type { SystemContext, SystemContextModel } from './wire.ts'

/** Locale keys this module asks the caller's translator for. */
export const REBUILT_CAVEAT_KEY = 'klaude.systemContext.rebuilt'

function text(value: string | null | undefined): string | undefined {
  return typeof value === 'string' && value !== '' ? value : undefined
}

function finite(value: number | null | undefined): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

/**
 * Model knobs -> the inspector's request config.
 *
 * Only the fields the vendored `AssistantRequestConfig` declares are carried;
 * the rest of the allowlist (`verbosity`, `cache_retention`, `fast_mode`,
 * `context_limit`, `supports_vision`) has no upstream slot and is dropped
 * rather than smuggled in under a wrong name.
 * @param model - The endpoint's `model` object, when it sent one.
 * @returns The config; provider/model fall back to empty strings.
 */
export function promptConfig(model: SystemContextModel | null | undefined): AssistantRequestConfig {
  const thinking = model?.thinking
  const effort = text(model?.effort)
  const temperature = finite(model?.temperature)
  const maxTokens = finite(model?.max_tokens)
  return {
    provider: text(model?.provider) ?? '',
    model: text(model?.model) ?? text(model?.model_config_name) ?? '',
    ...(effort === undefined ? {} : { reasoningEffort: effort }),
    ...(temperature === undefined ? {} : { temperature }),
    ...(maxTokens === undefined ? {} : { maxTokens }),
    ...(thinking === undefined || thinking === null
      ? {}
      : { thinking: JSON.stringify(thinking) }),
  }
}

/**
 * The tool catalogue, in the shape the Tools tab and the Schema tab read.
 * @param context - The endpoint payload, when it has been fetched.
 * @returns Tool schemas in server order; empty when none were reported.
 */
export function promptTools(context: SystemContext | undefined): readonly ToolSchema[] {
  const tools = context?.tools
  if (tools === undefined || tools === null) return []
  return tools.map(tool => ({
    name: tool.name,
    description: tool.description,
    parameters: tool.parameters,
  }))
}

/**
 * Build the SYSTEM row's prompt snapshot.
 * @param context - The endpoint payload; `undefined` before it is fetched.
 * @param translate - Locale seat for the `rebuilt` caveat.
 * @returns The snapshot, or undefined when the endpoint reported
 *   `available: false` (then there is no SYSTEM row at all).
 */
export function promptSnapshot(
  context: SystemContext | undefined,
  translate?: (key: string) => string,
): ConversationPromptSnapshot | undefined {
  if (context === undefined || !context.available) return undefined
  const caveat = context.source === 'rebuilt'
    ? translate?.(REBUILT_CAVEAT_KEY) ?? REBUILT_CAVEAT_KEY
    : undefined
  return {
    config: promptConfig(context.model),
    system: context.system_prompt ?? '',
    tools: promptTools(context),
    ...(caveat === undefined ? {} : { caveat }),
  }
}

/**
 * Index the catalogue by tool name so a call id can be resolved to its schema.
 * @param context - The endpoint payload, when it has been fetched.
 * @returns name -> schema; empty when the catalogue is unavailable.
 */
export function toolSchemasByName(
  context: SystemContext | undefined,
): ReadonlyMap<string, ToolSchema> {
  const byName = new Map<string, ToolSchema>()
  if (context === undefined || !context.available) return byName
  for (const tool of promptTools(context)) byName.set(tool.name, tool)
  return byName
}
