# Web Frontend Guidelines

Run `pnpm lint` and `pnpm format:check` before committing. Fix all errors; warnings are acceptable.

## Tooltip and shortcut hint rules

- Every `<button>` in the web frontend must use the shared tooltip style from `src/components/ui/tooltip.tsx` (`Tooltip`, `TooltipTrigger`, `TooltipContent`). Do not rely on native `title` tooltips for button hints.
- If a button has a keyboard shortcut, show it in the tooltip using the existing `kbd` visual style:

```tsx
<TooltipContent className="flex items-center gap-1.5">
  <span>Action label</span>
  <span className="inline-flex items-center text-neutral-400" aria-hidden="true">
    <span className="inline-flex whitespace-pre text-[12px] leading-none">
      <kbd className="inline-flex font-sans">
        <span className="min-w-[1em] text-center">⌘</span>
      </kbd>
      <kbd className="inline-flex font-sans">
        <span className="min-w-[1em] text-center">B</span>
      </kbd>
    </span>
  </span>
</TooltipContent>
```

## Collapse / expand animation rules

- Use `height` transition with imperative DOM (`useLayoutEffect` + snapshot height + force reflow) instead of `grid-template-rows: 1fr / 0fr`. The grid approach causes sub-pixel jitter in nested grids.
- Wrap animated content in a GPU-composited layer (`backface-visibility: hidden`) to prevent the browser from re-rasterizing content on every frame of the height transition.
- Never conditionally render (`{open && <El/>}`) elements near animated containers. Use `opacity` transitions instead, so the DOM stays stable and no layout recalc is triggered mid-animation.

## Icon and text vertical alignment rules

Icons (Lucide SVGs) and text use different positioning systems (box model vs text baseline). Follow these rules to prevent misalignment:

- **Single-line icon + text:** Use `flex items-center gap-*`. Add `min-h-*` matching the tallest child if elements appear/disappear conditionally (e.g., a spinner during streaming), to prevent the row height from changing and causing a vertical jump.
- **Multi-line text + icon pinned to first line:** Use `flex items-start gap-*` with `mt-*` on the icon to nudge it to the first line's vertical center.
- **Never use `items-baseline` when icons are in the same flex row.** Icons have no text baseline; flex falls back to bottom-edge alignment, causing them to sink below the text.
- **`items-baseline` is fine** when the flex row contains only text elements (different sizes/fonts).
- Lucide icons: use `h-* w-* shrink-0`. Do not use `translate-y-*` pixel hacks to fix alignment; fix the flex container alignment instead.
- Do not use `inline` + `vertical-align` to align icons with text; use flex.

## Scroll area rules

- Never use native `overflow-y-auto` for scrollable containers. Use the shared `ScrollArea` component from `src/components/ui/scroll-area.tsx` (wraps `@radix-ui/react-scroll-area`).
- Control the scrollable height via the `viewportClassName` prop, not on the `ScrollArea` root:

```tsx
<ScrollArea className="w-full" viewportClassName="max-h-40" type="auto">
  <ul>
    {items.map((item) => (
      <li key={item.id}>{item.label}</li>
    ))}
  </ul>
</ScrollArea>
```
