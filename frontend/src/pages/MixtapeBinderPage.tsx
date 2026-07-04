import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import clsx from "clsx";
import { Film, PlayCircle, FolderOpen, Trash2, X } from "lucide-react";
import type { RenderLibraryEntry } from "../utils/types";
import { listRenderedVideos, cancelRender } from "../utils/api";
import CrtStaticText from "../components/CrtStaticText";
import BackButton from "../components/BackButton";

const ITEMS_PER_PAGE = 4;
const LAST_RENDER_STORAGE_KEY = "power-hour-last-mixtape-render";
const DISC_DROP_DURATION_MS = 2400;

const CD_GRADIENT = [
  "radial-gradient(circle at 30% 25%, rgba(255,255,255,0.65) 0%, rgba(255,255,255,0.05) 28%, transparent 48%)",
  "radial-gradient(circle at 50% 50%, rgba(210,210,225,0.5) 0%, rgba(170,170,190,0.15) 45%, transparent 68%)",
  "conic-gradient(from 200deg, #adadb8, #cfc060, #e085b0, #85a8e0, #85e0b8, #b885e0, #e09085, #adadb8, #cfc060, #adadb8)",
].join(", ");

function splitName(name: string): [string, string | null] {
  if (name.length <= 9) return [name, null];
  const mid = name.lastIndexOf(" ", 9);
  if (mid <= 0) return [name.slice(0, 8) + "…", null];
  return [name.slice(0, mid), name.slice(mid + 1)];
}

export default function MixtapeBinderPage() {
  const navigate = useNavigate();
  const [renders, setRenders] = useState<RenderLibraryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);
  const [selectedRenderId, setSelectedRenderId] = useState<number | null>(null);
  const [viewerRenderId, setViewerRenderId] = useState<number | null>(null);
  const [animatingRenderId, setAnimatingRenderId] = useState<number | null>(null);
  const [viewerStage, setViewerStage] = useState<"loading" | "playing">("loading");

  useEffect(() => {
    listRenderedVideos()
      .then((data) => {
        setRenders(data);
        const storedRenderId = Number(window.localStorage.getItem(LAST_RENDER_STORAGE_KEY) || "");
        const initialRender = data.find((render) => render.render_id === storedRenderId) ?? data[0] ?? null;
        if (!initialRender) return;
        setSelectedRenderId(initialRender.render_id);
        const initialIndex = data.findIndex((render) => render.render_id === initialRender.render_id);
        setPage(initialIndex >= 0 ? Math.floor(initialIndex / ITEMS_PER_PAGE) : 0);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const totalPages = Math.max(1, Math.ceil(renders.length / ITEMS_PER_PAGE));
  const pageItems = renders.slice(page * ITEMS_PER_PAGE, (page + 1) * ITEMS_PER_PAGE);
  const selectedRender = useMemo(
    () => renders.find((render) => render.render_id === selectedRenderId) ?? renders[0] ?? null,
    [renders, selectedRenderId]
  );
  const viewerRender = useMemo(
    () => renders.find((render) => render.render_id === viewerRenderId) ?? null,
    [renders, viewerRenderId]
  );
  const [viewerLine1, viewerLine2] = splitName(viewerRender?.project_name ?? "");

  function startPlayback(renderId: number, renderOverride?: RenderLibraryEntry) {
    if (animatingRenderId !== null) return;
    const render = renderOverride ?? renders.find((entry) => entry.render_id === renderId);
    if (!render) return;

    setSelectedRenderId(renderId);
    setViewerRenderId(renderId);
    setViewerStage("loading");
    setAnimatingRenderId(renderId);
    window.localStorage.setItem(LAST_RENDER_STORAGE_KEY, String(renderId));
    window.setTimeout(() => {
      setViewerStage("playing");
      setAnimatingRenderId(null);
    }, DISC_DROP_DURATION_MS);
  }

  function closeViewer() {
    setViewerRenderId(null);
    setViewerStage("loading");
    setAnimatingRenderId(null);
  }

  async function handleDeleteRender(renderId: number) {
    await cancelRender(renderId);
    setRenders((prev) => prev.filter((r) => r.render_id !== renderId));
    if (selectedRenderId === renderId) setSelectedRenderId(null);
    if (viewerRenderId === renderId) closeViewer();
  }

  return (
    <div className="relative flex min-h-screen flex-col overflow-hidden bg-[#0a0a0a] scanlines">
      <div className="pointer-events-none fixed inset-0 animate-crt-flicker bg-transparent" />

      <header className="relative z-10 flex flex-wrap items-center justify-between gap-4 px-6 pt-8 sm:px-8">
        <div className="flex items-center gap-6">
          <BackButton fallback="/" />
          <CrtStaticText
            as="h1"
            text="INSERT MIXTAPE"
            textClassName="font-retro text-3xl tracking-widest text-[#ff77c2] glow-text sm:text-4xl"
          />
        </div>

        <button
          onClick={() => navigate("/works-in-progress")}
          className="crt-action retro-button-secondary inline-flex items-center gap-3 px-4 py-3 font-retro text-base tracking-[0.16em]"
        >
          <FolderOpen className="h-4 w-4" />
          <span className="crt-action__label" data-text="OPEN WIP LIBRARY">
            OPEN WIP LIBRARY
          </span>
        </button>
      </header>

      <main className="relative z-10 flex flex-1 flex-col gap-6 px-4 py-8 sm:px-8 sm:py-10">
        {loading ? (
          <CrtStaticText
            as="p"
            text="LOADING RENDERS..."
            textClassName="animate-pulse text-center font-retro text-2xl tracking-[0.2em] text-[#91fff2]/70"
          />
        ) : renders.length === 0 ? (
          <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col items-center justify-center border border-[#1affe4]/10 bg-[#08131a]/80 px-6 py-12 text-center">
            <Film className="h-14 w-14 text-[#ff77c2]/55" />
            <CrtStaticText
              as="p"
              text="NO FINISHED MIXTAPES YET"
              className="mt-6"
              textClassName="font-retro text-3xl tracking-[0.18em] text-[#ff9bd2]"
            />
            <button
              onClick={() => navigate("/works-in-progress")}
              className="crt-action retro-button-primary mt-8 inline-flex items-center gap-3 px-5 py-3 font-retro text-base tracking-[0.16em]"
            >
              <span className="crt-action__label" data-text="GO TO WORKS IN PROGRESS">
                GO TO WORKS IN PROGRESS
              </span>
            </button>
          </div>
        ) : (
          <>
            <section className="retro-shell mx-auto w-full max-w-6xl p-5 sm:p-6">
              <div className="relative z-10">
                <div className="mx-auto max-w-3xl text-center">
                  <p className="font-retro text-sm tracking-[0.34em] text-[#1affe4]/70">
                    FINISHED MIXTAPE LIBRARY
                  </p>
                  <CrtStaticText
                    as="h2"
                    text="SELECT A DISC TO PLAY"
                    className="mt-3"
                    textClassName="font-retro text-3xl tracking-[0.18em] text-[#ff9bd2] sm:text-4xl"
                  />
                </div>

                <div className="mt-8">
                  <div
                    style={{
                      position: "relative",
                      background: "linear-gradient(135deg, #1c1c2e 0%, #0f0f1a 100%)",
                      boxShadow: "inset 0 0 60px rgba(0,0,0,0.6), 0 12px 40px rgba(0,0,0,0.8)",
                      border: "1px solid #2a2a3a",
                      borderRadius: "10px",
                      padding: "20px 16px",
                      width: "100%",
                    }}
                  >
                    <div
                      style={{
                        position: "absolute",
                        top: "6%",
                        bottom: "6%",
                        left: "50%",
                        width: "2px",
                        background:
                          "linear-gradient(to bottom, transparent, #2a2a3a 20%, #3a3a4a 50%, #2a2a3a 80%, transparent)",
                        transform: "translateX(-50%)",
                      }}
                    />

                    <div className="mx-auto grid w-full max-w-4xl grid-cols-2 gap-3 sm:gap-4">
                      {pageItems.map((render) => (
                        <DiscSlot
                          key={render.render_id}
                          render={render}
                          selected={selectedRender?.render_id === render.render_id}
                          isAnimating={animatingRenderId === render.render_id}
                          onClick={() => setSelectedRenderId(render.render_id)}
                        />
                      ))}
                      {pageItems.length < ITEMS_PER_PAGE &&
                        Array.from({ length: ITEMS_PER_PAGE - pageItems.length }).map((_, i) => (
                          <div key={`empty-${i}`} className="cd-sleeve opacity-0" />
                        ))}
                    </div>
                  </div>
                </div>

                <div className="retro-panel retro-panel--labeled mt-8 p-5 pt-7">
                  <span className="retro-panel__label retro-panel__label--pink">SELECTED OUTPUT</span>
                  <div className="mx-auto max-w-3xl text-center">
                    <p className="font-retro text-2xl tracking-[0.14em] text-[#ffb6dd]">
                      {selectedRender?.project_name ?? "NONE"}
                    </p>
                    <p className="mt-3 font-mono text-sm text-[#91fff2]/60">
                      {selectedRender?.completed_at
                        ? `Rendered ${new Date(selectedRender.completed_at).toLocaleString()}`
                        : ""}
                    </p>
                    {selectedRender ? (
                      <div className="mt-5 flex items-center justify-center gap-3">
                        <button
                          onClick={() => startPlayback(selectedRender.render_id)}
                          disabled={animatingRenderId !== null}
                          className="crt-action retro-button-primary inline-flex items-center gap-3 px-4 py-3 font-retro text-base tracking-[0.16em] disabled:cursor-not-allowed disabled:opacity-40"
                        >
                          <PlayCircle className="h-4 w-4" />
                          <span className="crt-action__label" data-text="PLAY MIXTAPE">
                            PLAY MIXTAPE
                          </span>
                        </button>
                        <button
                          onClick={() => handleDeleteRender(selectedRender.render_id)}
                          className="inline-flex items-center gap-2 border border-red-500/30 bg-red-500/10 px-3 py-3 font-retro text-base tracking-[0.16em] text-red-400 hover:bg-red-500/20 transition-colors"
                          title="Delete this render"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    ) : null}
                  </div>
                </div>
              </div>
            </section>
          </>
        )}
      </main>

      {renders.length > 0 && (
        <footer className="relative z-10 flex items-center justify-center gap-8 pb-10">
          <button
            onClick={() => setPage((current) => current - 1)}
            disabled={page === 0}
            className={clsx(
              "crt-action font-retro text-2xl tracking-widest transition-colors",
              page === 0 ? "cursor-not-allowed text-zinc-700" : "text-zinc-400 hover:text-zinc-200"
            )}
          >
            <span className="crt-action__label" data-text="◀ PREV">
              ◀ PREV
            </span>
          </button>
          <CrtStaticText
            as="span"
            text={`DISC ${page + 1} OF ${totalPages}`}
            textClassName="font-retro text-xl tracking-widest text-zinc-500"
          />
          <button
            onClick={() => setPage((current) => current + 1)}
            disabled={page >= totalPages - 1}
            className={clsx(
              "crt-action font-retro text-2xl tracking-widest transition-colors",
              page >= totalPages - 1
                ? "cursor-not-allowed text-zinc-700"
                : "text-zinc-400 hover:text-zinc-200"
            )}
          >
            <span className="crt-action__label" data-text="NEXT ▶">
              NEXT ▶
            </span>
          </button>
        </footer>
      )}

      {viewerRender ? (
        <div
          className="fixed inset-0 z-[70] flex items-center justify-center bg-black/92 px-4 py-6"
          onClick={closeViewer}
        >
          <div
            className="relative w-full max-w-6xl border border-[#1affe4]/10 bg-[#030608] p-5 shadow-[0_18px_60px_rgba(0,0,0,0.55)] sm:p-6"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="relative">
              <div className="flex items-start justify-between gap-4 border-b border-[#1affe4]/10 pb-4">
                <div>
                  <p className="font-retro text-sm tracking-[0.32em] text-[#1affe4]/70">
                    NOW PLAYING
                  </p>
                  <CrtStaticText
                    as="h2"
                    text={viewerRender.project_name.toUpperCase()}
                    className="mt-2"
                    textClassName="font-retro text-2xl tracking-[0.18em] text-[#ff9bd2] sm:text-3xl"
                  />
                </div>
                <button
                  onClick={closeViewer}
                  className="crt-action retro-button-secondary inline-flex items-center gap-2 px-3 py-2 font-retro text-base tracking-[0.16em]"
                >
                  <X className="h-4 w-4" />
                  <span className="crt-action__label" data-text="CLOSE">
                    CLOSE
                  </span>
                </button>
              </div>

              <div className="mt-5 overflow-hidden rounded-bezel border border-[#1affe4]/10 bg-black">
                {viewerStage === "loading" ? (
                  <div className="mixtape-walkman flex min-h-[72vh] items-center justify-center p-6">
                    <div className="mixtape-walkman__body mixtape-walkman__body--modal">
                      <div className="mixtape-walkman__masthead">
                        <span className="mixtape-walkman__brand">POWER HOUR</span>
                        <span className="mixtape-walkman__brand">DIGITAL WALKMAN</span>
                      </div>

                      <div className="mixtape-walkman__speaker mixtape-walkman__speaker--left" />
                      <div className="mixtape-walkman__speaker mixtape-walkman__speaker--right" />

                      <div className="mixtape-walkman__screen">
                        <p className="font-retro text-sm tracking-[0.28em] text-[#91fff2]/80">
                          INSERTING DISC
                        </p>
                        <p className="mt-3 font-retro text-lg tracking-[0.12em] text-[#ffb6dd]">
                          {viewerRender.project_name}
                        </p>
                        <p className="mt-3 font-mono text-sm text-[#91fff2]/60">
                          The disc is dropping into the deck and slowly spinning up before playback.
                        </p>
                      </div>

                      <div className="mixtape-walkman__deck mixtape-walkman__deck--modal">
                        <div className="mixtape-walkman__slot" />
                        <div className="mixtape-walkman__window" />
                        <div
                          className={clsx(
                            "mixtape-walkman__disc",
                            "mixtape-walkman__disc--visible",
                            "mixtape-walkman__disc--spinup"
                          )}
                          style={{ background: CD_GRADIENT }}
                        >
                          <div className="mixtape-walkman__disc-label mixtape-walkman__disc-label--top">
                            {viewerLine1}
                          </div>
                          {viewerLine2 ? (
                            <div className="mixtape-walkman__disc-label mixtape-walkman__disc-label--bottom">
                              {viewerLine2}
                            </div>
                          ) : null}
                          <div className="mixtape-walkman__disc-hole" />
                        </div>
                      </div>

                      <div className="mixtape-walkman__controls">
                        <span />
                        <span />
                        <span />
                        <span />
                      </div>
                    </div>
                  </div>
                ) : (
                  <video
                    key={viewerRender.render_id}
                    src={viewerRender.output_url}
                    controls
                    autoPlay
                    playsInline
                    preload="auto"
                    className="max-h-[78vh] w-full bg-black object-contain"
                  />
                )}
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function DiscSlot({
  render,
  selected,
  isAnimating,
  onClick,
}: {
  render: RenderLibraryEntry;
  selected: boolean;
  isAnimating: boolean;
  onClick: () => void;
}) {
  const [line1, line2] = splitName(render.project_name);

  return (
    <button
      onClick={onClick}
      className={clsx(
        "group flex w-full flex-col items-center gap-1.5 transition-all duration-200",
        selected && "scale-[1.03]",
        isAnimating && "animate-disc-drop"
      )}
    >
      <div className="cd-sleeve mx-auto w-full max-w-[320px]">
        <div
          className="relative w-full rounded-full transition-all duration-200 group-hover:brightness-110"
          style={{
            aspectRatio: "1 / 1",
            background: CD_GRADIENT,
            boxShadow: selected
              ? "0 0 0 2px rgba(26,255,228,0.45), 0 2px 12px rgba(0,0,0,0.5)"
              : "0 2px 12px rgba(0,0,0,0.5), inset 0 0 0 1px rgba(255,255,255,0.15)",
          }}
        >
          <div
            style={{
              position: "absolute",
              top: "7%",
              left: "12%",
              right: "12%",
              textAlign: "center",
            }}
          >
            <span
              className="font-marker text-[#111]"
              style={{
                fontSize: "clamp(0.84rem, 4vw, 1.3rem)",
                transform: "rotate(-3deg)",
                display: "block",
                lineHeight: 1.1,
              }}
            >
              {line1}
            </span>
          </div>

          <div
            style={{
              position: "absolute",
              inset: "28%",
              borderRadius: "50%",
              background: "rgba(0,0,0,0.22)",
              border: "1px solid rgba(255,255,255,0.1)",
            }}
          />

          <div
            style={{
              position: "absolute",
              width: "7%",
              height: "7%",
              top: "46.5%",
              left: "46.5%",
              borderRadius: "50%",
              background: "#07070e",
            }}
          />

          {line2 && (
            <div
              style={{
                position: "absolute",
                bottom: "7%",
                left: "12%",
                right: "12%",
                textAlign: "center",
              }}
            >
              <span
                className="font-marker text-[#111]"
                style={{
                  fontSize: "clamp(0.84rem, 4vw, 1.3rem)",
                  transform: "rotate(2deg)",
                  display: "block",
                  lineHeight: 1.1,
                }}
              >
                {line2}
              </span>
            </div>
          )}
        </div>
      </div>

      <div className="text-center">
        <p className="font-retro text-sm tracking-[0.24em] text-[#91fff2]/70">
          RENDER #{render.render_id}
        </p>
      </div>
    </button>
  );
}
