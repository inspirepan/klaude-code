import { useEffect, useRef, useState } from "react";

const MIN_INTERVAL_MS = 80;

/**
 * Throttle streaming content updates using requestAnimationFrame
 * with a minimum interval, delivering small frequent chunks instead
 * of large infrequent batches.
 */
export function useStreamThrottle(content: string, isStreaming: boolean): string {
  const [display, setDisplay] = useState(content);
  const pendingRef = useRef(content);
  const lastUpdateRef = useRef(0);
  const rafRef = useRef(0);

  useEffect(() => {
    pendingRef.current = content;
  }, [content]);

  useEffect(() => {
    if (!isStreaming) {
      return;
    }

    const tick = () => {
      const now = performance.now();
      if (now - lastUpdateRef.current >= MIN_INTERVAL_MS) {
        setDisplay((current) => (current === pendingRef.current ? current : pendingRef.current));
        lastUpdateRef.current = now;
      }
      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(rafRef.current);
    };
  }, [isStreaming]);

  return isStreaming ? display : content;
}
