/**
 * klaude's translator for the vendored trajectory UI.
 *
 * Upstream threads a namespace-bound `TranslateNS<'trajectory'>` supplied by
 * the locale plugin. This fork ships one language (the upstream `zh`
 * dictionary, 175 keys) plus the shared `common` keys the trajectory surface
 * reaches for, and formats `{name}` params the way upstream's translator does
 * (packages/client/locale/src/client/index.ts).
 */

import { zh as trajectoryZh } from './trajectory/locales.ts'

/** Translate a dictionary key with optional `{name}` template params. */
export type TrajectoryTranslate = (key: string, params?: Record<string, unknown>) => string

/**
 * The `common` namespace keys the trajectory surface and the primitives it
 * renders ask for. Values are verbatim from the upstream common `zh`
 * dictionary (packages/client/locale/src/locales/zh.ts).
 */
const COMMON_ZH: Readonly<Record<string, string>> = {
  'copy': '复制',
  'copied': '复制成功',
  'copy.failed': '复制失败',
  'copy.value': '复制值',
  'copy.json': '复制 JSON',
  'copy.path': '复制属性路径',
  'copy.prettyJson': '复制格式化 JSON',
  'copy.compactJson': '复制紧凑 JSON',
  'copy.optionsHint': '{action}；右键点击可选择复制方式',
  'json.collapseNode': '收起 JSON 节点',
  'json.expandNode': '展开 JSON 节点',
  'markdown.footnotes': '脚注',
}

/**
 * Decision #4: row type badges stay English even though the rest of the
 * surface is Chinese — the badge column is a fixed-width code vocabulary.
 */
const KIND_OVERRIDES: Readonly<Record<string, string>> = {
  'kind.system': 'SYSTEM',
  'kind.user': 'USER',
  'kind.context': 'CONTEXT',
  'kind.compacted': 'COMPACTED',
  'kind.assistant': 'ASSISTANT',
  'kind.tool': 'TOOL',
  'kind.rewind': 'REWIND',
  'kind.btw': 'BTW',
  'kind.message': 'Message',
  'kind.sub': 'Sub',
}

/** Namespace lookup order: trajectory, then common; overrides win. */
const DICTIONARY: Readonly<Record<string, string>> = {
  ...COMMON_ZH,
  ...trajectoryZh,
  ...KIND_OVERRIDES,
}

/**
 * Look one key up and interpolate its `{name}` placeholders.
 * @param key - dictionary key; an unknown key renders as itself.
 * @param params - values for the template placeholders.
 * @returns the formatted string.
 */
export const t: TrajectoryTranslate = (key, params) => {
  const template = DICTIONARY[key] ?? key
  if (params === undefined) return template
  return template.replace(/\{(\w+)\}/g, (match: string, name: string) =>
    name in params ? String(params[name]) : match)
}
