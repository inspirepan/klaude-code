import { PanelLeftOpen } from "lucide-react";
import { useAppStore } from "../../stores/app-store";
import { useSessionStore } from "../../stores/session-store";

export function MainPanel(): JSX.Element {
  const activeSessionId = useSessionStore((state) => state.activeSessionId);
  const sidebarOpen = useAppStore((state) => state.sidebarOpen);
  const setSidebarOpen = useAppStore((state) => state.setSidebarOpen);

  return (
    <main className="main-panel relative">
      {!sidebarOpen ? (
        <button
          type="button"
          className="absolute top-3 left-3 h-10 w-10 inline-flex items-center justify-center rounded-lg border border-zinc-200 bg-white text-zinc-500 hover:bg-zinc-100 hover:text-zinc-700"
          onClick={() => {
            setSidebarOpen(true);
          }}
          title="展开侧边栏"
          aria-label="展开侧边栏"
        >
          <PanelLeftOpen className="w-4 h-4" />
        </button>
      ) : null}
      <div className="main-panel__placeholder">
        {activeSessionId === "draft" ? "新会话草稿（详情区待实现）" : `会话 ${activeSessionId}（详情区待实现）`}
      </div>
    </main>
  );
}
