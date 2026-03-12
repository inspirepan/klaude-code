import { useEffect, useRef, useState } from "react";
import { PanelRightClose } from "lucide-react";

import { FilePath } from "../messages/FilePath";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useAppStore } from "../../stores/app-store";
import { useSessionStore } from "../../stores/session-store";
import type { SessionSummary, TodoItem } from "../../types/session";

const todoStatusConfig: Record<
  TodoItem["status"],
  { mark: string; markClass: string; textClass: string }
> = {
  pending: { mark: "□", markClass: "text-neutral-300", textClass: "text-neutral-500" },
  in_progress: { mark: "◉", markClass: "text-blue-600", textClass: "text-neutral-700" },
  completed: {
    mark: "✔",
    markClass: "text-emerald-600",
    textClass: "text-neutral-400 line-through",
  },
};

function findActiveSession(
  groups: SessionSummary[],
  activeSessionId: string | "draft",
): SessionSummary | null {
  if (activeSessionId === "draft") {
    return null;
  }
  return groups.find((item) => item.id === activeSessionId) ?? null;
}

export function RightSidebar(): JSX.Element {
  const groups = useSessionStore((state) => state.groups);
  const activeSessionId = useSessionStore((state) => state.activeSessionId);
  const setRightSidebarOpen = useAppStore((state) => state.setRightSidebarOpen);
  const [sidebarWidth, setSidebarWidth] = useState(288);
  const sidebarResizeCleanupRef = useRef<(() => void) | null>(null);

  const clampSidebarWidth = (width: number): number => {
    const minWidth = 256;
    const hardMaxWidth = 512;
    const leftSidebarWidth =
      (document.querySelector('[data-sidebar="left"]') as HTMLElement | null)?.offsetWidth ?? 0;
    const minMainWidth = 320;
    const availableMaxWidth = window.innerWidth - leftSidebarWidth - minMainWidth;
    const maxWidth = Math.max(minWidth, Math.min(hardMaxWidth, availableMaxWidth));
    return Math.min(Math.max(width, minWidth), maxWidth);
  };

  const activeSession = findActiveSession(
    groups.flatMap((group) => group.sessions),
    activeSessionId,
  );
  const workDir = activeSession?.work_dir ?? "";
  const todos = activeSession?.todos ?? [];
  const fileChangeSummary = activeSession?.file_change_summary ?? {
    created_files: [],
    edited_files: [],
    diff_lines_added: 0,
    diff_lines_removed: 0,
    file_diffs: {},
  };
  const allFiles = [
    ...fileChangeSummary.created_files.map((p) => ({ path: p, kind: "created" as const })),
    ...fileChangeSummary.edited_files.map((p) => ({ path: p, kind: "edited" as const })),
  ];

  useEffect(() => {
    return () => {
      if (sidebarResizeCleanupRef.current !== null) {
        sidebarResizeCleanupRef.current();
        sidebarResizeCleanupRef.current = null;
      }
    };
  }, []);

  return (
    <aside
      data-sidebar="right"
      className="relative flex shrink-0 flex-col border-l border-neutral-200 bg-neutral-50"
      style={{ width: `${sidebarWidth}px`, minWidth: `${sidebarWidth}px` }}
    >
      <div className="flex items-center gap-2 px-3 py-2">
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-600"
              onClick={() => {
                setRightSidebarOpen(false);
              }}
              aria-label="Collapse right sidebar"
            >
              <PanelRightClose className="h-4 w-4" />
            </button>
          </TooltipTrigger>
          <TooltipContent className="flex items-center gap-1.5">
            <span>Collapse right sidebar</span>
            <span className="inline-flex items-center text-neutral-400" aria-hidden="true">
              <span className="inline-flex whitespace-pre text-[12px] leading-none">
                <kbd className="inline-flex font-sans">
                  <span className="min-w-[1em] text-center">⇧</span>
                </kbd>
                <kbd className="inline-flex font-sans">
                  <span className="min-w-[1em] text-center">⌘</span>
                </kbd>
                <kbd className="inline-flex font-sans">
                  <span className="min-w-[1em] text-center">B</span>
                </kbd>
              </span>
            </span>
          </TooltipContent>
        </Tooltip>
        <span className="flex-1 text-xs font-semibold text-neutral-500">Session context</span>
      </div>

      <ScrollArea className="min-h-0 w-full flex-1" type="auto">
        <div className="space-y-3 px-3 pb-3">
          {/* Tasks card */}
          <div className="rounded-lg border border-neutral-200/80 bg-white px-3.5 py-2.5">
            <div className="mb-2 text-xs font-semibold tracking-[0.04em] text-neutral-600">
              To-Do list
            </div>
            {todos.length === 0 ? (
              <div className="text-xs text-neutral-400">No to-dos yet</div>
            ) : (
              <div className="flex flex-col gap-0.5 py-1 text-xs">
                {todos.map((todo) => {
                  const config = todoStatusConfig[todo.status];
                  const textClass =
                    todo.status === "in_progress"
                      ? `${config.textClass} todo-in-progress-shimmer`
                      : config.textClass;
                  return (
                    <div
                      key={`${todo.status}-${todo.content}`}
                      className="flex items-start gap-2 leading-relaxed"
                    >
                      <span className={`w-4 shrink-0 text-center ${config.markClass}`}>
                        {config.mark}
                      </span>
                      <span className={`${textClass} min-w-0 flex-1 break-words`}>
                        {todo.content}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* File changes card */}
          <div className="rounded-lg border border-neutral-200/80 bg-white px-3.5 py-2.5">
            <div className="mb-2 flex items-center gap-2 text-xs font-semibold tracking-[0.04em] text-neutral-600">
              <span>Files</span>
              <span className="inline-flex items-center gap-1 text-[10px] font-medium normal-case tracking-normal">
                <span className="text-emerald-600">+{fileChangeSummary.diff_lines_added}</span>
                <span className="text-rose-600">-{fileChangeSummary.diff_lines_removed}</span>
              </span>
            </div>
            {allFiles.length === 0 ? (
              <div className="text-xs text-neutral-400">No file changes yet</div>
            ) : (
              <div className="flex flex-col gap-0.5 py-1 text-xs">
                {allFiles.map(({ path, kind }) => {
                  const stats = fileChangeSummary.file_diffs[path];
                  return (
                    <div
                      key={`${kind}-${path}`}
                      className="flex items-baseline gap-1.5 leading-relaxed"
                    >
                      <span
                        className={`shrink-0 text-[9px] font-semibold uppercase leading-none ${kind === "created" ? "text-emerald-500" : "text-blue-500"}`}
                      >
                        {kind === "created" ? "N" : "M"}
                      </span>
                      <div className="min-w-0 flex-1 overflow-hidden">
                        <FilePath
                          path={path}
                          workDir={workDir}
                          className="!rounded-none !bg-transparent !px-0 !py-0 !font-sans !text-2xs !leading-none !text-neutral-600"
                          truncateFromStart
                        />
                      </div>
                      {stats ? (
                        <span className="inline-flex shrink-0 items-center gap-1 text-[10px]">
                          <span className="text-emerald-600">+{stats.added}</span>
                          <span className="text-rose-600">-{stats.removed}</span>
                        </span>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </ScrollArea>

      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize right sidebar"
        className="absolute -left-1 top-0 z-30 flex h-full w-2 cursor-col-resize items-center justify-center"
        onPointerDown={(event) => {
          event.preventDefault();
          const startX = event.clientX;
          const startWidth = clampSidebarWidth(sidebarWidth);
          const onPointerMove = (moveEvent: PointerEvent): void => {
            const deltaX = moveEvent.clientX - startX;
            setSidebarWidth(clampSidebarWidth(startWidth - deltaX));
          };
          const onPointerUp = (): void => {
            cleanup();
            sidebarResizeCleanupRef.current = null;
          };
          const cleanup = (): void => {
            window.removeEventListener("pointermove", onPointerMove);
            window.removeEventListener("pointerup", onPointerUp);
          };

          if (sidebarResizeCleanupRef.current !== null) {
            sidebarResizeCleanupRef.current();
          }
          sidebarResizeCleanupRef.current = cleanup;
          window.addEventListener("pointermove", onPointerMove);
          window.addEventListener("pointerup", onPointerUp);
        }}
      >
        <span className="h-full w-px bg-neutral-200/85" />
      </div>
    </aside>
  );
}
