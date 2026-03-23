import { CheckCircle2, CircleDashed } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "../../lib/utils";
import {
  COLLAPSE_RAIL_GRID_CLASS_NAME,
  CollapseRailConnector,
  CollapseRailMarker,
  CollapseRailPanel,
} from "./CollapseRail";
import type { PlannedTodoItem } from "./message-sections";

interface PlannedGroupBlockProps {
  todos: PlannedTodoItem[];
  collapsed: boolean;
  onToggle: () => void;
  children: ReactNode;
}

function TodoIcon({ completed }: { completed: boolean }): JSX.Element {
  return completed ? (
    <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-700" />
  ) : (
    <CircleDashed className="h-3.5 w-3.5 shrink-0 text-amber-500 animate-spin-slow" />
  );
}

export function PlannedGroupBlock({
  todos,
  collapsed,
  onToggle,
  children,
}: PlannedGroupBlockProps): JSX.Element {
  const open = !collapsed;
  // Use the first todo's status for the rail icon (common case: single todo)
  const firstCompleted = todos[0]?.completed ?? false;

  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        className={`grid w-full min-w-0 ${COLLAPSE_RAIL_GRID_CLASS_NAME} items-start text-left text-base transition-colors hover:text-neutral-600`}
      >
        <CollapseRailMarker open={open} />
        <span className="flex min-w-0 items-center gap-1.5">
          {todos.length === 1 ? (
            <>
              <TodoIcon completed={firstCompleted} />
              <span
                className={cn(
                  "min-w-0 truncate",
                  firstCompleted ? "text-emerald-700" : "text-amber-600",
                )}
              >
                {todos[0]!.content}
              </span>
            </>
          ) : (
            <span className="flex min-w-0 items-center gap-1.5 truncate">
              {todos.map((t, i) => (
                <span key={i} className="flex items-center gap-0.5">
                  {i > 0 ? <span className="text-neutral-300">/</span> : null}
                  <TodoIcon completed={t.completed} />
                  <span className={t.completed ? "text-emerald-700" : "text-amber-600"}>
                    {t.content}
                  </span>
                </span>
              ))}
            </span>
          )}
        </span>
      </button>
      <CollapseRailPanel open={open}>
        <div className={`mt-3 grid min-w-0 items-start ${COLLAPSE_RAIL_GRID_CLASS_NAME}`}>
          <CollapseRailConnector lineClassName="-mt-3" />
          <div className="min-w-0 space-y-3 pb-1">{children}</div>
        </div>
      </CollapseRailPanel>
    </div>
  );
}
