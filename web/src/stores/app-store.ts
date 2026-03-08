import { create } from "zustand";

interface AppStoreState {
  sidebarOpen: boolean;
  rightSidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
  setRightSidebarOpen: (open: boolean) => void;
  toggleSidebar: () => void;
  toggleRightSidebar: () => void;
}

export const useAppStore = create<AppStoreState>((set) => ({
  sidebarOpen: true,
  rightSidebarOpen: true,
  setSidebarOpen: (open: boolean) => set({ sidebarOpen: open }),
  setRightSidebarOpen: (open: boolean) => set({ rightSidebarOpen: open }),
  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
  toggleRightSidebar: () => set((state) => ({ rightSidebarOpen: !state.rightSidebarOpen })),
}));
