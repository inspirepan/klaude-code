# VENDOR — deepseek-harness fork

`web/` is a **fork**, not a vendored dependency. The UI under `src/trajectory/`,
`src/ui-primitives/`, `src/theme/` and `src/contract/` was copied out of
deepseek-harness and is now maintained here. **We do not sync with upstream.**

- Upstream: <https://github.com/deepseek-ai/deepseek-harness>
- Commit: `cd5ef8148158c3a752a658978873241fdf8e2bbc` (`origin/master`, release
  `dsh-0.1.2-alpha.1`, 2026-08-28)
- License: MIT, `Copyright (c) 2026 DeepSeek` — full text in
  [`LICENSE.deepseek-harness`](./LICENSE.deepseek-harness). Every copied package
  declares `"license": "MIT"`.

## Copied paths

| Fork path | Upstream path | Files | Lines |
|---|---|---|---|
| `src/trajectory/` | `packages/client/ui-trajectory/src/client/` | 17 | 9076 |
| `src/ui-primitives/` | `packages/client/ui-primitives/src/` | 70 | 8493 |
| `src/theme/` | `packages/client/ui-theme/src/styles/` | 4 | 310 |
| `src/contract/` | `packages/client/ui-conversation/src/client/contract/` (3 files) + 2 local | 5 | 472 |
| `src/css-modules.d.ts` | `packages/client/ui-trajectory/src/css-modules.d.ts` | 1 | 6 |

Written by klaude, not copied: `src/adapter/`, `src/locale.ts`, `src/app/`
(including `src/app/live/`, the WebSocket channel), `src/contract/types.ts`,
`src/contract/index.ts`, `index.html`, `package.json`, `tsconfig.json`,
`vite.config.ts`.

## Files dropped from the copy

### `ui-trajectory/src/client/` — glue and dead code

Never copied:

| File | Why |
|---|---|
| `index.ts` | Plugin registration + slot/locale wiring for the upstream host. |
| `invariant.ts` | Upstream plugin-framework invariant companion. |
| `trajectory-snapshot-builder.ts` | Upstream Definition pipeline; klaude's snapshot comes from a REST/WS adapter. |
| `trajectory-definition-common.ts` | idem |
| `trajectory-assistant-definition.ts` | idem |
| `trajectory-compaction-definition.ts` | idem |
| `trajectory-message-definitions.ts` | idem |
| `trajectory-request-header-definition.ts` | idem |
| `trajectory-tool-definition.ts` | idem |
| `trajectory-event-projection.ts` | Projects host `SessionEvent`s; klaude has its own event shapes. |
| `duration-store.ts` | zustand/immer snapshot store; replaced by a `localStorage`-backed prop. |
| `TrajectoryCell.tsx` + `.module.css` | Dead upstream (no importer at this commit). |
| `TrajectoryTurn.tsx` + `.module.css` | idem |
| `TrajectoryTurnHeader.tsx` + `.module.css` | idem |
| `TrajectoryGroupHeader.tsx` + `.module.css` | idem |
| `src/index.ts`, `src/invariant.ts` | Package entry + invariant companion. |
| `tests/` | Not carried in this step; `tests/{table,views,layout,virtual-rows}.client.spec.*` remain a usable regression baseline (open item). |

### `ui-primitives/src/` — deleted after copying

| File | Why |
|---|---|
| `invariant.ts` | Only file coupled to the upstream plugin framework. |
| `ansi.ts` | Sole importer of the `anser` npm package. |
| `TerminalBlock.tsx`, `TerminalBlock.module.css` | Sole importer of `ansi.ts`; nothing kept imports `TerminalBlock`. |

Everything else in `ui-primitives/src/` is kept byte-identical. `Toast`, `Modal`,
`OnboardingSurface`, `RiskConfirmation`, `Menu`, … are unreachable from the
trajectory view but pull no extra dependency, so the tree stays intact.

### `ui-conversation/src/client/contract/`

Only `records.ts`, `request-inspection.ts` and `context-provenance.ts` were
copied. `conversation.ts`, `slots.ts`, `snapshot.ts`, `views.ts`, `input.ts`,
`queue.ts`, `composer-*.ts` are host-plane types; the handful of members the
trajectory UI needs from them were restated flat in `src/contract/types.ts`.

### `ui-theme/src/styles/`

`gradient-shadow-text.css` was not copied (unused by the trajectory surface).

## Edited upstream files

Every deviation carries a trailing or leading `// klaude:` comment so
`diff -r` against an upstream checkout stays auditable.

### `src/trajectory/`

| File | `// klaude:` changes |
|---|---|
| `layout.ts` | Import block: `@deepseek-ai/dsh-client-ui-conversation/client` + `@deepseek-ai/dsh-attachment` → `../contract/index.ts`. |
| `trajectory-record.ts` | Same two imports → `../contract/index.ts`. |
| `trajectory-contract.ts` | Imports → `../contract/index.ts`; trimmed to `TrajectoryRequestHeaderState` + `TrajectorySnapshot`; dropped `TrajectoryContribution`, `TrajectoryConversationViewNode`, `UseTrajectory` and the two `declare module` augmentations. |
| `trajectory-preview.ts` | `@deepseek-ai/dsh-client-ui-primitives` → `../ui-primitives/index.ts`. |
| `locales.ts` | Dropped the `declare module '@deepseek-ai/dsh-client-ui-slots'` `LocaleNamespaceMap` augmentation; `TrajectoryTranslate` is now re-exported from `../locale.ts` instead of aliasing `TranslateNS<'trajectory'>`. Both dictionaries carry 175 keys each (M2 swapped two row-kind keys for three; see below). |
| `TrajectoryTable.tsx` | Import block: primitives → `../ui-primitives/index.ts`; conversation + attachment types → `../contract/index.ts`. Plus the M2 deviations, below. |
| `TrajectoryTimeline.tsx` | `Tooltip` import → `../ui-primitives/index.ts`; `timelineKindLabel` row kinds; `data-discarded` on the span. |
| `TrajectoryToolbar.tsx` | `IconSearchOutline16` import → `../ui-primitives/index.ts`; prop `t: TranslateNS<typeof NS>` → `t: TrajectoryTranslate`. |
| `TrajectoryView.tsx` | See below. |

`trajectory-search-index.ts`, `trajectory-virtual-rows.ts` and `copy-codes.ts`
are **byte-identical** to upstream.

**M2 part 2 (session list + live WS state) added no vendored edit.** The live
channel feeds the two snapshot fields the fork already declares (`partial`,
`runningCalls`), so `TrajectoryView` and `layout.ts` consume it unchanged.

#### M2 deviation edits (2026-08-30)

Every line carries a `// klaude:` (or `/* klaude: */`) marker. Grouped by
deviation:

**D2 — row kinds** (drop the upstream nested-call kind, add `rewind` + `btw`):

| File | Change |
|---|---|
| `trajectory-record.ts` | `TrajectoryCellKind`: nested-call kind out, `rewind` / `btw` in. |
| `TrajectoryTable.tsx` | `KIND_LABEL_KEY`, `KIND_ICON` (+ `IconRefreshOutline14` / `IconQuestionOutline14` imports), `summarizeTurn`, `assistantToolCalls`, `collapseAssistantRecords`, `stateOf`, `parentRecords` (the nested-call parent walk is gone), `toolCallTextParts`, `openRecordSummary`, both kind-tag class chains, the record-overview timing section, and the removed nested-call count row in the request summary. `isMarkdownRecord` / `markdownSource` / `recordDisplayText` gained the new `isMarkdownInputRecord` helper so `rewind` / `btw` read as text records. |
| `TrajectoryTimeline.tsx` | `timelineKindLabel` cases. |
| `timeline.ts` | `laneFor` (both new kinds fall to lane 0 through the default). |
| `layout.ts` | `expandSubCalls` emits `kind: 'tool'`. |
| `locales.ts` | `kind.rewind` / `kind.btw` replace `kind.subtool`; `details.subAgentSession` replaces `details.subtoolCalls` (both dictionaries). |
| `TrajectoryTable.module.css` | `.rewind` / `.btw` badges replace the nested-call badge; the nested-call row selectors are gone. |
| `TrajectoryTimeline.module.css` | span colours for the two kinds. |

**D3 — discarded rows**:

| File | Change |
|---|---|
| `trajectory-record.ts` | `TrajectoryCellProps.discarded` / `lineIndex` / `auto` / `subAgent`. |
| `trajectory-contract.ts` | `TrajectorySnapshot.annotations`. |
| `TrajectoryView.tsx` | Applies `applyTrajectoryAnnotations` inside the `finalized` memo. |
| `TrajectoryTable.tsx` | `data-discarded` and `data-auto` on the row. |
| `timeline.ts` | `TrajectoryTimelineSpan.discarded`, set in both projections. |
| `TrajectoryTimeline.tsx` | `data-discarded` on the span. |
| `TrajectoryTable.module.css` | Dim + line-through mirroring `data-timeline-focus="outside"`, and the `auto` chip. |
| `TrajectoryTimeline.module.css` | `.span[data-discarded='true'] { opacity: .22 }`. |

**D4 — sub-agent link**: `TrajectoryTable.tsx` renders an
`#/s/{sessionId}` link in the record overview when the cell carries `subAgent`.

**D8 — bottom clearance**: `views.module.css` `--dsh-composer-height` fallback
`152px` → `0px`.

**Row identity**: `layout.ts` keys an assistant record on `node.seq` instead of
`assistant\0turn\0step`, so prepending an older page (which renumbers turns)
cannot change a row's React key.

**Source label**: `TrajectoryTable.tsx` `messageSourceLabel` falls back to
`source.type` — klaude's raw entries carry the persisted class name there.

**D5 / D6 / D7 / D9 need no vendored edit**: the image slot is a plain prop
(`src/app/render-images.tsx`), the English badge overrides live in
`src/locale.ts`, the duration preference lives in `src/app/duration.ts`, and
request numbering already falls out of `TrajectoryView`'s upstream
`requestNumbers` memo once the adapter emits a `RequestView` per assistant
message and per compaction.

#### `TrajectoryView.tsx` in detail

The injected-hook surface (`ConvViewProps & PropsRenderSlots & InjectFace &
PropsLocale`) is replaced by one explicit `TrajectoryViewProps` interface:

| Upstream | Fork |
|---|---|
| `useTrajectory(s => s)` | prop `snapshot: TrajectorySnapshot` |
| `useSession(s => s.openState === 'loading')` | prop `session.openState` (`TrajectoryOpenState`, mirrors upstream `OpenState`) |
| `useSession(s => s.loadingOlder)` | prop `session.loadingOlder` |
| `useSession(s => s.hasMore)` | prop `session.hasMore` |
| `useDuration(v => v)` (zustand `SnapshotStore<boolean>`) | props `actualDuration` + `setActualDuration` |
| `renderSlot('conversation.trajectory.images', …)` + `loadImage` | prop `renderImages: RenderMessageImages` |
| `t: TranslateNS<'trajectory'>` | prop `t: TrajectoryTranslate` |
| `loadOlder` (inject face) | prop `loadOlder` |
| `viewRequest` / `completeViewRequest` (view owner props) | kept as optional props |

Everything below the destructuring — `requestNumbers`, the layout memos, the
search index, the timeline wiring, the collapse handlers and the JSX — is
byte-identical to upstream.

### `src/ui-primitives/`

| File | `// klaude:` change |
|---|---|
| `index.ts` | Two `export … from './TerminalBlock.tsx'` lines replaced with a comment. |

`diff -r` against upstream `packages/client/ui-primitives/src` reports exactly:
three deleted files (`invariant.ts`, `ansi.ts`, `TerminalBlock.*`) and that one
`index.ts` hunk.

### `src/contract/`

`types.ts` also declares the adapter's annotation contract
(`TrajectoryDiscarded`, `SubAgentLink`, `TrajectoryRecordAnnotation`,
`TrajectoryAnnotations`), re-exported from `index.ts`.

| File | `// klaude:` changes |
|---|---|
| `records.ts` | Cross-package imports (`dsh-commands/brand`, `dsh-llm/brand`, `dsh-llm/types`, `dsh-attachment`, `dsh-llm-retry/types`, `dsh-tool-todo/client`) → `./types.ts`. Dropped `ModelRetryNode`, `TurnErrorNode`, `TurnMaxTokensNode`, `CommandNode`, `UnknownSurfaceNode` and the `TodoItem` re-export; `ConversationNode` is now the six arms `layout.ts` handles (user / steering / assistant / context / tool-result / compaction). |
| `request-inspection.ts` | `dsh-llm/types` → `./types.ts`. Dropped `RequestPromptInspector` and `inspectRequestPrompt` — they read a host `SessionEvent` that klaude never produces. All the types (`ConversationPromptSnapshot`, `RequestPromptChange`, `RequestView`, `RequestInspectionSnapshot`, …) are unchanged. |
| `context-provenance.ts` | **Unmodified.** |

`types.ts` restates, flat and locally: `ImageAttachmentRef`, `ImageMediaType`,
`ContentBlock`, `ToolSchema`, `MessageId`, `MessageImageSource`,
`MessageImagesOwnerProps`, `RenderMessageImages`, and a flattened
`ConversationLocation`. Upstream's `ConversationLocation` carries resolved
`TurnLocation`/`StepLocation` objects with `SessionEvent` boundaries and
per-location business data stores; the trajectory UI reads only
`location.turn.turn` and `location.step.step` (`layout.ts:878-881`), so the fork
keeps just the two ordinals.

### `src/theme/`

| File | Change |
|---|---|
| `design-platform.css` | The two `body[data-ds-dark-theme] { … }` token blocks (166 of 338 lines) are removed — decision #5, light only. Each is replaced by a one-line `/* klaude: … */` marker. |
| `base.css`, `scrollbar.css`, `shiki.css` | **Unmodified.** |

## Localization

`src/locale.ts` is klaude's translator. It formats `{name}` placeholders exactly
as upstream's does (`packages/client/locale/src/client/index.ts:447-455`:
`template.replace(/\{(\w+)\}/g, …)`, unknown key → the key itself). It composes:

1. the 12 `common` keys the trajectory surface reaches for
   (`copy`, `copied`, `copy.failed`, `copy.value`, `copy.json`, `copy.path`,
   `copy.prettyJson`, `copy.compactJson`, `copy.optionsHint`,
   `json.collapseNode`, `json.expandNode`, `markdown.footnotes`), verbatim from
   `packages/client/locale/src/locales/zh.ts`;
2. the vendored `zh` trajectory dictionary (175 keys);
3. English overrides for the `kind.*` badge keys, `REWIND` and `BTW` included
   (decision #4 / UX spec D6).

## Third-party dependencies

Runtime, versions taken from the upstream manifests at the fork commit:
`react` / `react-dom` `^18.2.0`, `@tanstack/react-virtual` `^3.14.9`,
`diff` `^9.0.0`, `clsx` `^2.0.0`, `shiki` `^4.3.1`, `@shikijs/langs` `^4.3.1`,
`katex` `^0.16.47`, `mdast-util-{from-markdown,gfm,math}`, `@types/mdast`,
`micromark-{core-commonmark,extension-gfm,extension-math,factory-space,util-character,util-classify-character,util-sanitize-uri,util-symbol,util-types}`.

Build: `vite ^6`, `@vitejs/plugin-react ^4`, `typescript ^6.0.3`,
`@types/react ~18.3.1`, `@types/react-dom ~18.3.0`.

Deliberately **not** taken: `zustand`, `immer`, `use-sync-external-store` (went
with `duration-store.ts`), `anser` (went with `ansi.ts` / `TerminalBlock`),
`@types/diff` (`diff@9` ships its own declarations).

The only global CSS side effect inside the component tree is
`src/ui-primitives/markdown/MarkdownText.tsx:23` → `import 'katex/dist/katex.min.css'`;
the KaTeX web fonts it pulls are the only font assets in the bundle.

## Build

`pnpm build` writes `../src/klaude_code/server/web/` (`index.html` + `assets/`),
with `emptyOutDir: true` and `base: '/'`. `pnpm typecheck` is `tsc --noEmit`.
The tsconfig keeps upstream's `allowImportingTsExtensions`,
`rewriteRelativeImportExtensions`, `exactOptionalPropertyTypes`,
`noUncheckedIndexedAccess`, `moduleResolution: "bundler"`, `noUnusedLocals` and
`noUnusedParameters`, so vendored files need no rewriting.

## Open items

- **Build output is not committed.** `src/klaude_code/server/web/` is in the root
  `.gitignore`; the wheel therefore has no web assets unless `pnpm build` runs
  first. Decide before M1 whether to commit `dist` or to build in the release
  pipeline, and add a `wheel-exclude` for `web/node_modules/` either way.
- **Feature deviations from
  [`docs/web-viewer-ux-spec.md`](../docs/web-viewer-ux-spec.md) §12**: D2, D3,
  D4, D5, D6, D7, D8 and D9 are **done** (M2 part 1); **D11** is **done** (M2
  part 2 — `src/app/live/` opens the WS channel only for a session whose meta
  reports `loaded`, so a cold session renders landed rows with no `partial` /
  `runningCalls` and never triggers an `InitAgentOperation`). Still open: **D1**
  timeline scale model (M3) and **D10** (nothing to do — klaude never packs
  chunk rows).
- `src/app/fixture.ts` stays as the `#/fixture` route so the ledger can be
  eyeballed with no server running; the session list links to it.
- **The composite `--dsw-font-*` tokens are undefined.** `base.css` supplies
  `--dsw-font-family` and the easings, but `--dsw-font-xxs-12` /
  `--dsw-font-xs-13` (used across `src/trajectory/*.module.css`) live in
  upstream's deepsuite `theme/global.css`, which was not copied — so every
  `font: var(--dsw-font-…)` declaration is dropped and the text inherits the
  body font. `src/app/SessionList.module.css` passes an explicit fallback;
  fixing it properly means copying the four missing composites into `base.css`.
- **Live channel, known gaps** (`src/app/live/`):
  - `tool.output.delta` is dropped: `RunningToolCall` has nowhere to put
    streaming tool output, so a running tool row stays headline-only until its
    `tool.result` lands.
  - `response.complete` only closes the open block; its `content` /
    `thinking_text` snapshot is not used to repair a partial that lost deltas.
  - The streaming `partial` is anchored on the newest landed row rather than on
    a wire ordinal (the socket has none), so a `Turn N · Step M` label can be
    one step stale for the flush window between a row being written and
    `history.appended` arriving.
  - A trajectory page for an offline session re-reads `meta` every 10 s to
    notice the session waking up; the socket takes over from there.
- ~~**Turn ordinals are window-relative.**~~ **Resolved** (M2 part 2): the
  history endpoint now serves `turn_index` / `step_index` / `auto` per row and
  `turn_count` per page, computed over the whole file by `session/ledger.py`.
  The adapter prefers them and keeps the window-relative count as a fallback for
  an older server; both paths are tested. See
  [`src/adapter/README.md`](./src/adapter/README.md#turn-and-step-numbering).
- **Compaction requests report a zero-length call.** Until `LLMRequestEntry`
  lands (M4) the COMPACT row has no recorded end, so the adapter sets
  `completedAt = startedAt`; a `null` would render the marker as pending, which
  is worse. Usage and Options stay unknown.
- `callSchemas` is always empty: klaude does not persist the tool catalog, so the
  tool inspector's Schema tab is empty until the M4 system-context endpoint.
- Upstream's `ui-trajectory/tests/` were not carried over; `src/adapter/*.test.ts`
  plus `src/app/session-list-model.test.ts` and `src/app/live/*.test.ts` (vitest,
  `pnpm test`) cover the projection, the list model and the live reducer instead.
  None of them mount React: every piece with a behaviour worth pinning is a pure
  function, and the two impure ones (`SessionList`'s poll and
  `use-live-session.ts`'s socket) are thin shells over them.
- Two vendored `ui-primitives` files still name upstream packages in JSDoc
  (`useAnchoredPosition.ts:10`, `relative-time.ts:6` `@module @deepseek-ai/…`),
  and several carry the phrase "cordis-free" in prose plus one
  `IconCordisPluginOutline14` icon export. They are comments and an identifier,
  never imports; they are left alone so the vendored diff stays clean.

- 2026-08-30: copied `ui-theme/src/styles/gradient-shadow-text.css` (light block only) — it defines the `--dsw-font-*` composite font tokens the trajectory CSS consumes; without it every `font: var(--dsw-font-…)` declaration was dropped.
