import { PanelLeftOpen, RefreshCw } from "lucide-react";
import { useAppStore } from "../../stores/app-store";
import { useSessionStore } from "../../stores/session-store";
import { MessageList } from "../messages/MessageList";

export function MainPanel(): JSX.Element {
  const activeSessionId = useSessionStore((state) => state.activeSessionId);
  const selectSession = useSessionStore((state) => state.selectSession);
  const sidebarOpen = useAppStore((state) => state.sidebarOpen);
  const setSidebarOpen = useAppStore((state) => state.setSidebarOpen);

  const showToolbar = !sidebarOpen || activeSessionId !== "draft";

  return (
    <main className="main-panel relative">
      {showToolbar ? (
        <div className="flex items-center justify-between px-3 py-2 shrink-0">
          <div>
            {!sidebarOpen ? (
              <button
                type="button"
                className="h-8 w-8 inline-flex items-center justify-center rounded-lg text-neutral-400 hover:bg-neutral-100 hover:text-neutral-600 transition-colors cursor-pointer"
                onClick={() => {
                  setSidebarOpen(true);
                }}
                title="Expand sidebar"
                aria-label="Expand sidebar"
              >
                <PanelLeftOpen className="w-4 h-4" />
              </button>
            ) : null}
          </div>
          <div>
            {activeSessionId !== "draft" ? (
              <button
                type="button"
                className="h-8 w-8 inline-flex items-center justify-center rounded-lg text-neutral-400 hover:bg-neutral-100 hover:text-neutral-600 transition-colors cursor-pointer"
                onClick={() => {
                  void selectSession(activeSessionId);
                }}
                title="Refresh session"
                aria-label="Refresh session"
              >
                <RefreshCw className="w-4 h-4" />
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
      {activeSessionId === "draft" ? (
        <div className="flex-1 flex items-center justify-center text-neutral-400 text-[15px]">
          New session draft (details area pending)
        </div>
      ) : (
        <MessageList sessionId={activeSessionId} />
      )}
    </main>
  );
}
