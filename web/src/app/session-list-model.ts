/**
 * Pure model behind the session list page.
 *
 * `GET /api/web/sessions` returns a flat array whose only structure is
 * `parent_session_id`. Everything the page needs on top of that — the parent
 * tree, the sort, the substring filter, the visible-row flattening — is here,
 * so it can be tested without a DOM.
 */

import type { SessionListRow, SessionState, SessionStatus, SpawnedChild } from '../adapter/index.ts'
// Direct file import, not the barrel: this module must stay DOM-free.
import { relativeTime } from '../ui-primitives/relative-time.ts'

/** The primary categories used by list filters and badges. */
export const SESSION_STATES: readonly SessionState[] = ['needs_you', 'working', 'idle']

/** Read the authoritative snapshot, not a task's historical outcome. */
export function rowState(row: SessionListRow): SessionState {
  return row.status.category
}

/** Whether a category deserves a live dot. */
export function isWorkingState(state: SessionState): boolean {
  return state === 'working'
}

/** Keep execution visible even when attention takes category precedence. */
export function statusLabel(status: SessionStatus): string {
  return [
    status.category,
    ...(status.execution === 'none' ? [] : [status.execution]),
    ...new Set(status.attention.map(reason => reason.kind)),
  ].join(' · ')
}

/**
 * Last path segment of a work dir, for the directory badge.
 * @param path - Absolute work dir, or null.
 * @returns The basename, or null when there is nothing to show.
 */
export function workDirName(path: string | null | undefined): string | null {
  if (path === null || path === undefined || path === '') return null
  const parts = path.split('/').filter(part => part !== '')
  return parts[parts.length - 1] ?? path
}

/**
 * Row title, falling back to the short session id.
 * @param row - One list row.
 * @returns A non-empty label.
 */
export function rowTitle(row: SessionListRow): string {
  const title = row.title ?? row.name ?? ''
  return title.trim() === '' ? row.id.slice(0, 8) : title
}

/** Trimmed text, or null when there is nothing to show. */
function text(value: string | null | undefined): string | null {
  if (value === null || value === undefined) return null
  const trimmed = value.trim()
  return trimmed === '' ? null : trimmed
}

/**
 * Messages recorded for a session, or null when the server does not know.
 *
 * `meta.json` gained the field late, and the index reports `-1` for a session
 * written before it — an unknown count, not an empty one.
 * @param row - One list row.
 * @returns A count of 0 or more, or null when unknown.
 */
export function messagesCount(row: SessionListRow): number | null {
  const value = row.messages_count
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return null
  return Math.trunc(value)
}

/** What a row shows for itself: an optional sub-agent badge, then a title. */
export interface RowLabel {
  /** The sub-agent's type; null for a row that is not a sub-agent session. */
  readonly badge: string | null
  readonly title: string
}

/**
 * Join a list row with the spawn row its parent's ledger recorded for it.
 *
 * A sub-agent session has no title of its own, so on the list it reads as an
 * 8-character id. The two facts a reader wants — which kind of agent it is and
 * what it was asked to do — live in the parent's `SpawnSubAgentEntry`
 * (`GET /api/web/sessions/{parent}/children`). The row's own `agent_type` is
 * the fallback badge: the child's meta always carries it, even when the
 * parent's ledger has not been fetched, or no longer holds the spawn row.
 * @param row - One list row.
 * @param spawn - The parent's spawn row for it, when known.
 * @returns The badge and title to render.
 */
export function rowLabel(row: SessionListRow, spawn?: SpawnedChild | null): RowLabel {
  const agentType = text(spawn?.sub_agent_type) ?? text(row.agent_type)
  return {
    // Only a child gets a badge: a root session is `main`, which says nothing.
    badge: text(row.parent_session_id) !== null && agentType !== 'main' ? agentType : null,
    title: text(spawn?.sub_agent_desc) ?? rowTitle(row),
  }
}

/**
 * Compact relative time for a list row.
 *
 * `updated_at` is epoch **seconds** on this endpoint; `relativeTime` buckets
 * epoch ms, and the words are ours (the primitive stays locale-free).
 * @param updatedAt - `row.updated_at`, epoch seconds.
 * @param now - Current epoch ms.
 * @returns A short label such as `5min`, or an empty string when undated.
 */
export function relativeUpdated(
  updatedAt: number | null | undefined,
  now: number,
): string {
  if (typeof updatedAt !== 'number' || !Number.isFinite(updatedAt)) return ''
  const bucket = relativeTime(updatedAt * 1000, now)
  switch (bucket.unit) {
    case 'now': return 'now'
    case 'minutes': return `${bucket.n}min`
    case 'hours': return `${bucket.n}h`
    case 'days': return `${bucket.n}d`
    case 'months': return `${bucket.n}mo`
    case 'years': return `${bucket.n}y`
  }
}

/**
 * Substring filter over the three fields the box advertises.
 *
 * Space-separated terms are ANDed, matched case-insensitively against title,
 * work dir, model — and the session id, so a pasted id always finds its row.
 * @param rows - All rows.
 * @param query - The filter box's contents.
 * @returns The matching rows, in input order.
 */
export function filterSessionRows(
  rows: readonly SessionListRow[],
  query: string,
): readonly SessionListRow[] {
  const terms = query.toLowerCase().split(/\s+/).filter(term => term !== '')
  if (terms.length === 0) return rows
  return rows.filter((row) => {
    const haystack = [
      row.title ?? '', row.name ?? '', row.work_dir ?? '', row.model ?? '', row.id,
      row.status.category, row.status.execution, ...row.status.attention.map(item => item.kind),
    ].join('\0').toLowerCase()
    return terms.every(term => haystack.includes(term))
  })
}

/** One row placed in the parent tree. */
export interface SessionTreeNode {
  readonly row: SessionListRow
  /** Nesting level; roots are 0. */
  readonly depth: number
  readonly children: readonly SessionTreeNode[]
  /**
   * Parent id when the row renders flat instead of nested — its parent is not
   * in the list (filtered out, or beyond the page limit), or the parent chain
   * looped. Null for a true root and for every nested child.
   */
  readonly orphanParent: string | null
  /** Descendants at any depth, for the collapsed count badge. */
  readonly descendants: number
}

function byUpdatedDesc(left: SessionListRow, right: SessionListRow): number {
  const delta = (right.updated_at ?? 0) - (left.updated_at ?? 0)
  return delta !== 0 ? delta : left.id.localeCompare(right.id)
}

/**
 * Group rows into parent trees, newest first at every level.
 *
 * A row whose `parent_session_id` is absent from the list is a root with an
 * `orphanParent` link rather than a hidden row — sub-agent sessions outlive
 * the page limit and the filter box, and losing them would be worse than
 * showing them flat.
 * @param rows - Rows from the list endpoint, any order.
 * @returns Root nodes sorted by `updated_at` descending.
 */
export function buildSessionTree(
  rows: readonly SessionListRow[],
): readonly SessionTreeNode[] {
  const present = new Set(rows.map(row => row.id))
  const childrenOf = new Map<string, SessionListRow[]>()
  const roots: SessionListRow[] = []
  for (const row of rows) {
    const parent = row.parent_session_id ?? null
    if (parent !== null && parent !== row.id && present.has(parent)) {
      const bucket = childrenOf.get(parent)
      if (bucket === undefined) childrenOf.set(parent, [row])
      else bucket.push(row)
      continue
    }
    roots.push(row)
  }

  // A malformed parent chain must neither hang the page nor swallow a row.
  const visited = new Set<string>()
  const build = (row: SessionListRow, depth: number): SessionTreeNode => {
    visited.add(row.id)
    const parent = row.parent_session_id ?? null
    const kids = (childrenOf.get(row.id) ?? [])
      .filter(child => !visited.has(child.id))
      .sort(byUpdatedDesc)
      .map(child => build(child, depth + 1))
    return {
      row,
      depth,
      children: kids,
      orphanParent: depth === 0 && parent !== null && parent !== row.id ? parent : null,
      descendants: kids.reduce((total, kid) => total + 1 + kid.descendants, 0),
    }
  }
  const nodes = roots.sort(byUpdatedDesc).map(row => build(row, 0))
  // Rows inside a parent cycle have no root to hang from; show them flat
  // rather than dropping them.
  const stranded = rows.filter(row => !visited.has(row.id)).sort(byUpdatedDesc)
  for (const row of stranded) {
    if (visited.has(row.id)) continue
    nodes.push(build(row, 0))
  }
  return stranded.length === 0
    ? nodes
    : nodes.sort((left, right) => byUpdatedDesc(left.row, right.row))
}

/**
 * The rows a tree renders, in order, given which parents are expanded.
 * @param nodes - Root nodes from `buildSessionTree`.
 * @param expanded - Ids of parents whose children are visible.
 * @returns Visible nodes, parents before their children.
 */
export function flattenSessionTree(
  nodes: readonly SessionTreeNode[],
  expanded: ReadonlySet<string>,
): readonly SessionTreeNode[] {
  const flat: SessionTreeNode[] = []
  const walk = (node: SessionTreeNode) => {
    flat.push(node)
    if (node.children.length === 0 || !expanded.has(node.row.id)) return
    for (const child of node.children) walk(child)
  }
  for (const node of nodes) walk(node)
  return flat
}
