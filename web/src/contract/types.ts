/**
 * Flat local stand-ins for the upstream cross-package types the vendored
 * Conversation contract referenced. klaude has no plugin graph, so each
 * type is restated here in the shape the trajectory UI actually reads.
 *
 * Provenance (deepseek-harness cd5ef8148158c3a752a658978873241fdf8e2bbc):
 * - `ImageAttachmentRef`  packages/attachment/attachment/src/types.ts
 * - `ContentBlock`        packages/llm/llm/src/types.ts
 * - `ToolSchema`          packages/llm/llm/src/types.ts
 * - `MessageId`           packages/llm/llm/src/brand.ts (branded; flattened to string)
 * - `ConversationLocation`, `MessageImageSource`, `RenderMessageImages`
 *   packages/client/ui-conversation/src/client/contract/{conversation,slots}.ts
 */

import type { ReactNode } from 'react'

/** Raster image formats accepted by the attachment path. */
export type ImageMediaType = 'image/png' | 'image/jpeg' | 'image/webp' | 'image/gif'

/** Durable, serializable reference to one immutable normalized image. */
export interface ImageAttachmentRef {
  /** Opaque storage identifier; never a filesystem path or bearer URL. */
  attachmentId: string
  /** Media type verified from the stored bytes. */
  mediaType: ImageMediaType
  /** Exact encoded byte length. */
  bytes: number
  /** Intrinsic encoded width in pixels. */
  width: number
  /** Intrinsic encoded height in pixels. */
  height: number
  /** Optional display name stripped of local path information. */
  name?: string
  /** Input dimensions before normalization scaling, when it reduced the image. */
  originalDimensions?: {
    width: number
    height: number
  }
}

/**
 * Any known content block; switch on `type` and fall through unknowns. The
 * upstream union is merge-extensible through `ContentBlockMap`; this fork
 * fixes it to the five core arms.
 */
export type ContentBlock =
  | { type: 'text'; text: string }
  | { type: 'reasoning'; text: string }
  | { type: 'image'; attachment: ImageAttachmentRef }
  | { type: 'tool-call'; id: string; name: string; arguments: string }
  | { type: 'tool-result'; toolCallId: string; content: ContentBlock[]; isError?: boolean }

/** One tool advertised to the model in a request header. */
export interface ToolSchema {
  name: string
  description: string
  /** JSON Schema object for the arguments. */
  parameters: Record<string, unknown>
}

/** Stable identity carried by an assistant or steering message. */
export type MessageId = string

/**
 * Engine-owned placement of one matched event in the session hierarchy.
 * Upstream carries the resolved `TurnLocation`/`StepLocation` objects (with
 * their `SessionEvent` boundaries and business data stores); the trajectory UI
 * reads only the two ordinals, so this fork keeps just those.
 */
export type ConversationLocation =
  | { readonly kind: 'session' }
  | { readonly kind: 'turn'; readonly turn: { readonly turn: number } }
  | {
    readonly kind: 'step'
    readonly turn: { readonly turn: number }
    readonly step: { readonly step: number }
  }
  | { readonly kind: 'unresolved' }

/** One image presented in a record: a durable reference or a submission echo. */
export type MessageImageSource =
  | { readonly attachment: ImageAttachmentRef }
  | {
    readonly preview: {
      /** Browser-owned preview URL (lifecycle stays with the submitter). */
      readonly url: string
      readonly name?: string
      /** Intrinsic pixel width, when the intake probe has resolved it. */
      readonly width?: number
      /** Intrinsic pixel height, when the intake probe has resolved it. */
      readonly height?: number
    }
  }

/** Group of record images handed to the host-supplied image renderer. */
export interface MessageImagesOwnerProps {
  /** Durable references or submission-echo previews in source order. */
  images: readonly MessageImageSource[]
  /** Horizontal placement inside the owning record. */
  align: 'start' | 'end'
}

/** Renderer for one group of record images; renders nothing when unimplemented. */
export type RenderMessageImages = (owner: MessageImagesOwnerProps) => ReactNode

/**
 * Ledger statuses that mean "the model stopped seeing this row". The row stays
 * in place, greyed and struck through (UX spec D3); `events.jsonl` is
 * append-only, so discarded content must remain visible.
 */
export type TrajectoryDiscardedStatus = 'retracted' | 'compacted' | 'rewound'

/** Why one ledger row no longer reaches the model. */
export interface TrajectoryDiscarded {
  readonly status: TrajectoryDiscardedStatus
  /** `events.jsonl` line of the marker that invalidated the row. */
  readonly droppedBy: number | null
}

/** Sub-agent session started by one Agent tool call (UX spec D4). */
export interface SubAgentLink {
  readonly sessionId: string
  readonly type: string
  readonly desc: string
}

/**
 * Row facts the klaude adapter knows but `layout.ts` cannot derive: ledger
 * status, the originating raw line, the two klaude-only row kinds, the
 * non-human user tag and the sub-agent session behind an Agent call.
 */
export interface TrajectoryRecordAnnotation {
  /** Zero-based `events.jsonl` line the record came from. */
  readonly lineIndex?: number
  /** Overrides the kind `layout.ts` assigned (`rewind` / `btw`). */
  readonly kind?: 'rewind' | 'btw'
  readonly discarded?: TrajectoryDiscarded
  /** A user row klaude synthesized rather than a human typing it. */
  readonly auto?: true
  readonly subAgent?: SubAgentLink
}

/**
 * Annotations addressed by the identities a projected cell keeps: the source
 * seq for message-backed rows, the call id for tool rows (which carry no seq).
 */
export interface TrajectoryAnnotations {
  readonly bySeq: ReadonlyMap<number, TrajectoryRecordAnnotation>
  readonly byCallId: ReadonlyMap<string, TrajectoryRecordAnnotation>
}
