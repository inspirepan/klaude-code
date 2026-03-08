import { PanelLeftOpen, PanelRightOpen } from "lucide-react";
import { useAppStore } from "../../stores/app-store";
import { useSessionStore } from "../../stores/session-store";
import { MessageComposer } from "../input/MessageComposer";
import { MessageList } from "../messages/MessageList";

export function MainPanel(): JSX.Element {
  const activeSessionId = useSessionStore((state) => state.activeSessionId);
  const sidebarOpen = useAppStore((state) => state.sidebarOpen);
  const rightSidebarOpen = useAppStore((state) => state.rightSidebarOpen);
  const setSidebarOpen = useAppStore((state) => state.setSidebarOpen);
  const setRightSidebarOpen = useAppStore((state) => state.setRightSidebarOpen);

  return (
    <main className="main-panel relative">
      {activeSessionId === "draft" ? (
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="flex h-12 shrink-0 items-center gap-3 border-b border-neutral-200/80 bg-white/95 px-4 backdrop-blur sm:px-6">
            {!sidebarOpen ? (
              <button
                type="button"
                className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-600"
                onClick={() => {
                  setSidebarOpen(true);
                }}
                title="Expand sidebar"
                aria-label="Expand sidebar"
              >
                <PanelLeftOpen className="h-4 w-4" />
              </button>
            ) : null}
            <div className="min-w-0 flex-1">
              <div className="flex min-w-0 items-baseline gap-2 text-[14px] leading-5">
                <span className="truncate font-semibold text-neutral-800">New session</span>
              </div>
            </div>
            {!rightSidebarOpen ? (
              <button
                type="button"
                className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-600"
                onClick={() => {
                  setRightSidebarOpen(true);
                }}
                title="Expand right sidebar"
                aria-label="Expand right sidebar"
              >
                <PanelRightOpen className="h-4 w-4" />
              </button>
            ) : null}
          </div>

          <div className="flex min-h-0 flex-1 items-center justify-center px-4 py-8 sm:px-6">
            <div className="w-full max-w-2xl rounded-3xl border border-dashed border-neutral-200 bg-neutral-50/60 px-6 py-10 text-center">
              <div className="text-[16px] font-semibold text-neutral-700">Start a new session</div>
              <div className="mt-2 text-[14px] leading-6 text-neutral-500">
                Choose a workspace below, then send your first message.
              </div>
            </div>
          </div>
        </div>
      ) : (
        <MessageList sessionId={activeSessionId} />
      )}
      <MessageComposer />
    </main>
  );
}
