import { ChevronRight } from "lucide-react";
import { type ReactNode, useLayoutEffect, useRef } from "react";

import { cn } from "../../lib/utils";

export const COLLAPSE_RAIL_GRID_CLASS_NAME = "grid-cols-[16px_1fr] gap-x-1.5";

interface CollapseRailMarkerProps {
  open: boolean;
  expandable?: boolean;
  inactiveMode?: "dot" | "hidden";
  className?: string;
  indicatorClassName?: string;
  connectorClassName?: string;
}

export function CollapseRailMarker({
  open,
  expandable = true,
  inactiveMode = "dot",
  className,
  indicatorClassName,
  connectorClassName,
}: CollapseRailMarkerProps): JSX.Element {
  return (
    <div className={cn("flex flex-col items-center self-stretch", className)}>
      <span
        className={cn(
          "flex h-[1lh] items-center justify-center",
          !expandable && inactiveMode === "hidden" && "opacity-0",
          indicatorClassName,
        )}
      >
        {expandable ? (
          <ChevronRight
            className={cn(
              "h-3.5 w-3.5 shrink-0 text-neutral-400 transition-transform duration-150 ease-out-strong",
              open && "rotate-90",
            )}
          />
        ) : (
          <span className="h-1 w-1 rounded-full bg-neutral-300" />
        )}
      </span>
      {expandable ? (
        <div
          className={cn(
            "mt-1 w-px flex-1 bg-neutral-200 transition-opacity duration-200",
            !open && "opacity-0",
            connectorClassName,
          )}
        />
      ) : null}
    </div>
  );
}

interface CollapseRailConnectorProps {
  className?: string;
  lineClassName?: string;
}

export function CollapseRailConnector({
  className,
  lineClassName,
}: CollapseRailConnectorProps): JSX.Element {
  return (
    <div className={cn("flex justify-center self-stretch", className)}>
      <div className={cn("w-px self-stretch bg-neutral-200", lineClassName)} />
    </div>
  );
}

interface CollapseRailPanelProps {
  open: boolean;
  className?: string;
  children: ReactNode;
}

export const COLLAPSE_RAIL_DURATION_MS = 200;

export function CollapseRailPanel({
  open,
  className,
  children,
}: CollapseRailPanelProps): JSX.Element {
  const ref = useRef<HTMLDivElement>(null);
  const mounted = useRef(false);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;

    // First render: set initial state without animation
    if (!mounted.current) {
      mounted.current = true;
      if (!open) el.style.height = "0px";
      return;
    }

    if (open) {
      // Expanding: animate from current height to content height, then release to auto
      el.style.height = `${el.scrollHeight}px`;
      const timer = setTimeout(() => {
        el.style.height = "auto";
      }, COLLAPSE_RAIL_DURATION_MS + 10);
      return () => clearTimeout(timer);
    } else {
      // Collapsing: snapshot current height, force reflow, then animate to 0
      el.style.transition = "none";
      el.style.height = `${el.getBoundingClientRect().height}px`;
      void el.offsetHeight;
      el.style.transition = "";
      el.style.height = "0px";
    }
  }, [open]);

  return (
    <div
      ref={ref}
      className={cn("overflow-hidden transition-[height] duration-200 ease-out-strong", className)}
    >
      <div style={{ backfaceVisibility: "hidden" }}>{children}</div>
    </div>
  );
}
