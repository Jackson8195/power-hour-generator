import { useState, useCallback, useRef } from "react";
import type { RenderProgress } from "../utils/types";
import { startRender, connectRenderWs } from "../utils/api";

/**
 * Hook for managing a render job with real-time WebSocket progress.
 */
export function useRenderProgress() {
  const [progress, setProgress] = useState<RenderProgress | null>(null);
  const [isRendering, setIsRendering] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  const start = useCallback(
    async (
      projectId: number,
      options?: {
        resolution?: string;
        transition_type?: string;
        include_countdown?: boolean;
      }
    ) => {
      setIsRendering(true);

      try {
        const { render_id } = await startRender(projectId, options);

        // Close any existing WebSocket
        wsRef.current?.close();

        const ws = connectRenderWs(render_id, (data) => {
          setProgress(data);
          if (data.status === "complete" || data.status === "error") {
            setIsRendering(false);
            ws.close();
            wsRef.current = null;
          }
        });

        wsRef.current = ws;
      } catch (err) {
        setIsRendering(false);
        throw err;
      }
    },
    []
  );

  const reset = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
    setProgress(null);
    setIsRendering(false);
  }, []);

  return { progress, isRendering, start, reset };
}
