import { create } from "zustand";

interface AppStoreState {
  sidebarOpen: boolean;
  rightSidebarOpen: boolean;
  newSessionOverlayOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
  setRightSidebarOpen: (open: boolean) => void;
  setNewSessionOverlayOpen: (open: boolean) => void;
  toggleSidebar: () => void;
  toggleRightSidebar: () => void;
}

export const useAppStore = create<AppStoreState>((set) => ({
  sidebarOpen: true,
  rightSidebarOpen: true,
  newSessionOverlayOpen: false,
  setSidebarOpen: (open: boolean) => set({ sidebarOpen: open }),
  setRightSidebarOpen: (open: boolean) => set({ rightSidebarOpen: open }),
  setNewSessionOverlayOpen: (open: boolean) => set({ newSessionOverlayOpen: open }),
  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
  toggleRightSidebar: () => set((state) => ({ rightSidebarOpen: !state.rightSidebarOpen })),
}));
