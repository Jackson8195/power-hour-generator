import { useEffect, useMemo, useRef, useState } from "react";
import clsx from "clsx";
import type { ClipAnalysis } from "../utils/types";
import { formatTime } from "../utils/time";

export type DraftRange = { start: number; end: number };

/**
 * Equalizer-style waveform with recommended regions and a draggable selection window.
 * Used for clip review and for re-trimming AI transition moments.
 */
export default function WaveformRangeEditor({
  waveform,
  highlights,
  duration,
  selection,
  onSeek,
  onChange,
  playhead,
  minSelection = 0.5,
  maxSelection,
  precise = false,
  title = "WAVEFORM RANGE",
  hint = "Drag either edge of the pink window to trim.",
}: {
  waveform: number[];
  highlights: ClipAnalysis["highlights"];
  duration: number;
  selection: DraftRange;
  onSeek?: (time: number) => void;
  playhead?: number | null;
  onChange: (range: DraftRange) => void;
  /** Shortest / longest selection the handles allow (seconds). */
  minSelection?: number;
  maxSelection?: number;
  /** Show tenths of a second (for short transition moments). */
  precise?: boolean;
  title?: string;
  hint?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const dragStateRef = useRef<"start" | "end" | null>(null);
  const [boxWidth, setBoxWidth] = useState(0);

  useEffect(() => {
    const box = containerRef.current;
    if (!box) return;
    const observer = new ResizeObserver(([entry]) => setBoxWidth(entry.contentRect.width));
    observer.observe(box);
    return () => observer.disconnect();
  }, []);

  const bars = useMemo(() => {
    const source = waveform.length ? waveform : new Array(80).fill(0.15);
    const target = Math.max(24, Math.floor((boxWidth || 640) / 4));
    if (source.length <= target) return source;
    // Keep each bucket's peak so short loud moments stay visible.
    const out: number[] = [];
    for (let i = 0; i < target; i++) {
      const from = Math.floor((i * source.length) / target);
      const to = Math.max(from + 1, Math.floor(((i + 1) * source.length) / target));
      out.push(Math.max(...source.slice(from, to)));
    }
    return out;
  }, [waveform, boxWidth]);

  useEffect(() => {
    function handlePointerMove(event: PointerEvent) {
      if (!dragStateRef.current || !containerRef.current || !duration) return;
      const rect = containerRef.current.getBoundingClientRect();
      const ratio = Math.max(0, Math.min((event.clientX - rect.left) / rect.width, 1));
      const nextTime = ratio * duration;

      if (dragStateRef.current === "start") {
        const floor = maxSelection ? selection.end - maxSelection : 0;
        onChange({
          start: Math.max(floor, Math.min(nextTime, Math.max(selection.end - minSelection, 0))),
          end: selection.end,
        });
      } else {
        const ceiling = maxSelection ? selection.start + maxSelection : duration;
        onChange({
          start: selection.start,
          end: Math.min(ceiling, Math.max(nextTime, selection.start + minSelection)),
        });
      }
    }

    function stopDragging() {
      dragStateRef.current = null;
    }

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", stopDragging);

    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", stopDragging);
    };
  }, [duration, onChange, selection.end, selection.start, minSelection, maxSelection]);

  function handleWaveformClick(e: React.MouseEvent<HTMLDivElement>) {
    if (!duration || !onSeek) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const ratio = (e.clientX - rect.left) / rect.width;
    onSeek(Math.max(0, Math.min(ratio * duration, duration)));
  }

  return (
    <div className="border border-phosphor/12 bg-gradient-to-b from-[#08131b] to-[#050c12] px-3 py-5">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <p className="font-retro text-lg tracking-[0.18em] text-zinc-200">{title}</p>
          <p className="type-body">
            {hint}
          </p>
        </div>
        <div className="retro-chip retro-chip--pink text-base">
          {formatTime(Math.max(selection.end - selection.start, 0), precise)}
        </div>
      </div>

      {/* Bar-strip wrapper: containerRef and every overlay share this exact box so
          percentage-based positions line up pixel-for-pixel with the rendered bars. */}
      <div
        ref={containerRef}
        className={clsx("relative h-28", onSeek && "cursor-pointer")}
        onClick={handleWaveformClick}
        title={onSeek ? "Click to seek video" : undefined}
      >
        <div className="pointer-events-none absolute inset-0">
          {selection.end > selection.start && (
            <div
              className="absolute inset-y-0 border border-magenta-soft/75 bg-magenta/12"
              style={{
                left: `${duration ? (selection.start / duration) * 100 : 0}%`,
                width: `${duration ? ((selection.end - selection.start) / duration) * 100 : 0}%`,
              }}
            />
          )}
        </div>

        <div className="absolute inset-0">
          {highlights.map((highlight) => (
            <div
              key={`${highlight.start}-${highlight.end}`}
              className="absolute inset-y-0 bg-phosphor/10 transition-colors hover:bg-phosphor/20"
              style={{
                left: `${duration ? (highlight.start / duration) * 100 : 0}%`,
                width: `${duration ? ((highlight.end - highlight.start) / duration) * 100 : 0}%`,
              }}
              title={`${highlight.label} — click to play from ${formatTime(highlight.start)}`}
              onClick={(e) => {
                e.stopPropagation();
                onSeek?.(highlight.start);
              }}
            />
          ))}
        </div>

        <div className="pointer-events-none absolute inset-0 flex items-end gap-px sm:gap-[2px]">
          {bars.map((bar, index) => (
            <div
              key={`${index}-${bar}`}
              className="flex-1 bg-phosphor-text/75"
              style={{ height: `${Math.max(bar * 100, 8)}%` }}
            />
          ))}
        </div>

        {duration > 0 && playhead != null ? (
          <div className="waveform-playhead" style={{ left: `${Math.min(100, (playhead / duration) * 100)}%` }} />
        ) : null}

        {duration > 0 && selection.end > selection.start ? (
          <>
            <button
              type="button"
              onPointerDown={(event) => {
                event.stopPropagation();
                dragStateRef.current = "start";
              }}
              className="group absolute inset-y-0 z-10 flex w-11 -translate-x-1/2 cursor-ew-resize touch-none justify-center"
              style={{ left: `${(selection.start / duration) * 100}%` }}
              aria-label="Drag selection start"
            >
              <span className="h-full w-3.5 border border-magenta-pale/70 bg-magenta-soft shadow-[0_0_18px_rgba(255,119,194,0.55)] group-active:w-4" />
            </button>
            <button
              type="button"
              onPointerDown={(event) => {
                event.stopPropagation();
                dragStateRef.current = "end";
              }}
              className="group absolute inset-y-0 z-10 flex w-11 -translate-x-1/2 cursor-ew-resize touch-none justify-center"
              style={{ left: `${(selection.end / duration) * 100}%` }}
              aria-label="Drag selection end"
            >
              <span className="h-full w-3.5 border border-magenta-pale/70 bg-magenta-soft shadow-[0_0_18px_rgba(255,119,194,0.55)] group-active:w-4" />
            </button>
          </>
        ) : null}
      </div>

      <div className="mt-4 flex items-center justify-between type-body">
        <span>0:00</span>
        <span>{formatTime(duration)}</span>
      </div>
    </div>
  );
}
