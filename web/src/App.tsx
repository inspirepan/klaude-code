import { useEffect } from "react";

import { MainPanel } from "./components/layout/MainPanel";
import { LeftSidebar } from "./components/sidebar/LeftSidebar";
import { RightSidebar } from "./components/sidebar/RightSidebar";
import { useAppStore } from "./stores/app-store";
import { useSessionStore } from "./stores/session-store";

const NARROW_BREAKPOINT = 768;

export default function App(): JSX.Element {
  const init = useSessionStore((state) => state.init);
  const activeSessionId = useSessionStore((state) => state.activeSessionId);
  const groups = useSessionStore((state) => state.groups);
  const draftWorkDir = useSessionStore((state) => state.draftWorkDir);
  const setDraftWorkDir = useSessionStore((state) => state.setDraftWorkDir);
  const sidebarOpen = useAppStore((state) => state.sidebarOpen);
  const rightSidebarOpen = useAppStore((state) => state.rightSidebarOpen);
  const setSidebarOpen = useAppStore((state) => state.setSidebarOpen);
  const setRightSidebarOpen = useAppStore((state) => state.setRightSidebarOpen);
  const setNewSessionOverlayOpen = useAppStore((state) => state.setNewSessionOverlayOpen);

  useEffect(() => {
    void init();
  }, [init]);

  // Sync session state on browser back/forward
  useEffect(() => {
    const handlePopState = () => {
      const match = window.location.pathname.match(/^\/session\/([a-f0-9]+)$/);
      if (match) {
        void useSessionStore.getState().selectSession(match[1]);
      } else {
        useAppStore.getState().setNewSessionOverlayOpen(false);
        useSessionStore.getState().selectDraft();
      }
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  // Auto-collapse sidebar when window becomes narrow
  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${NARROW_BREAKPOINT}px)`);
    const handleChange = (e: MediaQueryListEvent | MediaQueryList) => {
      if (e.matches) {
        setSidebarOpen(false);
        setRightSidebarOpen(false);
      }
    };
    handleChange(mq);
    mq.addEventListener("change", handleChange);
    return () => mq.removeEventListener("change", handleChange);
  }, [setRightSidebarOpen, setSidebarOpen]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || !event.shiftKey || event.key.toLowerCase() !== "o") {
        return;
      }
      event.preventDefault();
      const activeSession =
        activeSessionId === "draft"
          ? null
          : (groups
              .flatMap((group) => group.sessions)
              .find((session) => session.id === activeSessionId) ?? null);
      setDraftWorkDir(activeSession?.work_dir || draftWorkDir);
      setNewSessionOverlayOpen(activeSessionId !== "draft");
      window.dispatchEvent(new Event("klaude:draft-focus-input"));
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [activeSessionId, draftWorkDir, groups, setDraftWorkDir, setNewSessionOverlayOpen]);

  return (
    <div className="app-shell">
      {sidebarOpen ? <LeftSidebar /> : null}
      <MainPanel />
      {rightSidebarOpen ? <RightSidebar /> : null}
    </div>
  );
}
