import type { ReactNode } from "react";

import { cn } from "../../lib/utils";

export const COLLAPSE_RAIL_GRID_CLASS_NAME = "grid-cols-[3ch_1fr] gap-x-1.5";

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
  const indicator = expandable ? (open ? "[-]" : "[+]") : "[·]";

  return (
    <div className={cn("flex flex-col items-center self-stretch", className)}>
      <span
        className={cn(
          "mt-0.5 font-mono text-xs text-neutral-500",
          !expandable && inactiveMode === "hidden" && "opacity-0",
          indicatorClassName,
        )}
      >
        {indicator}
      </span>
      {open && expandable ? (
        <div className={cn("mt-1 w-px flex-1 bg-neutral-200", connectorClassName)} />
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

export function CollapseRailPanel({
  open,
  className,
  children,
}: CollapseRailPanelProps): JSX.Element {
  return (
    <div
      className={cn(
        "grid transition-[grid-template-rows,opacity] duration-200 ease-in-out",
        className,
      )}
      style={{ gridTemplateRows: open ? "1fr" : "0fr", opacity: open ? 1 : 0 }}
    >
      <div className="overflow-hidden">{children}</div>
    </div>
  );
}
