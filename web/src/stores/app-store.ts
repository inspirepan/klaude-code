import { create } from "zustand";

interface AppStoreState {
  sidebarOpen: boolean;
  newSessionOverlayOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
  setNewSessionOverlayOpen: (open: boolean) => void;
  toggleSidebar: () => void;
}

export const useAppStore = create<AppStoreState>((set) => ({
  sidebarOpen: true,
  newSessionOverlayOpen: false,
  setSidebarOpen: (open: boolean) => set({ sidebarOpen: open }),
  setNewSessionOverlayOpen: (open: boolean) => set({ newSessionOverlayOpen: open }),
  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
}));
