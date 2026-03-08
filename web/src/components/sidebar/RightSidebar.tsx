import { PanelRightClose } from "lucide-react";

import { FilePath } from "../messages/FilePath";
import { ScrollArea } from "@/components/ui/scroll-area";
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

  return (
    <aside className="flex w-[360px] min-w-[360px] flex-col border-l border-neutral-200 bg-neutral-50">
      <div className="flex items-center gap-2 px-3 py-2">
        <button
          type="button"
          className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-600"
          onClick={() => {
            setRightSidebarOpen(false);
          }}
          title="Collapse right sidebar"
          aria-label="Collapse right sidebar"
        >
          <PanelRightClose className="h-4 w-4" />
        </button>
        <span className="flex-1 text-[12px] font-semibold text-neutral-500">Session context</span>
      </div>

      <ScrollArea className="min-h-0 w-full flex-1" type="auto">
        <div className="space-y-3 px-3 pb-3">
          {/* Tasks card */}
          <div className="rounded-lg border border-neutral-200/80 bg-white px-3.5 py-2.5">
            <div className="mb-2 text-[11px] font-semibold tracking-[0.04em] text-neutral-600">
              To-Do list
            </div>
            {todos.length === 0 ? (
              <div className="text-[13px] text-neutral-400">No todos yet</div>
            ) : (
              <div className="flex flex-col gap-0.5 py-1 text-[13px]">
                {todos.map((todo) => {
                  const config = todoStatusConfig[todo.status];
                  return (
                    <div
                      key={`${todo.status}-${todo.content}`}
                      className="flex items-start gap-2 leading-relaxed"
                    >
                      <span className={`w-4 shrink-0 text-center ${config.markClass}`}>
                        {config.mark}
                      </span>
                      <span className={config.textClass}>{todo.content}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* File changes card */}
          <div className="rounded-lg border border-neutral-200/80 bg-white px-3.5 py-2.5">
            <div className="mb-2 flex items-center gap-2 text-[11px] font-semibold tracking-[0.04em] text-neutral-600">
              <span>Files</span>
              <span className="inline-flex items-center gap-1 text-[10px] font-medium normal-case tracking-normal">
                <span className="text-emerald-600">+{fileChangeSummary.diff_lines_added}</span>
                <span className="text-rose-600">-{fileChangeSummary.diff_lines_removed}</span>
              </span>
            </div>
            {allFiles.length === 0 ? (
              <div className="text-[13px] text-neutral-400">No file changes yet</div>
            ) : (
              <div className="flex flex-col gap-0.5 py-1 text-[13px]">
                {allFiles.map(({ path, kind }) => {
                  const stats = fileChangeSummary.file_diffs[path];
                  return (
                    <div
                      key={`${kind}-${path}`}
                      className="flex items-center gap-1.5 leading-relaxed"
                    >
                      <span
                        className={`shrink-0 text-[9px] font-semibold uppercase leading-none ${kind === "created" ? "text-emerald-500" : "text-blue-500"}`}
                      >
                        {kind === "created" ? "N" : "M"}
                      </span>
                      <div className="min-w-0 flex-1 overflow-hidden">
                        <FilePath path={path} workDir={workDir} className="text-xs" />
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
    </aside>
  );
}
