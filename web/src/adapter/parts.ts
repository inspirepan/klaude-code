/**
 * klaude message `parts` -> upstream content blocks.
 *
 * The block vocabulary is upstream's (`text` / `reasoning` / `image` /
 * `tool-call` / `tool-result`); klaude part names never leak into the ledger.
 * `thinking_signature` parts carry no readable text and are dropped.
 */

import type { AssistantBlock, ContentBlock } from '../contract/index.ts'
import { imageAttachment } from './images.ts'
import { readRecord, readString } from './json.ts'

/** One decoded tool call emitted by an assistant message. */
export interface ToolCallPart {
  readonly callId: string
  readonly name: string
  readonly argsRaw: string
}

/**
 * Text and image blocks for a user, context or tool-result record.
 * @param parts - Raw `parts` array from the entry payload.
 * @param sessionId - Session that owns local image paths.
 * @returns Content blocks in source order.
 */
export function contentBlocks(
  parts: readonly unknown[],
  sessionId: string,
): ContentBlock[] {
  const blocks: ContentBlock[] = []
  for (const raw of parts) {
    const part = readRecord(raw)
    if (part === undefined) continue
    const type = readString(part.type)
    if (type === 'text') {
      blocks.push({ type: 'text', text: readString(part.text) ?? '' })
      continue
    }
    if (type === 'thinking_text') {
      blocks.push({ type: 'reasoning', text: readString(part.text) ?? '' })
      continue
    }
    if (type === 'image_file' || type === 'image_url') {
      const attachment = imageAttachment(part, sessionId)
      if (attachment !== undefined) blocks.push({ type: 'image', attachment })
    }
  }
  return blocks
}

/**
 * Assistant blocks (text, reasoning, tool calls, images) in source order.
 * @param parts - Raw `parts` array from an AssistantMessage payload.
 * @param sessionId - Session that owns local image paths.
 * @returns Assistant blocks in source order.
 */
export function assistantBlocks(
  parts: readonly unknown[],
  sessionId: string,
): AssistantBlock[] {
  const blocks: AssistantBlock[] = []
  for (const raw of parts) {
    const part = readRecord(raw)
    if (part === undefined) continue
    const type = readString(part.type)
    if (type === 'text') {
      blocks.push({ kind: 'text', text: readString(part.text) ?? '' })
      continue
    }
    if (type === 'thinking_text') {
      blocks.push({ kind: 'reasoning', text: readString(part.text) ?? '' })
      continue
    }
    if (type === 'tool_call') {
      const call = toolCallPart(part)
      if (call !== undefined) {
        blocks.push({ kind: 'tool-call', callId: call.callId, name: call.name, argsRaw: call.argsRaw })
      }
      continue
    }
    if (type === 'image_file' || type === 'image_url') {
      const attachment = imageAttachment(part, sessionId)
      if (attachment !== undefined) blocks.push({ kind: 'image', attachment })
    }
  }
  return blocks
}

/**
 * Decode one `tool_call` part.
 * @param part - Raw part payload.
 * @returns The call, or undefined when it has no call id.
 */
export function toolCallPart(part: Record<string, unknown>): ToolCallPart | undefined {
  const callId = readString(part.call_id)
  if (callId === undefined || callId === '') return undefined
  return {
    callId,
    name: readString(part.tool_name) ?? '',
    argsRaw: readString(part.arguments_json) ?? '',
  }
}

/**
 * Concatenate the text parts of one message the way klaude does.
 * @param parts - Raw `parts` array.
 * @returns All `text` part contents joined without a separator.
 */
export function joinTextParts(parts: readonly unknown[]): string {
  let text = ''
  for (const raw of parts) {
    const part = readRecord(raw)
    if (part === undefined) continue
    if (readString(part.type) === 'text') text += readString(part.text) ?? ''
  }
  return text
}
