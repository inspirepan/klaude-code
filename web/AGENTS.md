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
