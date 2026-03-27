import { useEffect, useRef } from "react";

/**
 * Polls a callback at a given interval. Automatically cleans up on unmount.
 * Pass `null` as the interval to pause polling.
 */
export function usePolling(
  callback: () => void | Promise<void>,
  intervalMs: number | null
) {
  const savedCallback = useRef(callback);

  useEffect(() => {
    savedCallback.current = callback;
  }, [callback]);

  useEffect(() => {
    if (intervalMs === null) return;

    const tick = () => {
      savedCallback.current();
    };

    const id = setInterval(tick, intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
}
