import * as React from "react";

import { cn } from "@/lib/utils";
import { ScrollArea } from "./scroll-area";

/**
 * Container panel for dropdown/completion lists.
 * Provides consistent rounded corners, border, background, and shadow.
 * Position, width, z-index, and drop direction are controlled via className.
 */
export function CommandListPanel({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}): JSX.Element {
  return (
    <div
      className={cn("overflow-hidden rounded-xl border border-border/80 bg-background", className)}
    >
      {children}
    </div>
  );
}

/**
 * Scrollable area inside a CommandListPanel.
 * Wraps ScrollArea with consistent inner padding and max-height.
 */
export const CommandListScroll = React.forwardRef<
  HTMLDivElement,
  { maxHeight?: string; children: React.ReactNode }
>(({ maxHeight = "max-h-72", children }, ref) => (
  <ScrollArea ref={ref} className="w-full px-1 py-1.5" viewportClassName={maxHeight} type="hover">
    {children}
  </ScrollArea>
));
CommandListScroll.displayName = "CommandListScroll";

/**
 * Individual selectable item inside a CommandListScroll.
 * Handles highlight state, hover, and click with consistent styling.
 */
export function CommandListItem({
  highlighted,
  className,
  children,
  ...buttonProps
}: {
  highlighted: boolean;
  className?: string;
  children: React.ReactNode;
} & Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "type" | "className">): JSX.Element {
  return (
    <button
      type="button"
      className={cn(
        "mx-1 flex w-[calc(100%-0.5rem)] items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-sm transition-colors",
        highlighted ? "bg-muted text-neutral-900" : "text-neutral-600 hover:bg-surface",
        className,
      )}
      onMouseDown={(e) => {
        e.preventDefault();
      }}
      {...buttonProps}
    >
      {children}
    </button>
  );
}
