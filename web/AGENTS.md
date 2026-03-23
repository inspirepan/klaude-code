# Web Frontend Guidelines

Run `pnpm lint` and `pnpm format:check` before committing. Fix all errors; warnings are acceptable.

## Required reading by task

Before making changes, read the relevant docs:

| If you are working on...                                        | MUST read first                                          |
| --------------------------------------------------------------- | -------------------------------------------------------- |
| Styles, colors, typography, spacing, shadows, animation, layout | [DESIGN.md](DESIGN.md) -- full design system spec        |
| Session loading, WebSocket, history, sub-agent, read-only logic | [Session event pipeline](docs/session-event-pipeline.md) |

## Component rules (always apply)

These prevent common visual bugs. Violating them causes hard-to-debug layout/animation issues.

### Buttons & tooltips

- Every `<button>` MUST use the shared `Tooltip` / `TooltipTrigger` / `TooltipContent` from `src/components/ui/tooltip.tsx`. No native `title` attribute.
- Keyboard shortcuts in tooltips use the `kbd` pattern -- see existing tooltip usages for the markup.

### Scroll areas

- Never `overflow-y-auto`. Use `ScrollArea` from `src/components/ui/scroll-area.tsx`.
- Control scrollable height via `viewportClassName` prop, not on the `ScrollArea` root.

### Icon + text alignment

- Single-line: `flex items-center gap-*`. Add `min-h-*` if children appear/disappear conditionally.
- Multi-line: `flex items-start gap-*` + `mt-*` on the icon.
- Never `items-baseline` with icons (icons have no text baseline -- they sink).
- Lucide icons: always `h-* w-* shrink-0`. No `translate-y-*` hacks, no `inline` + `vertical-align`.

### Collapse / expand animation

- Use `height` transition with imperative DOM (`useLayoutEffect` + snapshot height + force reflow). Not `grid-template-rows`.
- Wrap animated content in GPU layer (`backface-visibility: hidden`).
- Never conditionally render (`{open && <El/>}`) near animated containers. Use `opacity` transitions to keep DOM stable.
