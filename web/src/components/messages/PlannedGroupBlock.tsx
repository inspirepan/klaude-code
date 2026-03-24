import { CheckCircle2, CircleDashed } from "lucide-react";
import { Children, type ReactNode, useEffect, useRef, useState } from "react";

import {
  COLLAPSE_RAIL_GRID_CLASS_NAME,
  CollapseRailConnector,
  CollapseRailMarker,
  CollapseRailPanel,
} from "./CollapseRail";
import type { PlannedTodoItem } from "./message-sections";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";

interface PlannedGroupBlockProps {
  todos: PlannedTodoItem[];
  collapsed: boolean;
  onToggle: () => void;
  children: ReactNode;
}

function TodoIcon({ completed }: { completed: boolean }): React.JSX.Element {
  return completed ? (
    <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-700" />
  ) : (
    <CircleDashed className="h-3.5 w-3.5 shrink-0 animate-spin-slow text-blue-500" />
  );
}

export function PlannedGroupBlock({
  todos,
  collapsed,
  onToggle,
  children,
}: PlannedGroupBlockProps): React.JSX.Element {
  const hasContent = Children.count(children) > 0;
  const open = !collapsed;
  const firstCompleted = todos[0]?.completed ?? false;
  // Single line for the summary row; tooltip shows each todo on its own line
  const summaryText = todos.map((t) => t.content).join(" / ");
  const tooltipText = todos.map((t) => t.content).join("\n\n");

  const summaryRef = useRef<HTMLSpanElement>(null);
  const [isTruncated, setIsTruncated] = useState(false);

  useEffect(() => {
    const el = summaryRef.current;
    if (!el) return;
    const check = () => {
      setIsTruncated(el.scrollWidth > el.clientWidth);
    };
    check();
    const observer = new ResizeObserver(check);
    observer.observe(el);
    return () => {
      observer.disconnect();
    };
  }, [summaryText]);

  const headerRow = (
    <span className="flex min-w-0 items-center gap-1.5">
      <TodoIcon completed={firstCompleted} />
      <span ref={summaryRef} className="min-w-0 truncate text-neutral-500">
        {summaryText}
      </span>
    </span>
  );

  return (
    <div>
      <Tooltip>
        <TooltipTrigger asChild>
          {hasContent ? (
            <button
              type="button"
              onClick={onToggle}
              className={`grid w-full min-w-0 ${COLLAPSE_RAIL_GRID_CLASS_NAME} items-start text-left text-sm transition-colors hover:text-neutral-600`}
            >
              <CollapseRailMarker open={open} />
              {headerRow}
            </button>
          ) : (
            <div
              className={`grid w-full min-w-0 ${COLLAPSE_RAIL_GRID_CLASS_NAME} items-start text-left text-sm`}
            >
              <CollapseRailMarker open={false} expandable={false} />
              {headerRow}
            </div>
          )}
        </TooltipTrigger>
        {isTruncated ? (
          <TooltipContent
            side="bottom"
            align="end"
            className="max-w-sm whitespace-pre-wrap break-words"
          >
            {tooltipText}
          </TooltipContent>
        ) : null}
      </Tooltip>
      {hasContent ? (
        <CollapseRailPanel open={open}>
          <div className={`mt-3 grid min-w-0 items-start ${COLLAPSE_RAIL_GRID_CLASS_NAME}`}>
            <CollapseRailConnector lineClassName="-mt-3" />
            <div className="planned-group-content min-w-0 space-y-3 pb-1">{children}</div>
          </div>
        </CollapseRailPanel>
      ) : null}
    </div>
  );
}
