import { useEffect } from "react";

import { MainPanel } from "./components/layout/MainPanel";
import { LeftSidebar } from "./components/sidebar/LeftSidebar";
import { TooltipProvider } from "./components/ui/tooltip";
import { I18nProvider } from "./i18n/I18nProvider";
import { useMountEffect } from "@/hooks/useMountEffect";
import { useAppStore } from "./stores/app-store";
import { useSessionStore } from "./stores/session-store";

const NARROW_BREAKPOINT = 768;

export default function App(): JSX.Element {
  const init = useSessionStore((state) => state.init);
  const activeSessionId = useSessionStore((state) => state.activeSessionId);
  const setDraftWorkDir = useSessionStore((state) => state.setDraftWorkDir);
  const setSidebarOpen = useAppStore((state) => state.setSidebarOpen);
  const setNewSessionOverlayOpen = useAppStore((state) => state.setNewSessionOverlayOpen);
  const toggleSidebar = useAppStore((state) => state.toggleSidebar);

  useMountEffect(() => {
    void init();
  });

  // Sync session state on browser back/forward
  useMountEffect(() => {
    const handlePopState = () => {
      const match = window.location.pathname.match(
        /^\/session\/([a-f0-9]+)(?:\/agent\/[a-f0-9]+)?$/,
      );
      if (match) {
        void useSessionStore.getState().selectSession(match[1]);
      } else {
        useAppStore.getState().setNewSessionOverlayOpen(false);
        useSessionStore.getState().selectDraft();
      }
    };
    window.addEventListener("popstate", handlePopState);
    return () => { window.removeEventListener("popstate", handlePopState); };
  });

  // Auto-collapse sidebar when window becomes narrow
  useMountEffect(() => {
    const mq = window.matchMedia(`(max-width: ${NARROW_BREAKPOINT}px)`);
    const handleChange = (e: MediaQueryListEvent | MediaQueryList) => {
      if (e.matches) {
        setSidebarOpen(false);
      }
    };
    handleChange(mq);
    mq.addEventListener("change", handleChange);
    return () => { mq.removeEventListener("change", handleChange); };
  });

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey)) {
        return;
      }

      const key = event.key.toLowerCase();

      if (key === "b" && !event.shiftKey) {
        event.preventDefault();
        toggleSidebar();
        return;
      }

      if (!event.shiftKey || key !== "o") {
        return;
      }

      event.preventDefault();
      setDraftWorkDir("");
      setNewSessionOverlayOpen(activeSessionId !== "draft");
      window.dispatchEvent(new Event("klaude:draft-focus-input"));
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [activeSessionId, setDraftWorkDir, setNewSessionOverlayOpen, toggleSidebar]);

  return (
    <I18nProvider>
      <TooltipProvider delayDuration={150}>
        <div className="app-shell">
          <LeftSidebar />
          <MainPanel />
        </div>
      </TooltipProvider>
    </I18nProvider>
  );
}
