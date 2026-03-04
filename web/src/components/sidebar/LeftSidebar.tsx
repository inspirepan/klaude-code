import { PanelLeftClose } from "lucide-react";
import { NewSessionButton } from "./NewSessionButton";
import { ProjectGroup } from "./ProjectGroup";
import { useSessionStore } from "../../stores/session-store";
import { useAppStore } from "../../stores/app-store";
import { ScrollArea } from "@/components/ui/scroll-area";

export function LeftSidebar(): JSX.Element {
  const groups = useSessionStore((state) => state.groups);
  const collapsedByWorkDir = useSessionStore((state) => state.collapsedByWorkDir);
  const runtimeBySessionId = useSessionStore((state) => state.runtimeBySessionId);
  const activeSessionId = useSessionStore((state) => state.activeSessionId);
  const loading = useSessionStore((state) => state.loading);
  const loadError = useSessionStore((state) => state.loadError);
  const selectDraft = useSessionStore((state) => state.selectDraft);
  const toggleGroup = useSessionStore((state) => state.toggleGroup);
  const selectSession = useSessionStore((state) => state.selectSession);
  const refreshSessions = useSessionStore((state) => state.refreshSessions);
  const setSidebarOpen = useAppStore((state) => state.setSidebarOpen);

  return (
    <aside className="w-[260px] min-w-[260px] border-r border-zinc-200 bg-zinc-50 flex flex-col">
      <div className="p-3 flex items-center gap-2">
        <div className="flex-1">
          <NewSessionButton onClick={selectDraft} />
        </div>
        <button
          type="button"
          className="h-10 w-10 shrink-0 inline-flex items-center justify-center rounded-lg border border-zinc-200 bg-white text-zinc-500 hover:bg-zinc-100 hover:text-zinc-700"
          onClick={() => {
            setSidebarOpen(false);
          }}
          title="收起侧边栏"
          aria-label="收起侧边栏"
        >
          <PanelLeftClose className="w-4 h-4" />
        </button>
      </div>

      <ScrollArea className="flex-1 w-full min-h-0" type="auto">
        <div className="px-3 pb-3">
          {loadError !== null ? (
            <div className="mt-3 p-3 border border-dashed border-zinc-300 rounded-lg bg-white">
              <div className="font-semibold mb-1">加载失败</div>
              <div className="text-sm text-zinc-500 break-words">{loadError}</div>
              <button
                type="button"
                className="mt-2 border border-zinc-300 rounded-md bg-white px-2.5 py-1.5 text-sm cursor-pointer"
                onClick={() => {
                  void refreshSessions();
                }}
              >
                点击重试
              </button>
            </div>
          ) : null}

          {loadError === null && loading && groups.length === 0 ? (
            <div className="flex items-center gap-2 px-2 py-2 text-zinc-500">
              <div className="w-4 h-4 rounded-full border-2 border-zinc-200 border-t-zinc-500 animate-spin" />
              <span className="text-[13px] font-medium">加载中...</span>
            </div>
          ) : null}

          {loadError === null && !loading && groups.length === 0 ? (
            <div className="px-2 py-2 text-zinc-500">
              <div className="text-[13px] font-medium">暂无会话</div>
              <div className="text-[12px] mt-0.5">点击上方“New Agent”开始</div>
            </div>
          ) : null}

          {groups.map((group) => (
            <ProjectGroup
              key={group.work_dir}
              workDir={group.work_dir}
              sessions={group.sessions}
              collapsed={collapsedByWorkDir[group.work_dir] ?? false}
              activeSessionId={activeSessionId}
              runtimeBySessionId={runtimeBySessionId}
              onToggle={() => {
                toggleGroup(group.work_dir);
              }}
              onSelectSession={(sessionId) => {
                void selectSession(sessionId);
              }}
            />
          ))}
        </div>
      </ScrollArea>
    </aside>
  );
}
