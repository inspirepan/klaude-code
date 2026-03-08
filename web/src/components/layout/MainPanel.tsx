import { PanelLeftOpen } from "lucide-react";
import { useAppStore } from "../../stores/app-store";
import { useSessionStore } from "../../stores/session-store";
import { MessageList } from "../messages/MessageList";

export function MainPanel(): JSX.Element {
  const activeSessionId = useSessionStore((state) => state.activeSessionId);
  const sidebarOpen = useAppStore((state) => state.sidebarOpen);
  const setSidebarOpen = useAppStore((state) => state.setSidebarOpen);

  const showDraftToolbar = activeSessionId === "draft" && !sidebarOpen;

  return (
    <main className="main-panel relative">
      {showDraftToolbar ? (
        <div className="flex shrink-0 items-center justify-between px-3 py-2">
          <div>
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
          </div>
          <div />
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
