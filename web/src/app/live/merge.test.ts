import { describe, expect, it, vi } from 'vitest'
import type { HistoryPage, HistoryRow, HistoryRowStatus } from '../../adapter/index.ts'
import { row } from '../../adapter/fixtures.ts'
import type { HistoryPageQuery, LoadedWindow } from './merge.ts'
import { hasStatusMarker, mergeHistoryTail, refreshRowStatuses } from './merge.ts'

const SESSION = 'sess1'

function page(rows: readonly HistoryRow[], hasMore = false): HistoryPage {
  return {
    session_id: SESSION,
    line_count: rows.length === 0 ? 0 : (rows[rows.length - 1]?.line_index ?? 0) + 1,
    rows,
    has_more: hasMore,
    next_before_line: rows[0]?.line_index ?? null,
  }
}

function windowOf(rows: readonly HistoryRow[]): LoadedWindow {
  return { rows, hasMore: true, nextBeforeLine: rows[0]?.line_index ?? null }
}

const USER = row(0, 'UserMessage', { parts: [{ type: 'text', text: 'hi' }] })
const ASSISTANT = row(1, 'AssistantMessage', { response_id: 'r1', parts: [] })

/** A fetcher that answers each query from a scripted list, recording calls. */
function scripted(pages: readonly HistoryPage[]) {
  const queries: HistoryPageQuery[] = []
  let index = 0
  const fetchPage = vi.fn(async (query: HistoryPageQuery): Promise<HistoryPage> => {
    queries.push(query)
    const answer = pages[index] ?? page([])
    index += 1
    return await Promise.resolve(answer)
  })
  return { fetchPage, queries }
}

describe('tail increment', () => {
  it('pulls rows after the last loaded line and appends them', async () => {
    const landedRow = row(2, 'ToolResultMessage', {
      call_id: 'c1', tool_name: 'Read', status: 'success', output_text: 'ok',
    })
    const { fetchPage, queries } = scripted([page([landedRow])])
    const result = await mergeHistoryTail(windowOf([USER, ASSISTANT]), fetchPage)

    expect(queries).toEqual([{ afterLine: 1, limit: 500 }])
    expect(result.window.rows.map(entry => entry.line_index)).toEqual([0, 1, 2])
    expect(result.landed).toEqual([landedRow])
    expect(result.refreshed).toBe(false)
    // The older edge is untouched: a tail increment cannot move it.
    expect(result.window.hasMore).toBe(true)
    expect(result.window.nextBeforeLine).toBe(0)
  })

  it('follows has_more across several pages', async () => {
    const { fetchPage, queries } = scripted([
      page([row(2, 'DeveloperMessage', { parts: [] })], true),
      page([row(3, 'DeveloperMessage', { parts: [] })], false),
    ])
    const result = await mergeHistoryTail(windowOf([USER, ASSISTANT]), fetchPage, 1)
    expect(queries).toEqual([{ afterLine: 1, limit: 1 }, { afterLine: 2, limit: 1 }])
    expect(result.landed.map(entry => entry.line_index)).toEqual([2, 3])
  })

  it('returns the same window when nothing landed', async () => {
    const { fetchPage } = scripted([page([])])
    const loaded = windowOf([USER, ASSISTANT])
    const result = await mergeHistoryTail(loaded, fetchPage)
    expect(result.window).toBe(loaded)
    expect(result.landed).toEqual([])
  })

  it('asks for the tail page when nothing is loaded yet', async () => {
    const { fetchPage, queries } = scripted([page([USER, ASSISTANT])])
    const result = await mergeHistoryTail(
      { rows: [], hasMore: false, nextBeforeLine: null },
      fetchPage,
    )
    expect(queries).toEqual([{ limit: 500 }])
    expect(result.window.rows).toEqual([USER, ASSISTANT])
  })
})

describe('marker-triggered status refresh', () => {
  it('spots the entries that restate older statuses', () => {
    expect(hasStatusMarker([USER])).toBe(false)
    expect(hasStatusMarker([row(2, 'CompactionEntry', { summary: '' })])).toBe(true)
    expect(hasStatusMarker([row(2, 'RetractEntry', { retracted_text: '' })])).toBe(true)
    expect(hasStatusMarker([row(2, 'RewindEntry', { note: '' })])).toBe(true)
  })

  it('re-reads the loaded window and replaces statuses in place', async () => {
    const marker = row(2, 'RetractEntry', { retracted_text: 'hi', retracted_line: 0 })
    const restated = (line: number, type: string, status: HistoryRowStatus, droppedBy: number | null) =>
      row(line, type, {}, status, droppedBy)
    const { fetchPage, queries } = scripted([
      page([marker]),
      // The refresh page: line 0 is now retracted, dropped by the marker.
      page([
        restated(0, 'UserMessage', 'retracted', 2),
        restated(1, 'AssistantMessage', 'active', null),
        restated(2, 'RetractEntry', 'sidecar', null),
      ]),
    ])
    const result = await mergeHistoryTail(windowOf([USER, ASSISTANT]), fetchPage)

    expect(queries).toEqual([{ afterLine: 1, limit: 500 }, { beforeLine: 3, limit: 3 }])
    expect(result.refreshed).toBe(true)
    expect(result.window.rows.map(entry => [entry.line_index, entry.status, entry.dropped_by]))
      .toEqual([[0, 'retracted', 2], [1, 'active', null], [2, 'sidecar', null]])
    // Row identity survives: same line numbers, same entry payloads.
    expect(result.window.rows[0]?.entry).toBe(USER.entry)
    expect(result.window.rows[1]).toBe(ASSISTANT)
  })

  it('pages backwards over a window larger than one request', async () => {
    const wide = Array.from({ length: 5 }, (_, index) => row(index, 'UserMessage', { parts: [] }))
    const { fetchPage, queries } = await (async () => {
      const scriptedPages = [
        page([row(5, 'CompactionEntry', { summary: 'squashed' })]),
        page([row(3, 'UserMessage', {}, 'compacted', 5), row(4, 'UserMessage', {}, 'compacted', 5)], true),
        page([
          row(0, 'UserMessage', {}, 'compacted', 5),
          row(1, 'UserMessage', {}, 'compacted', 5),
          row(2, 'UserMessage', {}, 'compacted', 5),
        ], false),
      ]
      return scripted(scriptedPages)
    })()
    const result = await mergeHistoryTail(windowOf(wide), fetchPage)

    expect(queries[1]).toEqual({ beforeLine: 6, limit: 6 })
    expect(queries[2]).toEqual({ beforeLine: 3, limit: 4 })
    expect(result.window.rows.slice(0, 5).every(entry => entry.status === 'compacted')).toBe(true)
  })

  it('keeps rows the refresh could not reach', async () => {
    const { fetchPage } = scripted([page([row(1, 'UserMessage', {}, 'retracted', 5)])])
    const refreshed = await refreshRowStatuses([USER, ASSISTANT], fetchPage)
    expect(refreshed[0]).toBe(USER)
    expect(refreshed[1]?.status).toBe('retracted')
  })
})
