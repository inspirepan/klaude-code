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
