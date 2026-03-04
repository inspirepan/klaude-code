import { useEffect } from "react";

import { MainPanel } from "./components/layout/MainPanel";
import { LeftSidebar } from "./components/sidebar/LeftSidebar";
import { useAppStore } from "./stores/app-store";
import { useSessionStore } from "./stores/session-store";

const NARROW_BREAKPOINT = 768;

export default function App(): JSX.Element {
  const init = useSessionStore((state) => state.init);
  const sidebarOpen = useAppStore((state) => state.sidebarOpen);
  const setSidebarOpen = useAppStore((state) => state.setSidebarOpen);

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
      if (e.matches) setSidebarOpen(false);
    };
    handleChange(mq);
    mq.addEventListener("change", handleChange);
    return () => mq.removeEventListener("change", handleChange);
  }, [setSidebarOpen]);

  return (
    <div className="app-shell">
      {sidebarOpen ? <LeftSidebar /> : null}
      <MainPanel />
    </div>
  );
}
