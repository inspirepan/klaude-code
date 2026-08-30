/**
 * klaude image parts -> the durable image reference the ledger passes to the
 * host image renderer (UX spec D5).
 *
 * Upstream's `ImageAttachmentRef` addresses a normalized attachment store.
 * klaude has no such store: an image is either an absolute local path
 * (`ImageFilePart.file_path`, served by `/api/web/file`) or a URL that is
 * already loadable (`ImageURLPart.url`, including `data:` URLs). The resolved
 * URL therefore *is* the opaque identifier, and `src/app/render-images.tsx`
 * reads it straight back out of `attachmentId`.
 */

import type { ImageAttachmentRef, ImageMediaType } from '../contract/index.ts'
import { readNumber, readString } from './json.ts'

const MEDIA_TYPES: readonly string[] = ['image/png', 'image/jpeg', 'image/webp', 'image/gif']

/**
 * Endpoint URL for one local image path.
 * @param sessionId - Session that owns the path (the server checks the roots).
 * @param path - Absolute path recorded in the part.
 * @returns Same-origin `/api/web/file` URL.
 */
export function localImageUrl(sessionId: string, path: string): string {
  const query = new URLSearchParams({ session_id: sessionId, path })
  return `/api/web/file?${query.toString()}`
}

function mediaType(value: string | undefined): ImageMediaType {
  return value !== undefined && MEDIA_TYPES.includes(value)
    ? value as ImageMediaType
    : 'image/png'
}

function dataUrlMediaType(url: string): string | undefined {
  const match = /^data:([^;,]+)[;,]/.exec(url)
  return match?.[1]
}

function baseName(path: string): string {
  const parts = path.split('/')
  return parts[parts.length - 1] ?? path
}

/**
 * Project one `image_file` / `image_url` part into a durable image reference.
 * @param part - Decoded part payload.
 * @param sessionId - Session that owns local paths.
 * @returns The reference, or undefined when the part carries no usable source.
 */
export function imageAttachment(
  part: Record<string, unknown>,
  sessionId: string,
): ImageAttachmentRef | undefined {
  const type = readString(part.type)
  if (type === 'image_file') {
    const path = readString(part.file_path)
    if (path === undefined || path === '') return undefined
    return {
      attachmentId: localImageUrl(sessionId, path),
      mediaType: mediaType(readString(part.mime_type)),
      bytes: readNumber(part.byte_size) ?? 0,
      width: 0,
      height: 0,
      name: baseName(path),
    }
  }
  if (type === 'image_url') {
    const url = readString(part.url)
    if (url === undefined || url === '') return undefined
    const sourcePath = readString(part.source_file_path)
    return {
      attachmentId: url,
      mediaType: mediaType(dataUrlMediaType(url)),
      bytes: 0,
      width: 0,
      height: 0,
      ...(sourcePath === undefined ? {} : { name: baseName(sourcePath) }),
    }
  }
  return undefined
}
