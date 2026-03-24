import { useEffect, useRef, useState } from "react";

import { useMountEffect } from "./useMountEffect";

const DEFAULT_SIDEBAR_WIDTH = 340;
const SIDEBAR_WIDTH_STORAGE_KEY = "klaude:left-sidebar:width";

function clampSidebarWidth(width: number): number {
  const minWidth = 256;
  const hardMaxWidth = 512;
  const rightSidebarWidth =
    document.querySelector<HTMLElement>('[data-sidebar="right"]')?.offsetWidth ?? 0;
  const minMainWidth = 320;
  const availableMaxWidth = window.innerWidth - rightSidebarWidth - minMainWidth;
  const maxWidth = Math.max(minWidth, Math.min(hardMaxWidth, availableMaxWidth));
  return Math.min(Math.max(width, minWidth), maxWidth);
}

function readStoredSidebarWidth(): number | null {
  const raw = window.localStorage.getItem(SIDEBAR_WIDTH_STORAGE_KEY);
  if (raw === null) return null;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

interface SidebarResize {
  sidebarWidth: number;
  isResizing: boolean;
  handleResizePointerDown: (event: React.PointerEvent) => void;
}

export function useSidebarResize(): SidebarResize {
  const [sidebarWidth, setSidebarWidth] = useState(
    () => readStoredSidebarWidth() ?? DEFAULT_SIDEBAR_WIDTH,
  );
  const [isResizing, setIsResizing] = useState(false);
  const cleanupRef = useRef<(() => void) | null>(null);

  useMountEffect(() => {
    const syncSidebarWidth = (): void => {
      setSidebarWidth((current) => {
        const next = clampSidebarWidth(current);
        return next === current ? current : next;
      });
    };

    syncSidebarWidth();
    window.addEventListener("resize", syncSidebarWidth);
    return () => {
      window.removeEventListener("resize", syncSidebarWidth);
      cleanupRef.current?.();
      cleanupRef.current = null;
    };
  });

  useEffect(() => {
    window.localStorage.setItem(SIDEBAR_WIDTH_STORAGE_KEY, String(sidebarWidth));
  }, [sidebarWidth]);

  const handleResizePointerDown = (event: React.PointerEvent): void => {
    event.preventDefault();
    setIsResizing(true);
    const startX = event.clientX;
    const startWidth = sidebarWidth;

    const onPointerMove = (moveEvent: PointerEvent): void => {
      setSidebarWidth(clampSidebarWidth(startWidth + (moveEvent.clientX - startX)));
    };
    const onPointerUp = (): void => {
      setIsResizing(false);
      cleanup();
      cleanupRef.current = null;
    };
    const cleanup = (): void => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
    };

    cleanupRef.current?.();
    cleanupRef.current = cleanup;
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
  };

  return { sidebarWidth, isResizing, handleResizePointerDown };
}
