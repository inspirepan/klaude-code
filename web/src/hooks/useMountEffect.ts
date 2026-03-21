import { useEffect } from "react";

/** Run an effect exactly once on mount (and optional cleanup on unmount). */
export function useMountEffect(effect: () => void | (() => void)) {
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(effect, []);
}
