import { useEffect, useRef, useState } from "react";
import { Play, Scissors, X } from "lucide-react";
import WaveformRangeEditor, { type DraftRange } from "./WaveformRangeEditor";
import { formatTime } from "../utils/time";

const MIN_SECONDS = 1;
const MAX_SECONDS = 20; // transition_fx.MAX_VIDEO_CLIP_SECONDS
const TAIL_SECONDS = 1.8; // the held last frame with the DRINK text (transition_fx.VIDEO_TAIL_SECONDS)

interface Props {
  sourceUrl: string;
  /** Length of the whole source and its waveform (from the build). */
  sourceSeconds: number;
  waveform: number[];
  initialStart: number;
  initialEnd: number;
  drinkText: string;
  busy: boolean;
  onApply: (edit: { start: number; end: number; drink_text: string }) => void;
  onCancel: () => void;
}

/**
 * Re-trim an AI video moment on its WHOLE source: watch any part of it, drag the window on the
 * waveform (or set in/out from the playhead), set the DRINK text, then rebuild.
 */
export default function AiTransitionTrim({
  sourceUrl,
  sourceSeconds,
  waveform,
  initialStart,
  initialEnd,
  drinkText,
  busy,
  onApply,
  onCancel,
}: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [length, setLength] = useState(sourceSeconds || 0);
  const [range, setRange] = useState<DraftRange>({ start: initialStart, end: initialEnd || initialStart + 4 });
  const [text, setText] = useState(drinkText);
  const [playhead, setPlayhead] = useState<number | null>(null);
  const stopAt = useRef<number | null>(null);

  // Follow the video smoothly while it plays (timeupdate alone is ~4 Hz).
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    let frame = 0;
    const tick = () => {
      setPlayhead(video.currentTime);
      if (stopAt.current !== null && video.currentTime >= stopAt.current) {
        video.pause();
        stopAt.current = null;
      }
      if (!video.paused && !video.ended) frame = window.requestAnimationFrame(tick);
    };
    const start = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(tick);
    };
    const update = () => setPlayhead(video.currentTime);
    video.addEventListener("play", start);
    video.addEventListener("seeked", update);
    return () => {
      window.cancelAnimationFrame(frame);
      video.removeEventListener("play", start);
      video.removeEventListener("seeked", update);
    };
  }, []);

  const seek = (t: number) => {
    const v = videoRef.current;
    if (v) {
      v.currentTime = t;
      void v.play();
    }
  };
  const now = () => videoRef.current?.currentTime ?? 0;

  // On a long source the window is a sliver, so the playhead is the real tool: START HERE moves
  // the whole window to the playhead (same length); END HERE ends it there, keeping the start
  // when that still makes a 1-20s cut, otherwise sliding the window back.
  const setStartHere = () => {
    const t = now();
    setRange((r) => {
      const keep = Math.max(MIN_SECONDS, Math.min(MAX_SECONDS, r.end - r.start));
      const end = length ? Math.min(length, t + keep) : t + keep;
      return { start: Math.max(0, Math.min(t, end - MIN_SECONDS)), end };
    });
  };
  const setEndHere = () => {
    const t = now();
    setRange((r) => {
      const span = t - r.start;
      if (span >= MIN_SECONDS && span <= MAX_SECONDS) return { start: r.start, end: t };
      const keep = Math.max(MIN_SECONDS, Math.min(MAX_SECONDS, r.end - r.start));
      return { start: Math.max(0, t - keep), end: Math.max(t, MIN_SECONDS) };
    });
  };
  const playSelection = () => {
    const v = videoRef.current;
    if (!v) return;
    v.currentTime = range.start;
    stopAt.current = range.end;
    void v.play();
  };

  const clip = Math.max(0, range.end - range.start);
  const valid = clip >= MIN_SECONDS && clip <= MAX_SECONDS + 0.05;
  const small =
    "inline-flex items-center gap-1 border border-phosphor/20 px-2 py-1 font-mono text-xs uppercase tracking-[0.12em] text-phosphor-text/85 hover:border-phosphor/50 disabled:opacity-40";

  return (
    <div className="space-y-3">
      <video
        playsInline
        ref={videoRef}
        src={sourceUrl}
        controls
        preload="auto"
        className="aspect-video w-full bg-black"
        onLoadedMetadata={(e) => setLength(e.currentTarget.duration || sourceSeconds || 0)}
      />

      <WaveformRangeEditor
        waveform={waveform}
        highlights={[]}
        duration={length}
        selection={range}
        onSeek={seek}
        onChange={setRange}
        playhead={playhead}
        minSelection={MIN_SECONDS}
        maxSelection={MAX_SECONDS}
        precise
        title="WHOLE VIDEO"
        hint={`Tap the waveform to jump anywhere and watch, then START HERE / END HERE. Or drag the pink window's edges (${MIN_SECONDS}-${MAX_SECONDS}s).`}
      />

      <div className="flex flex-wrap gap-2">
        <button type="button" className={small} disabled={!length || busy} onClick={setStartHere}>
          START HERE
        </button>
        <button type="button" className={small} disabled={!length || busy} onClick={setEndHere}>
          END HERE
        </button>
        <button type="button" className={small} disabled={!length} onClick={playSelection}>
          <Play className="h-3 w-3" /> PLAY CUT
        </button>
      </div>

      <label className="block">
        <span className="font-mono text-xs uppercase tracking-[0.16em] text-phosphor-text/80">Drink text</span>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={24}
          placeholder="Leave empty for no text"
          className="retro-input mt-1 w-full px-3 py-2 font-mono text-sm"
        />
      </label>

      <p className="type-body">
        {formatTime(range.start, true)} to {formatTime(range.end, true)}: clip {clip.toFixed(1)}s +{" "}
        {TAIL_SECONDS}s {text.trim() ? `"${text.trim()}" over the last frame` : "held last frame"}. The countdown runs
        over the clip&apos;s last 3s.
      </p>

      <div className="flex gap-2">
        <button
          type="button"
          disabled={!length || busy || !valid}
          onClick={() =>
            onApply({
              start: Math.round(range.start * 10) / 10,
              end: Math.round(range.end * 10) / 10,
              drink_text: text.trim(),
            })
          }
          className="inline-flex items-center gap-1 border border-phosphor/50 px-3 py-2 font-mono text-xs uppercase tracking-[0.12em] text-phosphor hover:border-phosphor disabled:opacity-40"
        >
          <Scissors className="h-3 w-3" /> APPLY
        </button>
        <button type="button" className={`${small} px-3 py-2`} onClick={onCancel}>
          <X className="h-3 w-3" /> CANCEL
        </button>
      </div>
    </div>
  );
}
