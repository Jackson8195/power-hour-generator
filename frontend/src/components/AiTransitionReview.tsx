import { useCallback, useEffect, useRef, useState } from "react";
import { Plus, RefreshCcw, Scissors, Sparkles, Trash2, Type } from "lucide-react";
import Spinner from "./Spinner";
import clsx from "clsx";
import {
  addAiTransition,
  deleteAiTransition,
  generateAiTransitions,
  getAiTransitions,
  regenerateAiTransition,
  setAiTransitionText,
  trimAiTransition,
  type AiTransitionItem,
  type AiTransitionReview as ReviewState,
} from "../utils/api";
import AiTransitionTrim from "./AiTransitionTrim";

type Sources = "cards" | "youtube" | "both";

interface Props {
  projectId: number;
  /** The power hour's own prompt, shown as context (the AI always gets it too). */
  powerHourPrompt: string;
  transitionPrompt: string;
  onTransitionPromptChange: (value: string) => void;
  /** The call word for new transitions ("" = no text); each one can be changed after. */
  drinkText: string;
  onDrinkTextChange: (value: string) => void;
  count: number;
  sources: Sources;
  /** Reports how many transitions are ready and whether anything is still building. */
  onStatus?: (status: { ready: number; busy: boolean }) => void;
}

const MAX_TRANSITIONS = 8;

/**
 * Generate the AI transitions before building the power hour, watch each one, and trash /
 * regenerate / add individual ones until the set is right. Approving then keeps these.
 */
export default function AiTransitionReview({
  projectId,
  powerHourPrompt,
  transitionPrompt,
  onTransitionPromptChange,
  drinkText,
  onDrinkTextChange,
  count,
  sources,
  onStatus,
}: Props) {
  const [review, setReview] = useState<ReviewState | null>(null);
  const [error, setError] = useState("");
  const [requesting, setRequesting] = useState(false);
  const [trimming, setTrimming] = useState<number | null>(null);
  const [editingText, setEditingText] = useState<number | null>(null);
  const [textDraft, setTextDraft] = useState("");
  const statusRef = useRef(onStatus);
  statusRef.current = onStatus;

  const items = review?.transitions ?? [];
  const busy =
    requesting || (review?.state ?? "idle") !== "idle" || items.some((t) => t.status === "building");
  const ready = items.filter((t) => t.status === "ready").length;

  const load = useCallback(async () => {
    try {
      const next = await getAiTransitions(projectId);
      setReview(next);
      if (next.error) setError(next.error);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load transitions");
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  // Poll while anything is being planned or built.
  useEffect(() => {
    if (!busy) return;
    const interval = window.setInterval(load, 2500);
    return () => window.clearInterval(interval);
  }, [busy, load]);

  useEffect(() => {
    statusRef.current?.({ ready, busy });
  }, [ready, busy]);

  async function run(action: () => Promise<unknown>) {
    setRequesting(true);
    setError("");
    try {
      await action();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setRequesting(false);
    }
  }

  const words = drinkText.trim();
  const generateAll = () =>
    run(() => generateAiTransitions(projectId, { prompt: transitionPrompt, count, sources, drink_text: words }));
  const regenerate = (item: AiTransitionItem, kind?: "card" | "youtube") =>
    run(() => regenerateAiTransition(projectId, item.id, { prompt: transitionPrompt, kind }));
  const trash = (item: AiTransitionItem) => run(() => deleteAiTransition(projectId, item.id));
  const applyTrim = (item: AiTransitionItem, edit: { start: number; end: number; drink_text: string }) => {
    setTrimming(null);
    void run(() => trimAiTransition(projectId, item.id, edit));
  };
  const applyText = (item: AiTransitionItem) => {
    setEditingText(null);
    void run(() => setAiTransitionText(projectId, item.id, textDraft.trim()));
  };
  const add = (kind: "card" | "youtube") =>
    run(() => addAiTransition(projectId, { prompt: transitionPrompt, kind, drink_text: words }));

  const stateLabel =
    review?.state === "planning"
      ? "The AI is designing your transitions…"
      : review?.state === "building" || items.some((t) => t.status === "building")
        ? `Building… ${ready} of ${items.length} ready (art takes ~30s each, video moments longer)`
        : items.length
          ? `${ready} ready. Watch them; trim video moments to the exact part you want, change any text, trash or regenerate the rest.`
          : "Nothing generated yet. Approving without reviewing makes the AI create them during the build.";

  return (
    <div className="mt-4 space-y-4 border-t border-phosphor/14 pt-4">
      <div>
        <p className="font-mono text-xs uppercase tracking-[0.16em] text-phosphor-text/50">Power hour prompt (context)</p>
        <p className="mt-1 line-clamp-3 type-body">{powerHourPrompt}</p>
      </div>

      <label className="block">
        <span className="font-mono text-xs uppercase tracking-[0.16em] text-phosphor-text/70">Transition prompt</span>
        <textarea
          value={transitionPrompt}
          onChange={(e) => onTransitionPromptChange(e.target.value)}
          maxLength={1000}
          rows={3}
          placeholder="Optional direction, e.g. golden microphones and judges' desk vibes, Simon Cowell eye-rolls for the video moments, gold and red stage lighting."
          className="retro-input mt-1 w-full px-3 py-2 font-mono text-sm"
        />
      </label>

      <label className="block max-w-sm">
        <span className="font-mono text-xs uppercase tracking-[0.16em] text-phosphor-text/70">Drink text</span>
        <input
          value={drinkText}
          onChange={(e) => onDrinkTextChange(e.target.value)}
          maxLength={24}
          placeholder="Leave empty for no text"
          className="retro-input mt-1 w-full px-3 py-2 font-mono text-sm"
        />
        <span className="mt-1 block type-body text-phosphor-text/70">
          Shown at the end of each new transition. You can change it on any one below.
        </span>
      </label>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={generateAll}
          disabled={busy}
          className="crt-action retro-button-primary inline-flex items-center gap-2 px-4 py-2 font-retro text-lg tracking-[0.16em] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? <Spinner className="h-4 w-4" /> : <Sparkles className="h-4 w-4" />}
          <span className="crt-action__label" data-text={items.length ? "REDO ALL" : "GENERATE TRANSITIONS"}>
            {items.length ? "REDO ALL" : "GENERATE TRANSITIONS"}
          </span>
        </button>
        {items.length > 0 && items.length < MAX_TRANSITIONS && (
          <>
            <button
              type="button"
              onClick={() => add("card")}
              disabled={busy}
              className="retro-button-secondary inline-flex items-center gap-2 px-3 py-2 font-retro text-lg tracking-[0.14em] disabled:opacity-40"
            >
              <Plus className="h-3.5 w-3.5" /> ADD CARD
            </button>
            {sources !== "cards" && (
              <button
                type="button"
                onClick={() => add("youtube")}
                disabled={busy}
                className="retro-button-secondary inline-flex items-center gap-2 px-3 py-2 font-retro text-lg tracking-[0.14em] disabled:opacity-40"
              >
                <Plus className="h-3.5 w-3.5" /> ADD VIDEO MOMENT
              </button>
            )}
          </>
        )}
      </div>

      <p className="type-body">{stateLabel}</p>
      {error && <p className="font-mono text-sm text-red-400">{error}</p>}

      {items.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {items.map((item) => (
            <div
              key={item.id}
              className={clsx(
                "border border-phosphor/12 bg-crt-panel/80 p-2",
                trimming === item.id && "sm:col-span-2 xl:col-span-3"
              )}
            >
              {trimming === item.id && item.status === "ready" && item.source_url ? (
                <AiTransitionTrim
                  sourceUrl={item.source_url}
                  sourceSeconds={item.source_seconds}
                  waveform={item.waveform}
                  initialStart={item.trim_start}
                  initialEnd={item.trim_end}
                  drinkText={item.drink_text}
                  busy={busy}
                  onApply={(edit) => applyTrim(item, edit)}
                  onCancel={() => setTrimming(null)}
                />
              ) : (
              <div className="relative aspect-video bg-black">
                {item.status === "ready" && item.preview_url ? (
                  <video playsInline
                    key={item.preview_url}
                    src={item.preview_url}
                    controls
                    preload="metadata"
                    className="h-full w-full"
                  />
                ) : item.status === "error" ? (
                  <div className="flex h-full items-center justify-center p-3 text-center font-mono text-xs text-red-300">
                    FAILED: {item.error_message || "unknown error"}
                  </div>
                ) : (
                  <div className="flex h-full items-center justify-center gap-2 type-body">
                    <Spinner className="h-4 w-4" /> BUILDING…
                  </div>
                )}
              </div>
              )}
              <div className="mt-2 flex items-center gap-2">
                <span
                  className={clsx(
                    "retro-chip shrink-0",
                    item.kind === "youtube" ? "retro-chip--info" : "retro-chip--dim"
                  )}
                >
                  {item.kind === "youtube" ? "VIDEO" : "CARD"}
                </span>
                <p className="min-w-0 truncate font-mono text-sm text-magenta-text" title={item.label}>
                  {item.label}
                </p>
                {item.status === "ready" && item.duration > 0 && (
                  <span className="ml-auto shrink-0 type-body">{item.duration.toFixed(1)}s</span>
                )}
              </div>
              {item.status === "ready" && trimming !== item.id && (
                editingText === item.id ? (
                  <div className="mt-2 flex gap-2">
                    <input
                      autoFocus
                      value={textDraft}
                      onChange={(e) => setTextDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") applyText(item);
                        if (e.key === "Escape") setEditingText(null);
                      }}
                      maxLength={24}
                      placeholder="Empty = no text"
                      aria-label="Drink text"
                      className="retro-input min-w-0 flex-1 px-2 py-1 font-mono text-sm"
                    />
                    <button
                      type="button"
                      onClick={() => applyText(item)}
                      disabled={busy}
                      className="border border-phosphor/50 px-2 py-1 font-mono text-xs uppercase tracking-[0.12em] text-phosphor disabled:opacity-40"
                    >
                      SET
                    </button>
                  </div>
                ) : (
                  <p className="mt-1 font-mono text-sm text-phosphor-text/85">
                    Ends with: <span className="text-magenta-text">{item.drink_text ? `"${item.drink_text}"` : "no text"}</span>
                  </p>
                )
              )}
              {item.status === "ready" && item.error_message && (
                <p className="mt-1 font-mono text-xs text-red-300">{item.error_message}</p>
              )}
              <div className="mt-2 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => regenerate(item)}
                  disabled={busy}
                  className="inline-flex items-center gap-1 border border-phosphor/20 px-2 py-1 font-mono text-xs uppercase tracking-[0.12em] text-phosphor-text/80 hover:border-phosphor/50 disabled:opacity-40"
                >
                  <RefreshCcw className="h-3 w-3" /> NEW ONE
                </button>
                {item.kind === "youtube" && item.source_url && item.status === "ready" && trimming !== item.id && (
                  <button
                    type="button"
                    onClick={() => setTrimming(item.id)}
                    disabled={busy}
                    className="inline-flex items-center gap-1 border border-phosphor/20 px-2 py-1 font-mono text-xs uppercase tracking-[0.12em] text-phosphor-text/80 hover:border-phosphor/50 disabled:opacity-40"
                  >
                    <Scissors className="h-3 w-3" /> TRIM
                  </button>
                )}
                {item.status === "ready" && trimming !== item.id && editingText !== item.id &&
                  (item.kind === "card" || item.source_url) && (
                  <button
                    type="button"
                    onClick={() => {
                      setTextDraft(item.drink_text);
                      setEditingText(item.id);
                    }}
                    disabled={busy}
                    className="inline-flex items-center gap-1 border border-phosphor/20 px-2 py-1 font-mono text-xs uppercase tracking-[0.12em] text-phosphor-text/80 hover:border-phosphor/50 disabled:opacity-40"
                  >
                    <Type className="h-3 w-3" /> TEXT
                  </button>
                )}
                {sources !== "cards" && (
                  <button
                    type="button"
                    onClick={() => regenerate(item, item.kind === "youtube" ? "card" : "youtube")}
                    disabled={busy}
                    className="border border-phosphor/20 px-2 py-1 font-mono text-xs uppercase tracking-[0.12em] text-phosphor-text/80 hover:border-phosphor/50 disabled:opacity-40"
                  >
                    {item.kind === "youtube" ? "MAKE IT A CARD" : "MAKE IT A VIDEO"}
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => trash(item)}
                  disabled={busy}
                  className="ml-auto inline-flex items-center gap-1 border border-red-400/30 px-2 py-1 font-mono text-xs uppercase tracking-[0.12em] text-red-300 hover:border-red-400/60 disabled:opacity-40"
                >
                  <Trash2 className="h-3 w-3" /> TRASH
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
