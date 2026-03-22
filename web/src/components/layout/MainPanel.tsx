import { PanelLeftOpen } from "lucide-react";
import { useRef } from "react";
import { useMountEffect } from "@/hooks/useMountEffect";
import { useAppStore } from "../../stores/app-store";
import { useSessionStore } from "../../stores/session-store";
import { MessageComposer } from "../input/MessageComposer";
import { NewSessionOverlay } from "../input/NewSessionOverlay";
import { MessageList } from "../messages/MessageList";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";

export function MainPanel(): JSX.Element {
  const activeSessionId = useSessionStore((state) => state.activeSessionId);
  const isDraft = activeSessionId === "draft";
  const sidebarOpen = useAppStore((state) => state.sidebarOpen);
  const newSessionOverlayOpen = useAppStore((state) => state.newSessionOverlayOpen);
  const setSidebarOpen = useAppStore((state) => state.setSidebarOpen);
  const setNewSessionOverlayOpen = useAppStore((state) => state.setNewSessionOverlayOpen);
  const mainRef = useRef<HTMLElement>(null);
  const composerRef = useRef<HTMLDivElement>(null);

  useMountEffect(() => {
    const el = composerRef.current;
    const root = mainRef.current;
    if (!el || !root) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) {
        root.style.setProperty("--composer-h", `${entry.contentRect.height}px`);
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  });

  return (
    <main ref={mainRef} className="main-panel relative">
      {isDraft ? (
        <div className="relative min-h-0 flex-1 bg-surface/45">
          {!sidebarOpen ? (
            <div className="absolute left-4 top-3 z-30 sm:left-6">
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    className="inline-flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg text-neutral-500 transition-colors hover:bg-muted hover:text-neutral-700"
                    onClick={() => {
                      setSidebarOpen(true);
                    }}
                    aria-label="Expand sidebar"
                  >
                    <PanelLeftOpen className="h-4 w-4" />
                  </button>
                </TooltipTrigger>
                <TooltipContent className="flex items-center gap-1.5">
                  <span>Expand sidebar</span>
                  <span className="inline-flex items-center text-neutral-500" aria-hidden="true">
                    <span className="inline-flex whitespace-pre text-sm leading-none">
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
            </div>
          ) : null}
          <NewSessionOverlay showBackdrop={false} />
        </div>
      ) : (
        <>
          <MessageList sessionId={activeSessionId} />
          <div ref={composerRef} className="absolute bottom-0 left-0 right-0 z-30">
            <MessageComposer key={activeSessionId} />
          </div>
          {newSessionOverlayOpen ? (
            <NewSessionOverlay
              showBackdrop
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
