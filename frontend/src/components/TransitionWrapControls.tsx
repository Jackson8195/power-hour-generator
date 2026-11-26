import { useEffect, useState } from "react";
import clsx from "clsx";
import { getTransitionAssets, type TransitionAssets, type TransitionWrap } from "../utils/api";

const SOUND_LABELS: Record<string, string> = {
  can: "BEER CAN",
  clink: "GLASS CLINK",
  pop: "BOTTLE POP",
  pour: "POUR",
  cheer: "CROWD CHEER",
  bell: "BOXING BELL",
};

interface Props {
  value: TransitionWrap;
  onChange: (next: TransitionWrap) => void;
}

/**
 * Extras for a hand-built transition: the corner 3·2·1 countdown over the end of the clip,
 * and an optional "DRINK!" ending (drink art + call word + sound cue) after it.
 */
export default function TransitionWrapControls({ value, onChange }: Props) {
  const [assets, setAssets] = useState<TransitionAssets | null>(null);

  useEffect(() => {
    getTransitionAssets().then(setAssets).catch(() => setAssets(null));
  }, []);

  const set = (patch: Partial<TransitionWrap>) => onChange({ ...value, ...patch });
  const labelClass = "font-mono text-sm uppercase tracking-[0.14em] text-phosphor-text/75";

  return (
    <div className="space-y-3 border border-phosphor/10 bg-crt-panel/70 p-3">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <label className={clsx(labelClass, "flex items-center gap-2")}>
          <input
            type="checkbox"
            checked={value.countdown}
            onChange={(e) => set({ countdown: e.target.checked })}
          />
          CORNER 3·2·1 COUNTDOWN
        </label>
        <label className={clsx(labelClass, "flex items-center gap-2")}>
          DRINK! ENDING
          <select
            value={value.drinkEnding}
            onChange={(e) => set({ drinkEnding: e.target.value })}
            className="retro-input px-2 py-1 font-mono text-sm"
          >
            <option value="">NONE</option>
            {(assets?.sounds ?? ["can", "clink", "pop", "pour", "cheer", "bell"]).map((sound) => (
              <option key={sound} value={sound}>
                {SOUND_LABELS[sound] ?? sound.toUpperCase()}
              </option>
            ))}
          </select>
        </label>
        {value.drinkEnding && (
          <label className={clsx(labelClass, "flex items-center gap-2")}>
            CALL
            <select
              value={value.drinkWord}
              onChange={(e) => set({ drinkWord: e.target.value })}
              className="retro-input px-2 py-1 font-mono text-sm"
            >
              {(assets?.words ?? ["DRINK!"]).map((word) => (
                <option key={word} value={word}>
                  {word}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {value.drinkEnding && assets && assets.art.length > 0 && (
        <div>
          <p className={labelClass}>ENDING ART</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => set({ drinkArt: "" })}
              className={clsx(
                "h-16 w-24 border font-mono text-xs uppercase tracking-[0.12em]",
                value.drinkArt === ""
                  ? "border-magenta/60 text-magenta-pale"
                  : "border-phosphor/14 text-phosphor-text/60"
              )}
            >
              SURPRISE ME
            </button>
            {assets.art.map((art) => (
              <button
                type="button"
                key={art.name}
                onClick={() => set({ drinkArt: art.name })}
                className={clsx(
                  "h-16 w-24 overflow-hidden border-2",
                  value.drinkArt === art.name ? "border-magenta" : "border-transparent opacity-70 hover:opacity-100"
                )}
                title={art.name}
              >
                <img src={art.url} alt={art.name} className="h-full w-full object-cover" />
              </button>
            ))}
          </div>
        </div>
      )}
      <p className="type-body">
        The countdown ticks over the last 3 seconds of your clip; the ending adds about 2 seconds.
      </p>
    </div>
  );
}
