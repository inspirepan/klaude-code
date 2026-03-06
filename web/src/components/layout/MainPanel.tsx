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
        <div className="flex shrink-0 items-center justify-between px-3 py-2">
          <div>
            {!sidebarOpen ? (
              <button
                type="button"
                className="inline-flex h-8 w-8 cursor-pointer items-center justify-center rounded-lg text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-600"
                onClick={() => {
                  setSidebarOpen(true);
                }}
                title="Expand sidebar"
                aria-label="Expand sidebar"
              >
                <PanelLeftOpen className="h-4 w-4" />
              </button>
            ) : null}
          </div>
          <div>
            {activeSessionId !== "draft" ? (
              <button
                type="button"
                className="inline-flex h-8 w-8 cursor-pointer items-center justify-center rounded-lg text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-600"
                onClick={() => {
                  void selectSession(activeSessionId);
                }}
                title="Refresh session"
                aria-label="Refresh session"
              >
                <RefreshCw className="h-4 w-4" />
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
      {activeSessionId === "draft" ? (
        <div className="flex flex-1 items-center justify-center text-[15px] text-neutral-400">
          New session draft (details area pending)
        </div>
      ) : (
        <MessageList sessionId={activeSessionId} />
      )}
    </main>
  );
}
