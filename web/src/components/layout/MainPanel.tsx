import { PanelLeftOpen, PanelRightOpen } from "lucide-react";
import { useAppStore } from "../../stores/app-store";
import { useSessionStore } from "../../stores/session-store";
import { MessageComposer } from "../input/MessageComposer";
import { NewSessionOverlay } from "../input/NewSessionOverlay";
import { MessageList } from "../messages/MessageList";

export function MainPanel(): JSX.Element {
  const activeSessionId = useSessionStore((state) => state.activeSessionId);
  const isDraft = activeSessionId === "draft";
  const sidebarOpen = useAppStore((state) => state.sidebarOpen);
  const rightSidebarOpen = useAppStore((state) => state.rightSidebarOpen);
  const newSessionOverlayOpen = useAppStore((state) => state.newSessionOverlayOpen);
  const setSidebarOpen = useAppStore((state) => state.setSidebarOpen);
  const setRightSidebarOpen = useAppStore((state) => state.setRightSidebarOpen);
  const setNewSessionOverlayOpen = useAppStore((state) => state.setNewSessionOverlayOpen);

  return (
    <main className="main-panel relative">
      {isDraft ? (
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
              <div className="flex min-w-0 items-baseline gap-2 text-sm leading-5">
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

          <div className="relative min-h-0 flex-1 bg-neutral-50/45">
            <NewSessionOverlay />
          </div>
        </div>
      ) : (
        <>
          <MessageList sessionId={activeSessionId} />
          <div className="absolute bottom-0 left-0 right-0 z-10">
            <MessageComposer />
          </div>
          {newSessionOverlayOpen ? (
            <NewSessionOverlay
              onClose={() => {
                setNewSessionOverlayOpen(false);
              }}
            />
          ) : null}
        </>
      )}
    </main>
  );
}
