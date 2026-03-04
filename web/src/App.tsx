import { useEffect } from "react";

import { MainPanel } from "./components/layout/MainPanel";
import { LeftSidebar } from "./components/sidebar/LeftSidebar";
import { useAppStore } from "./stores/app-store";
import { useSessionStore } from "./stores/session-store";

export default function App(): JSX.Element {
  const init = useSessionStore((state) => state.init);
  const sidebarOpen = useAppStore((state) => state.sidebarOpen);

  useEffect(() => {
    void init();
  }, [init]);

  return (
    <div className="app-shell">
      {sidebarOpen ? <LeftSidebar /> : null}
      <MainPanel />
    </div>
  );
}
