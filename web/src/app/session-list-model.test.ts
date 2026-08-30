import { describe, expect, it } from 'vitest'
import type { SessionListRow, SpawnedChild } from '../adapter/index.ts'
import {
  buildSessionTree, filterSessionRows, flattenSessionTree, isLiveState, messagesCount,
  relativeUpdated, rowLabel, rowState, rowTitle, workDirName,
} from './session-list-model.ts'

/** `updated_at` is epoch **seconds** on this endpoint. */
const T0 = 1_800_000_000

function listRow(id: string, fields: Partial<SessionListRow> = {}): SessionListRow {
  return { id, updated_at: T0, ...fields }
}

function spawn(childId: string, fields: Partial<SpawnedChild> = {}): SpawnedChild {
  return {
    session_id: childId,
    sub_agent_type: 'code-reviewer',
    sub_agent_desc: 'review the loader change',
    model: null,
    created_at: '2026-08-30T10:00:00',
    line_index: 3,
    ...fields,
  }
}

describe('row fields', () => {
  it('falls back to the short session id when there is no title', () => {
    expect(rowTitle(listRow('abcdef0123456789'))).toBe('abcdef01')
    expect(rowTitle(listRow('abcdef01', { title: '  ' }))).toBe('abcdef01')
    expect(rowTitle(listRow('abcdef01', { title: 'refactor the loader' })))
      .toBe('refactor the loader')
    expect(rowTitle(listRow('abcdef01', { name: 'finder-1' }))).toBe('finder-1')
  })

  it('badges the work dir by its basename', () => {
    expect(workDirName('/Users/x/code/klaude-code')).toBe('klaude-code')
    expect(workDirName('/Users/x/code/klaude-code/')).toBe('klaude-code')
    expect(workDirName('')).toBeNull()
    expect(workDirName(null)).toBeNull()
  })

  it('normalizes the six-state vocabulary and marks the two live ones', () => {
    expect(rowState(listRow('a', { state: 'waiting_input' }))).toBe('waiting_input')
    // A cold session reports `completed`; anything unknown reads the same way.
    expect(rowState(listRow('a', { state: 'no_such_state' }))).toBe('completed')
    expect(rowState(listRow('a'))).toBe('completed')
    expect(isLiveState('running')).toBe(true)
    expect(isLiveState('waiting_input')).toBe(true)
    expect(isLiveState('queued')).toBe(false)
    expect(isLiveState('idle')).toBe(false)
  })

  it('renders updated_at as a compact bucket, converting seconds to ms', () => {
    const now = T0 * 1000
    expect(relativeUpdated(T0, now)).toBe('now')
    expect(relativeUpdated(T0 - 300, now)).toBe('5min')
    expect(relativeUpdated(T0 - 3 * 3600, now)).toBe('3h')
    expect(relativeUpdated(T0 - 2 * 86400, now)).toBe('2d')
    expect(relativeUpdated(null, now)).toBe('')
  })
})

describe('message count', () => {
  it('reports the count and treats the pre-field sentinel as unknown', () => {
    expect(messagesCount(listRow('a', { messages_count: 198 }))).toBe(198)
    expect(messagesCount(listRow('a', { messages_count: 0 }))).toBe(0)
    // `session_index.py` reports -1 for a meta written before the field.
    expect(messagesCount(listRow('a', { messages_count: -1 }))).toBeNull()
    expect(messagesCount(listRow('a'))).toBeNull()
    expect(messagesCount(listRow('a', { messages_count: null }))).toBeNull()
  })
})

describe('sub-agent label', () => {
  const child = listRow('cccc1111ffff', { parent_session_id: 'root-a', agent_type: 'code-reviewer' })

  it('takes the type and the description from the parent spawn row', () => {
    expect(rowLabel(child, spawn('cccc1111ffff'))).toEqual({
      badge: 'code-reviewer',
      title: 'review the loader change',
    })
  })

  it('falls back to the short id and the child meta type without a spawn row', () => {
    expect(rowLabel(child)).toEqual({ badge: 'code-reviewer', title: 'cccc1111' })
    expect(rowLabel(child, null)).toEqual({ badge: 'code-reviewer', title: 'cccc1111' })
    // An empty description is no description.
    expect(rowLabel(child, spawn('cccc1111ffff', { sub_agent_desc: '  ' })).title).toBe('cccc1111')
  })

  it('prefers the spawn row type over the one on the child meta', () => {
    expect(rowLabel(listRow('c1', { parent_session_id: 'p', agent_type: 'general-purpose' }),
      spawn('c1', { sub_agent_type: 'finder' })).badge).toBe('finder')
  })

  it('badges no root row, whose type is always `main`', () => {
    expect(rowLabel(listRow('root-a', { title: 'fix the loader', agent_type: 'main' })))
      .toEqual({ badge: null, title: 'fix the loader' })
    // A child that somehow reports `main` gets no badge either.
    expect(rowLabel(listRow('c2', { parent_session_id: 'p', agent_type: 'main' })).badge).toBeNull()
    // ... and one with no type at all keeps the badge column empty.
    expect(rowLabel(listRow('c3', { parent_session_id: 'p' })).badge).toBeNull()
  })
})

describe('filter', () => {
  const rows = [
    listRow('aaa1', { title: 'fix the adapter', work_dir: '/w/klaude-code', model: 'opus' }),
    listRow('bbb2', { title: 'web viewer', work_dir: '/w/other', model: 'sonnet' }),
  ]

  it('matches title, dir and model case-insensitively', () => {
    expect(filterSessionRows(rows, 'ADAPTER').map(row => row.id)).toEqual(['aaa1'])
    expect(filterSessionRows(rows, 'other').map(row => row.id)).toEqual(['bbb2'])
    expect(filterSessionRows(rows, 'sonnet').map(row => row.id)).toEqual(['bbb2'])
  })

  it('ANDs space-separated terms and finds a pasted id', () => {
    expect(filterSessionRows(rows, 'web sonnet').map(row => row.id)).toEqual(['bbb2'])
    expect(filterSessionRows(rows, 'web opus')).toEqual([])
    expect(filterSessionRows(rows, 'aaa1').map(row => row.id)).toEqual(['aaa1'])
  })

  it('returns the input untouched for an empty query', () => {
    expect(filterSessionRows(rows, '   ')).toBe(rows)
  })
})

describe('parent grouping', () => {
  const rows = [
    listRow('child-old', { parent_session_id: 'root-a', updated_at: T0 - 100 }),
    listRow('root-b', { updated_at: T0 - 50 }),
    listRow('root-a', { updated_at: T0 - 200 }),
    listRow('child-new', { parent_session_id: 'root-a', updated_at: T0 - 10 }),
    listRow('grandchild', { parent_session_id: 'child-new', updated_at: T0 - 5 }),
    listRow('orphan', { parent_session_id: 'gone', updated_at: T0 - 300 }),
  ]

  it('sorts roots by updated_at descending and nests children', () => {
    const tree = buildSessionTree(rows)
    expect(tree.map(node => node.row.id)).toEqual(['root-b', 'root-a', 'orphan'])
    const rootA = tree[1]
    expect(rootA?.children.map(node => node.row.id)).toEqual(['child-new', 'child-old'])
    expect(rootA?.descendants).toBe(3)
    expect(rootA?.children[0]?.children.map(node => node.row.id)).toEqual(['grandchild'])
    expect(rootA?.children[0]?.depth).toBe(1)
    expect(rootA?.children[0]?.children[0]?.depth).toBe(2)
  })

  it('keeps a row whose parent is not in the list, flat, with a parent link', () => {
    const tree = buildSessionTree(rows)
    const orphan = tree.find(node => node.row.id === 'orphan')
    expect(orphan?.depth).toBe(0)
    expect(orphan?.orphanParent).toBe('gone')
    // A nested child is not an orphan even though it has a parent.
    expect(tree.find(node => node.row.id === 'root-a')?.orphanParent).toBeNull()
  })

  it('survives a parent cycle', () => {
    const cyclic = [
      listRow('x', { parent_session_id: 'y' }),
      listRow('y', { parent_session_id: 'x' }),
    ]
    const tree = buildSessionTree(cyclic)
    const seen = new Set<string>()
    const walk = (nodes: ReturnType<typeof buildSessionTree>) => {
      for (const node of nodes) {
        expect(seen.has(node.row.id)).toBe(false)
        seen.add(node.row.id)
        walk(node.children)
      }
    }
    walk(tree)
    expect(seen.size).toBe(2)
  })

  it('shows children only for expanded parents', () => {
    const tree = buildSessionTree(rows)
    expect(flattenSessionTree(tree, new Set()).map(node => node.row.id))
      .toEqual(['root-b', 'root-a', 'orphan'])
    expect(flattenSessionTree(tree, new Set(['root-a'])).map(node => node.row.id))
      .toEqual(['root-b', 'root-a', 'child-new', 'child-old', 'orphan'])
    expect(flattenSessionTree(tree, new Set(['root-a', 'child-new'])).map(node => node.row.id))
      .toEqual(['root-b', 'root-a', 'child-new', 'grandchild', 'child-old', 'orphan'])
  })

  it('surfaces a matching child as a root when the filter drops its parent', () => {
    const tree = buildSessionTree(filterSessionRows(rows, 'child-old'))
    expect(tree.map(node => node.row.id)).toEqual(['child-old'])
    expect(tree[0]?.orphanParent).toBe('root-a')
  })
})
