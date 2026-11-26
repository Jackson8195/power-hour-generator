import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import clsx from "clsx";
import { Download, Film, FolderOpen, Link2, Play, Trash2, X } from "lucide-react";
import type { RenderLibraryEntry } from "../utils/types";
import { listRenderedVideos, cancelRender, healthCheck } from "../utils/api";
import StudioPage from "../components/StudioPage";
import CrtStaticText from "../components/CrtStaticText";
import { useConfirm } from "../components/ConfirmDialog";

const TAPES_PER_ROW = 10;
const ROWS_PER_PAGE = 2;
const TAPES_PER_PAGE = TAPES_PER_ROW * ROWS_PER_PAGE;
const LAST_RENDER_STORAGE_KEY = "power-hour-last-mixtape-render";
const INSERT_MS = 450;

// Label stripe colours, picked per tape so the shelf doesn't read as one grey block.
const TAPE_COLORS = ["#ff2b9d", "#1affe4", "#ffd166", "#b08cff", "#7dffb0", "#ff8d4d"];

function tapeColor(render: RenderLibraryEntry) {
  return TAPE_COLORS[render.render_id % TAPE_COLORS.length];
}

const SPINE_LINE_CHARS = 26; // what fits down a 280px spine at the smallest marker size

/** Hand-written spine label: one line if it fits, else two (split at the space nearest the
 *  middle), with the marker font shrinking for longer names. Never scrolls. */
function spineLabel(name: string): { text: string; fontSize: string } {
  const clean = name.trim().replace(/\s+/g, " ");
  const clip = (line: string) =>
    line.length > SPINE_LINE_CHARS ? line.slice(0, SPINE_LINE_CHARS - 1).trimEnd() + "…" : line;
  if (clean.length <= 16) return { text: clean, fontSize: "1.1rem" };

  const middle = clean.length / 2;
  let split = -1;
  for (let i = 0; i < clean.length; i++) {
    if (clean[i] === " " && (split < 0 || Math.abs(i - middle) < Math.abs(split - middle))) split = i;
  }
  const lines = split > 0 ? [clean.slice(0, split), clean.slice(split + 1)] : [clean];
  const longest = Math.max(...lines.map((line) => line.length));
  return {
    text: lines.map(clip).join("\n"),
    fontSize: longest <= 12 ? "1.05rem" : longest <= 18 ? "0.95rem" : "0.875rem",
  };
}

function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function formatSize(bytes: number) {
  if (!bytes) return "";
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  return `${Math.max(1, Math.round(bytes / 1024 ** 2))} MB`;
}

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]", "::1"]);

/** A link another device on the Wi-Fi can open: "localhost" means nothing to a phone, so a page
 *  opened at localhost swaps in the PC's LAN address (handed to the backend by docker-up). */
function shareLink(path: string, lanHost: string, frontendPort: number) {
  if (!LOCAL_HOSTS.has(window.location.hostname)) return `${window.location.origin}${path}`;
  return lanHost ? `http://${lanHost}:${frontendPort}${path}` : "";
}

/** Copy text; navigator.clipboard only exists on https/localhost, so fall back for LAN http. */
async function copyText(text: string) {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // fall through
    }
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  }
  area.remove();
  return ok;
}

function formatDate(value: string | null) {
  return value ? new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "—";
}

export default function TapeShelfPage() {
  const navigate = useNavigate();
  const confirm = useConfirm();
  const [renders, setRenders] = useState<RenderLibraryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [page, setPage] = useState(0);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [inserting, setInserting] = useState(false);
  const [playingId, setPlayingId] = useState<number | null>(null);
  const insertTimer = useRef<number>();
  const [lan, setLan] = useState<{ host: string; port: number }>({ host: "", port: 5173 });
  // The tape whose link was just copied (or couldn't be), and the link itself.
  const [shared, setShared] = useState<{ id: number; link: string; copied: boolean } | null>(null);

  useEffect(() => {
    healthCheck()
      .then((health) => setLan({ host: health.lan_host ?? "", port: health.frontend_port ?? 5173 }))
      .catch(() => {});
  }, []);

  async function copyLink(render: RenderLibraryEntry) {
    const link = shareLink(render.download_url, lan.host, lan.port);
    if (!link) {
      setShared({ id: render.render_id, link: "", copied: false });
      return;
    }
    setShared({ id: render.render_id, link, copied: await copyText(link) });
  }

  useEffect(() => {
    listRenderedVideos()
      .then((data) => {
        setRenders(data);
        const stored = Number(window.localStorage.getItem(LAST_RENDER_STORAGE_KEY) || "");
        const initial = data.find((render) => render.render_id === stored) ?? data[0];
        if (!initial) return;
        setSelectedId(initial.render_id);
        const index = data.indexOf(initial);
        setPage(Math.floor(index / TAPES_PER_PAGE));
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load the tape shelf."))
      .finally(() => setLoading(false));
    return () => window.clearTimeout(insertTimer.current);
  }, []);

  const totalPages = Math.max(1, Math.ceil(renders.length / TAPES_PER_PAGE));
  const pageTapes = renders.slice(page * TAPES_PER_PAGE, (page + 1) * TAPES_PER_PAGE);
  const rows = Array.from({ length: ROWS_PER_PAGE }, (_, row) =>
    pageTapes.slice(row * TAPES_PER_ROW, (row + 1) * TAPES_PER_ROW)
  );
  const selected = useMemo(
    () => renders.find((render) => render.render_id === selectedId) ?? null,
    [renders, selectedId]
  );
  const playing = useMemo(() => renders.find((render) => render.render_id === playingId) ?? null, [renders, playingId]);

  function selectTape(render: RenderLibraryEntry) {
    if (inserting) return;
    setSelectedId(render.render_id);
    window.localStorage.setItem(LAST_RENDER_STORAGE_KEY, String(render.render_id));
  }

  function play(render: RenderLibraryEntry) {
    if (inserting) return;
    selectTape(render);
    if (prefersReducedMotion()) {
      setPlayingId(render.render_id);
      return;
    }
    // Short and snappy: the cover slides into the VCR, then the TV powers on.
    setInserting(true);
    insertTimer.current = window.setTimeout(() => {
      setInserting(false);
      setPlayingId(render.render_id);
    }, INSERT_MS);
  }

  async function erase(render: RenderLibraryEntry) {
    const ok = await confirm({
      title: "ERASE TAPE?",
      body: (
        <>
          The rendered video for <span className="text-magenta-text">{render.project_name}</span> will be deleted
          from disk. The project and its clips stay, so you can render it again.
        </>
      ),
      confirmLabel: "ERASE",
      tone: "danger",
    });
    if (!ok) return;
    try {
      await cancelRender(render.render_id);
      setRenders((prev) => {
        const next = prev.filter((r) => r.render_id !== render.render_id);
        setPage((p) => Math.min(p, Math.max(0, Math.ceil(next.length / TAPES_PER_PAGE) - 1)));
        return next;
      });
      if (selectedId === render.render_id) setSelectedId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not erase the tape.");
    }
  }

  // Arrow keys walk the shelf like a remote.
  function handleShelfKey(event: React.KeyboardEvent) {
    if (!renders.length || !(event.key === "ArrowRight" || event.key === "ArrowLeft")) return;
    event.preventDefault();
    const index = Math.max(0, renders.findIndex((r) => r.render_id === selectedId));
    const nextIndex = Math.max(0, Math.min(renders.length - 1, index + (event.key === "ArrowRight" ? 1 : -1)));
    const next = renders[nextIndex];
    selectTape(next);
    setPage(Math.floor(nextIndex / TAPES_PER_PAGE));
    window.requestAnimationFrame(() =>
      (document.querySelector(`[data-tape="${next.render_id}"]`) as HTMLElement | null)?.focus()
    );
  }

  return (
    <StudioPage
      eyebrow="FINISHED POWER HOURS"
      title="TAPE SHELF"
      actions={
        <button
          onClick={() => navigate("/works-in-progress")}
          className="crt-action retro-button-secondary inline-flex items-center gap-3 px-4 py-3"
        >
          <FolderOpen className="h-4 w-4" />
          <span className="crt-action__label type-label" data-text="WORKS IN PROGRESS">
            WORKS IN PROGRESS
          </span>
        </button>
      }
    >
      {error ? (
        <div className="osd-notice osd-notice--error">
          <p className="osd-notice__title">TRACKING ERROR</p>
          <p className="type-body mt-1 !text-inherit">{error}</p>
        </div>
      ) : null}

      {loading ? (
        <div className="retro-panel px-6 py-16 text-center">
          <p className="type-display text-3xl text-phosphor-text/80">REWINDING...</p>
          <div className="tracking-loader mx-auto mt-6 max-w-xs" />
        </div>
      ) : renders.length === 0 ? (
        <div className="retro-panel flex flex-col items-center px-6 py-16 text-center">
          <Film className="h-14 w-14 text-magenta-soft/60" />
          <CrtStaticText
            as="p"
            text="THE SHELF IS EMPTY"
            className="mt-6"
            textClassName="type-display text-3xl text-magenta-light"
          />
          <p className="type-body mt-3">Render a project and its tape lands here.</p>
          <button
            onClick={() => navigate("/works-in-progress")}
            className="crt-action retro-button-primary mt-8 inline-flex items-center gap-3 px-5 py-3"
          >
            <span className="crt-action__label type-label" data-text="GO TO WORKS IN PROGRESS">
              GO TO WORKS IN PROGRESS
            </span>
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-[minmax(0,1fr)] gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
          {/* Shelf */}
          <div>
            <div className="vhs-shelf" onKeyDown={handleShelfKey}>
              {rows.map((row, rowIndex) =>
                row.length || rowIndex === 0 ? (
                  <div key={rowIndex} className={clsx(rowIndex > 0 && "mt-4")}>
                    <div className="vhs-shelf__row overflow-x-auto">
                      {row.map((render) => (
                        <button
                          key={render.render_id}
                          data-tape={render.render_id}
                          onClick={() => selectTape(render)}
                          onDoubleClick={() => play(render)}
                          className={clsx("vhs-tape", selectedId === render.render_id && "vhs-tape--selected")}
                          style={{ ["--tape-color" as string]: tapeColor(render) }}
                          aria-pressed={selectedId === render.render_id}
                          aria-label={`${render.project_name}, tape ${render.render_id}`}
                          title={render.project_name}
                        >
                          <span className="vhs-tape__label">
                            <span className="vhs-tape__title" style={{ fontSize: spineLabel(render.project_name).fontSize }}>
                              {spineLabel(render.project_name).text}
                            </span>
                          </span>
                          <span className="vhs-tape__num">#{render.render_id}</span>
                        </button>
                      ))}
                    </div>
                    <div className="vhs-shelf__board" />
                  </div>
                ) : null
              )}
            </div>

            <div className="mt-5 flex items-center justify-center gap-3 whitespace-nowrap sm:gap-8">
              <button
                onClick={() => setPage((current) => current - 1)}
                disabled={page === 0}
                className="crt-action retro-button-ghost px-3 py-1.5 disabled:cursor-not-allowed disabled:opacity-30"
              >
                <span className="crt-action__label type-label text-2xl" data-text="◀◀ REW">
                  ◀◀ REW
                </span>
              </button>
              <span className="type-label text-xl text-phosphor-text/80 sm:text-2xl">
                SHELF {page + 1} / {totalPages}
              </span>
              <button
                onClick={() => setPage((current) => current + 1)}
                disabled={page >= totalPages - 1}
                className="crt-action retro-button-ghost px-3 py-1.5 disabled:cursor-not-allowed disabled:opacity-30"
              >
                <span className="crt-action__label type-label text-2xl" data-text="FF ▶▶">
                  FF ▶▶
                </span>
              </button>
            </div>
            <p className="type-body mt-2 text-center text-phosphor-text/60">
              Click a tape to pull it out · double-click to play · ◀ ▶ to browse
            </p>
          </div>

          {/* Selected tape + VCR */}
          <div className="retro-panel retro-panel--labeled flex flex-col items-center gap-5 p-5 pt-8">
            <span className="retro-panel__label retro-panel__label--pink">IN HAND</span>
            {selected ? (
              <>
                <div
                  key={selected.render_id}
                  className={clsx("vhs-cover crt-power-on crt-power-on--fast", inserting && "vhs-inserting")}
                  style={{ ["--tape-color" as string]: tapeColor(selected) }}
                >
                  <p className="type-label relative z-10 text-lg text-white/80">POWER HOUR STUDIO · VHS</p>
                  <p className="relative z-10 mt-6 break-words font-marker text-3xl leading-tight text-white">
                    {selected.project_name}
                  </p>
                  <div className="absolute inset-x-4 bottom-4 z-10 flex items-end justify-between">
                    <span className="type-data text-xs text-white/70">{formatDate(selected.completed_at)}</span>
                    <span className="type-label text-lg text-white/80">#{selected.render_id}</span>
                  </div>
                </div>

                <div className="vcr w-full">
                  <div className="flex items-center justify-between gap-3">
                    <span className="vcr__display">{inserting ? "LOADING" : "STOP"}</span>
                    <span className="type-label text-base text-zinc-400">HI-FI STEREO</span>
                  </div>
                  <div className="vcr__slot mt-3" />
                </div>

                <div className="flex w-full gap-3">
                  <button
                    onClick={() => play(selected)}
                    disabled={inserting}
                    className="crt-action retro-button-primary inline-flex flex-1 items-center justify-center gap-3 px-4 py-3 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    <Play className="h-4 w-4" />
                    <span className="crt-action__label type-label" data-text="PLAY">
                      PLAY
                    </span>
                  </button>
                  <button
                    onClick={() => void erase(selected)}
                    disabled={inserting}
                    className="crt-action retro-button-danger inline-flex items-center gap-2 px-4 py-3"
                    title="Erase this tape"
                  >
                    <Trash2 className="h-4 w-4" />
                    <span className="crt-action__label type-label" data-text="ERASE">
                      ERASE
                    </span>
                  </button>
                </div>

                <div className="flex w-full gap-3">
                  <a
                    href={selected.download_url}
                    download
                    className="crt-action retro-button-secondary inline-flex flex-1 items-center justify-center gap-3 px-4 py-3"
                    title="Save the MP4 to this device"
                  >
                    <Download className="h-4 w-4" />
                    <span className="crt-action__label type-label" data-text="DOWNLOAD">
                      DOWNLOAD
                    </span>
                    {selected.size_bytes ? (
                      <span className="type-data text-sm opacity-80">{formatSize(selected.size_bytes)}</span>
                    ) : null}
                  </a>
                  <button
                    onClick={() => void copyLink(selected)}
                    className="crt-action retro-button-ghost inline-flex items-center gap-2 px-4 py-3"
                    title="Copy a link any device on this Wi-Fi can open to download the tape"
                  >
                    <Link2 className="h-4 w-4" />
                    <span className="crt-action__label type-label" data-text="COPY LINK">
                      COPY LINK
                    </span>
                  </button>
                </div>

                {shared?.id === selected.render_id ? (
                  shared.link ? (
                    <div className="osd-notice osd-notice--ok w-full">
                      <p className="osd-notice__title">{shared.copied ? "LINK COPIED" : "COPY THIS LINK"}</p>
                      <p className="type-body mt-1 !text-inherit">
                        Open it on any phone, tablet or computer on this Wi-Fi to save the tape.
                      </p>
                      <input
                        readOnly
                        value={shared.link}
                        onFocus={(event) => event.currentTarget.select()}
                        className="retro-input mt-2 w-full px-3 py-2 font-mono text-sm"
                        aria-label="Tape download link"
                      />
                    </div>
                  ) : (
                    <div className="osd-notice osd-notice--warn w-full">
                      <p className="osd-notice__title">NO NETWORK ADDRESS</p>
                      <p className="type-body mt-1 !text-inherit">
                        This page is open at localhost and the app doesn&apos;t know this PC&apos;s Wi-Fi address. Start it
                        with scripts/docker-up, or open the app from the other device and download it there.
                      </p>
                    </div>
                  )
                ) : null}
              </>
            ) : (
              <p className="type-body py-10 text-center">Pick a tape off the shelf.</p>
            )}
          </div>
        </div>
      )}

      {playing ? <TapePlayer render={playing} onClose={() => setPlayingId(null)} /> : null}
    </StudioPage>
  );
}

function TapePlayer({ render, onClose }: { render: RenderLibraryEntry; onClose: () => void }) {
  const [showOsd, setShowOsd] = useState(true);
  const [noSignal, setNoSignal] = useState(false);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const timer = window.setTimeout(() => setShowOsd(false), 2200);
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onCloseRef.current();
    }
    window.addEventListener("keydown", onKey);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  return createPortal(
    <div className="osd-backdrop !bg-black/90" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Now playing ${render.project_name}`}
        className="relative w-full max-w-6xl border border-phosphor/15 bg-[#030608] p-4 shadow-[0_18px_60px_rgba(0,0,0,0.55)] sm:p-5"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between gap-4">
          <div className="min-w-0">
            <p className="type-eyebrow">NOW PLAYING</p>
            <p className="type-display mt-1 truncate text-3xl text-magenta-light">{render.project_name.toUpperCase()}</p>
          </div>
          <button onClick={onClose} className="crt-action retro-button-secondary inline-flex shrink-0 items-center gap-2 px-3 py-2">
            <X className="h-4 w-4" />
            <span className="crt-action__label type-label" data-text="EJECT">
              EJECT
            </span>
          </button>
        </div>

        <div className="crt-power-on relative overflow-hidden rounded-bezel border border-phosphor/10 bg-black">
          {noSignal ? (
            <div className="flex aspect-video max-h-[76vh] w-full flex-col items-center justify-center gap-3 bg-[#0a1a3a] text-center">
              <p className="type-display text-5xl text-white">NO SIGNAL</p>
              <p className="type-body max-w-md !text-white/80">
                The video file for this tape is missing from the renders folder. Render the project again to
                re-record it, or erase the tape.
              </p>
            </div>
          ) : (
            <video
              src={render.output_url}
              controls
              autoPlay
              playsInline
              preload="auto"
              onError={() => setNoSignal(true)}
              className="max-h-[76vh] w-full bg-black object-contain"
            />
          )}
          {/* VCR on-screen display, like the green PLAY in the corner of an old TV. */}
          <span
            className={clsx(
              "vcr__display pointer-events-none absolute left-5 top-4 text-3xl transition-opacity duration-500",
              showOsd && !noSignal ? "opacity-100" : "opacity-0"
            )}
          >
            PLAY ▶
          </span>
        </div>
      </div>
    </div>,
    document.body
  );
}
