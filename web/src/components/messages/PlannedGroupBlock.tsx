import { CheckCircle2, ChevronRight, CircleDashed } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "../../lib/utils";
import {
  COLLAPSE_RAIL_GRID_CLASS_NAME,
  CollapseRailConnector,
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
        <div className="flex flex-col items-center self-stretch">
          <span className="flex h-[1lh] items-center justify-center">
            <TodoIcon completed={firstCompleted} />
          </span>
          <div
            className={cn(
              "mt-1 w-px flex-1 bg-neutral-200 transition-opacity duration-200",
              !open && "opacity-0",
            )}
          />
        </div>
        <span className="flex min-w-0 items-center gap-1">
          {todos.length === 1 ? (
            <span
              className={cn(
                "min-w-0 truncate font-mono",
                firstCompleted ? "text-emerald-700" : "text-amber-600",
              )}
            >
              {todos[0]!.content}
            </span>
          ) : (
            <span className="flex min-w-0 items-center gap-1.5 truncate font-mono">
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
          <ChevronRight
            className={cn(
              "h-3.5 w-3.5 shrink-0 text-neutral-400 transition-transform duration-150 ease-out-strong",
              open && "rotate-90",
            )}
          />
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
