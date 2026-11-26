import { useEffect, useState, useCallback, useRef } from "react";
import {
  DndContext,
  closestCenter,
  PointerSensor,
  KeyboardSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Link, useParams } from "react-router-dom";
import {
  Search,
  Download,
  Trash2,
  Play,
  Sparkles,
  GripVertical,
  ChevronDown,
  Scissors,
  CheckCircle2,
} from "lucide-react";
import Spinner from "../components/Spinner";
import type {
  Clip,
  ClipAnalysis,
  ProjectDetail,
  RenderProgress,
  SearchResult,
} from "../utils/types";
import {
  ApiError,
  addClip,
  cancelRender,
  commitClipSelection,
  connectRenderWs,
  deleteClip,
  getActiveRender,
  getAiTransitions,
  getClipAnalysis,
  getRecommendedTracks,
  getProject,
  reorderClips,
  searchYouTube,
  startDownload,
  startRender,
  updateClip,
  useSuggestedSegment,
} from "../utils/api";
import clsx from "clsx";
import CrtStaticText from "../components/CrtStaticText";
import ChangeoverBuilder from "../components/ChangeoverBuilder";
import AiTransitionReview from "../components/AiTransitionReview";
import WaveformRangeEditor from "../components/WaveformRangeEditor";
import { formatTime } from "../utils/time";
import StudioPage from "../components/StudioPage";
import SegmentedControl from "../components/SegmentedControl";
import { usePageCrumb } from "../components/StudioNav";
import { useConfirm } from "../components/ConfirmDialog";

type DraftRange = { start: number; end: number };

function formatSearchSourceLabel(source: string): string {
  if (source === "youtube_api") return "YOUTUBE API";
  if (source === "yt_dlp") return "YT-DLP";
  return source ? source.replace(/_/g, " ").toUpperCase() : "";
}

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const projectId = Number(id);

  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [musicOnly, setMusicOnly] = useState(true);
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [recommendedResults, setRecommendedResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [loadingRecommendations, setLoadingRecommendations] = useState(false);
  const [renderProgress, setRenderProgress] = useState<RenderProgress | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [renderNotice, setRenderNotice] = useState<string | null>(null);
  const [activeRenderId, setActiveRenderId] = useState<number | null>(null);
  const renderWsRef = useRef<WebSocket | null>(null);
  const [activeTab, setActiveTab] = useState<"search" | "timeline">("search");
  const dndSensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );
  const [expandedClipId, setExpandedClipId] = useState<number | null>(null);
  const [analysisByClip, setAnalysisByClip] = useState<Record<number, ClipAnalysis>>({});
  const [loadingAnalysis, setLoadingAnalysis] = useState<Record<number, boolean>>({});
  const [draftRanges, setDraftRanges] = useState<Record<number, DraftRange>>({});
  const [savingClipIds, setSavingClipIds] = useState<Record<number, boolean>>({});
  const [committingClipIds, setCommittingClipIds] = useState<Record<number, boolean>>({});
  // A trim the server refused or that failed, shown on that clip until the next attempt.
  const [trimErrors, setTrimErrors] = useState<Record<number, string>>({});
  const confirm = useConfirm();
  usePageCrumb(project?.name);
  // AI transitions made by the AI build: reviewable here too (trim, text) until the render.
  const [hasAiTransitions, setHasAiTransitions] = useState(false);
  const [transitionPrompt, setTransitionPrompt] = useState("");
  const [drinkText, setDrinkText] = useState("DRINK!");

  useEffect(() => {
    getAiTransitions(projectId)
      .then((review) => setHasAiTransitions(review.transitions.length > 0))
      .catch(() => setHasAiTransitions(false));
  }, [projectId]);

  // The range each clip had on the server at the last load. A draft that still matches it
  // has not been touched here, so it follows the server (e.g. a range saved on the phone);
  // a draft that differs is an unsaved edit on this device and is kept.
  const serverRanges = useRef<Record<number, DraftRange>>({});
  const dragging = useRef(false);

  const loadProject = useCallback(async () => {
    try {
      const data = await getProject(projectId);
      if (dragging.current) return; // don't reshuffle the list under a finger mid-drag
      setProject(data);
      // Captured outside the updater: React may run updaters twice (StrictMode), so they
      // must not read a ref they also change.
      const baseline = serverRanges.current;
      serverRanges.current = Object.fromEntries(
        data.clips.map((clip) => [clip.id, { start: clip.start_time, end: clip.end_time }])
      );
      setDraftRanges((prev) => {
        const next: Record<number, DraftRange> = {};
        for (const clip of data.clips) {
          const server = { start: clip.start_time, end: clip.end_time };
          const before = baseline[clip.id];
          const local = prev[clip.id];
          const untouched = !local || !before || (local.start === before.start && local.end === before.end);
          next[clip.id] = untouched ? server : local;
        }
        return next;
      });
    } catch (err) {
      console.error("Failed to load project:", err);
    }
  }, [projectId]);

  useEffect(() => {
    loadProject();
  }, [loadProject]);

  const loadRecommendations = useCallback(async () => {
    setLoadingRecommendations(true);
    try {
      const results = await getRecommendedTracks(projectId);
      setRecommendedResults(results);
    } catch (err) {
      console.error("Failed to load recommendations:", err);
    } finally {
      setLoadingRecommendations(false);
    }
  }, [projectId]);

  useEffect(() => {
    loadRecommendations();
  }, [loadRecommendations]);

  // Keep in step with the other device (desktop <-> phone): poll while visible, faster while
  // clips are downloading, and catch up as soon as the tab or app comes back to the front.
  const busyClips = Boolean(
    project?.clips.some((c) => c.status === "pending" || c.status === "downloading" || c.status === "analyzing")
  );
  useEffect(() => {
    const sync = () => {
      if (document.hidden) return;
      void loadProject();
      if (!renderWsRef.current) {
        getActiveRender(projectId)
          .then((active) => {
            if (active && !renderWsRef.current) connectToRender(active.render_id);
          })
          .catch(() => {});
      }
    };
    const interval = window.setInterval(sync, busyClips ? 3000 : 5000);
    document.addEventListener("visibilitychange", sync);
    window.addEventListener("focus", sync);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", sync);
      window.removeEventListener("focus", sync);
    };
    // connectToRender only touches refs and setters
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busyClips, loadProject, projectId]);

  function connectToRender(renderId: number) {
    renderWsRef.current?.close();
    setActiveRenderId(renderId);
    const ws = connectRenderWs(renderId, (data) => {
      setRenderProgress(data);
      if (data.status === "complete" || data.status === "error") {
        ws.close();
        renderWsRef.current = null;
        setActiveRenderId(null);
      }
    });
    renderWsRef.current = ws;
  }

  useEffect(() => {
    getActiveRender(projectId).then((active) => {
      if (active) connectToRender(active.render_id);
    }).catch(() => {});
    return () => renderWsRef.current?.close();
  }, [projectId]);

  async function ensureAnalysis(clipId: number) {
    if (analysisByClip[clipId] || loadingAnalysis[clipId]) {
      return;
    }

    setLoadingAnalysis((prev) => ({ ...prev, [clipId]: true }));
    try {
      const analysis = await getClipAnalysis(clipId);
      setAnalysisByClip((prev) => ({ ...prev, [clipId]: analysis }));
      setDraftRanges((prev) => ({
        ...prev,
        [clipId]: prev[clipId] ?? {
          start: analysis.suggested_start,
          end: analysis.suggested_end,
        },
      }));
    } catch (err) {
      console.error("Failed to load analysis:", err);
    } finally {
      setLoadingAnalysis((prev) => ({ ...prev, [clipId]: false }));
    }
  }

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!searchQuery.trim()) return;

    setSearching(true);
    try {
      const results = await searchYouTube(searchQuery, 10, projectId, musicOnly);
      setSearchResults(results);
    } catch (err) {
      console.error("Search failed:", err);
    } finally {
      setSearching(false);
    }
  }

  async function handleAddClip(result: SearchResult) {
    if (!project) return;

    try {
      const clip = await addClip(projectId, {
        source_url: `https://www.youtube.com/watch?v=${result.youtube_id}`,
        source_title: result.title,
        source_artist: result.artist,
        source_thumbnail: result.thumbnail,
        youtube_id: result.youtube_id,
        position: project.clips.length,
      });

      await startDownload(clip.id);
      await loadProject();
      await loadRecommendations();
      setSearchResults((prev) => prev.filter((r) => r.youtube_id !== result.youtube_id));
      setRecommendedResults((prev) => prev.filter((r) => r.youtube_id !== result.youtube_id));
    } catch (err) {
      console.error("Failed to add clip:", err);
    }
  }

  function handleDragEnd(event: DragEndEvent) {
    dragging.current = false;
    if (!project) return;
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = project.clips.findIndex((c) => c.id === active.id);
    const newIndex = project.clips.findIndex((c) => c.id === over.id);
    const reordered = [...project.clips];
    const [moved] = reordered.splice(oldIndex, 1);
    reordered.splice(newIndex, 0, moved);
    handleReorder(reordered.map((c) => c.id));
  }

  async function handleReorder(clipIds: number[]) {
    if (!project) return;
    // Optimistically reorder in UI
    const reordered = clipIds.map((id) => project.clips.find((c) => c.id === id)!);
    setProject({ ...project, clips: reordered });
    try {
      await reorderClips(project.id, clipIds);
    } catch (err) {
      console.error("Failed to reorder clips:", err);
      await loadProject();
    }
  }

  async function handleDeleteClip(clip: Clip) {
    const clipId = clip.id;
    const ok = await confirm({
      title: "REMOVE CLIP?",
      body: (
        <>
          <span className="text-magenta-text">{clip.source_title || "This clip"}</span> and its downloaded media
          and analysis will be deleted. You can search for it and add it again later.
        </>
      ),
      confirmLabel: "REMOVE",
      tone: "danger",
    });
    if (!ok) return;
    try {
      await deleteClip(clipId);
      setExpandedClipId((current) => (current === clipId ? null : current));
      await loadProject();
      await loadRecommendations();
    } catch (err) {
      console.error("Failed to delete clip:", err);
    }
  }

  async function handleExpandClip(clip: Clip) {
    if (clip.preview_url.includes("/media/clips/")) {
      return;
    }
    const nextExpanded = expandedClipId === clip.id ? null : clip.id;
    setExpandedClipId(nextExpanded);
    if (nextExpanded === clip.id && clip.status === "ready") {
      await ensureAnalysis(clip.id);
    }
  }

  async function handleUseSuggestion(clip: Clip) {
    setSavingClipIds((prev) => ({ ...prev, [clip.id]: true }));
    try {
      const updated = await useSuggestedSegment(clip.id);
      setDraftRanges((prev) => ({
        ...prev,
        [clip.id]: { start: updated.start_time, end: updated.end_time },
      }));
      await loadProject();
    } catch (err) {
      console.error("Failed to apply suggestion:", err);
    } finally {
      setSavingClipIds((prev) => ({ ...prev, [clip.id]: false }));
    }
  }

  async function handleSaveDraft(clip: Clip) {
    const draft = draftRanges[clip.id];
    if (!draft || draft.end <= draft.start) return;

    setSavingClipIds((prev) => ({ ...prev, [clip.id]: true }));
    try {
      await updateClip(clip.id, {
        start_time: draft.start,
        end_time: draft.end,
      });
      await loadProject();
    } catch (err) {
      console.error("Failed to save clip range:", err);
    } finally {
      setSavingClipIds((prev) => ({ ...prev, [clip.id]: false }));
    }
  }

  async function handleCommitSelection(clip: Clip) {
    const draft = draftRanges[clip.id];
    if (!draft || draft.end <= draft.start) return;
    const ok = await confirm({
      title: "TRIM AND DISCARD?",
      body: (
        <>
          This cuts the final clip ({formatTime(draft.start)} to {formatTime(draft.end)}) and deletes the full source
          download. To change the range afterwards you would have to download the song again.
        </>
      ),
      confirmLabel: "TRIM IT",
    });
    if (!ok) return;

    setCommittingClipIds((prev) => ({ ...prev, [clip.id]: true }));
    setTrimErrors((prev) => ({ ...prev, [clip.id]: "" }));
    try {
      await commitClipSelection(clip.id, {
        start_time: draft.start,
        end_time: draft.end,
      });
      await loadProject();
      setAnalysisByClip((prev) => {
        const next = { ...prev };
        delete next[clip.id];
        return next;
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Trim failed";
      setTrimErrors((prev) => ({ ...prev, [clip.id]: message }));
      // 409: another device already trimmed it. Pull the current state so this one shows it too.
      if (err instanceof ApiError && err.status === 409) {
        await loadProject();
        setAnalysisByClip((prev) => {
          const next = { ...prev };
          delete next[clip.id];
          return next;
        });
      }
    } finally {
      setCommittingClipIds((prev) => ({ ...prev, [clip.id]: false }));
    }
  }

  // Clips with a saved range that still point at their full download (AI review flow, or a
  // manual clip saved but not trimmed): rendering trims them afterwards.
  const sourceClips = (project?.clips ?? []).filter(
    (c) => c.status === "ready" && c.has_selection && !c.preview_url.includes("/media/clips/")
  );

  async function handleStartRender() {
    const onSource = sourceClips.length;
    if (onSource > 0) {
      const ok = await confirm({
        title: "RENDER IT?",
        body: (
          <>
            {onSource} clip{onSource === 1 ? " is" : "s are"} still on {onSource === 1 ? "its" : "their"} full source
            video. The render uses your ranges as they are now. When it finishes,{" "}
            {onSource === 1 ? "it's trimmed to its range and the full video is" : "they're trimmed to their ranges and the full videos are"}{" "}
            deleted to free up space.
          </>
        ),
        confirmLabel: "RENDER",
      });
      if (!ok) return;
    }
    setRenderError(null);
    setRenderNotice(null);
    setRenderProgress(null);
    try {
      const { render_id, clips_included, clips_skipped } = await startRender(projectId, {
        finalize_sources: onSource > 0,
      });
      if (clips_skipped.length > 0) {
        setRenderNotice(
          `Rendering ${clips_included} clip${clips_included === 1 ? "" : "s"}. Skipped ${clips_skipped.length} not ready or without a saved range: ${clips_skipped.join(", ")}`
        );
      }
      connectToRender(render_id);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Render failed";
      setRenderError(msg);
    }
  }

  async function handleCancelRender() {
    if (!activeRenderId) return;
    try {
      await cancelRender(activeRenderId);
      renderWsRef.current?.close();
      renderWsRef.current = null;
      setActiveRenderId(null);
      setRenderProgress(null);
    } catch (err) {
      console.error("Failed to cancel render:", err);
    }
  }

  if (!project) {
    return (
      <StudioPage eyebrow="EDIT MIXTAPE" title="LOADING PROJECT...">
        <div className="retro-panel px-6 py-16 text-center">
          <div className="tracking-loader mx-auto max-w-xs" />
        </div>
      </StudioPage>
    );
  }

  const reviewedClips = project.clips.filter((c) => c.has_selection);
  const rendering = renderProgress?.status === "rendering";

  return (
    <StudioPage
      eyebrow="EDIT MIXTAPE"
      title={project.name.toUpperCase()}
      stickyHeader
      subtitle={
        <span>
          <span className="text-magenta-text">{reviewedClips.length}</span> of {project.clips.length} clips have a
          locked-in range.
        </span>
      }
      actions={
        <>
          {rendering ? (
            <div className="flex min-w-[10rem] flex-col gap-1">
              <span className="type-label flex justify-between text-phosphor-text">
                <span className="rec-light !text-lg">REC</span>
                <span>{Math.round(renderProgress?.progress ?? 0)}%</span>
              </span>
              <div className="retro-progress h-2">
                <div className="retro-progress__bar h-full transition-all" style={{ width: `${renderProgress?.progress ?? 0}%` }} />
              </div>
            </div>
          ) : null}
          <button
            onClick={handleStartRender}
            disabled={reviewedClips.length === 0 || rendering}
            title={reviewedClips.length === 0 ? "Save a range on at least one clip first" : undefined}
            className="crt-action retro-button-primary inline-flex items-center justify-center gap-3 px-5 py-3 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {rendering ? <Spinner className="h-4 w-4" /> : <Play className="h-4 w-4" />}
            <span className="crt-action__label type-label" data-text={rendering ? "RENDERING" : "RENDER VIDEO"}>
              {rendering ? "RENDERING" : "RENDER VIDEO"}
            </span>
          </button>
        </>
      }
    >
      <div>
          {renderError && (
            <div className="osd-notice osd-notice--error mb-6">
              <p className="osd-notice__title">RENDER FAILED</p>
              <p className="type-body mt-1 !text-inherit">{renderError}</p>
            </div>
          )}

          {renderNotice && (
            <div className="osd-notice osd-notice--warn mb-6">
              <p className="osd-notice__title">HEADS UP</p>
              <p className="type-body mt-1 !text-inherit">{renderNotice}</p>
            </div>
          )}

          {renderProgress && (
            <div className="retro-panel retro-panel--labeled mb-6 p-5 pt-6">
              <span className="retro-panel__label">RENDER STATUS</span>
              <div className="relative z-10">
                <div className="mb-3 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <p className="font-retro text-lg tracking-[0.18em] text-phosphor-text">
                      {renderProgress.status === "rendering"
                        ? "RENDERING..."
                        : renderProgress.status === "complete"
                          ? "RENDER COMPLETE"
                          : `STATUS: ${renderProgress.status.toUpperCase()}`}
                    </p>
                    {renderProgress.status === "rendering" && (
                      <span
                        className={clsx(
                          "gpu-active-indicator",
                          !renderProgress.gpu_active && "gpu-active-indicator--cpu"
                        )}
                        title={
                          renderProgress.gpu_active
                            ? "Encoding on the GPU (NVENC)"
                            : "Encoding on the CPU (libx264)"
                        }
                      >
                        <span className="gpu-active-indicator__light" />
                        {renderProgress.gpu_active
                          ? "GPU ENCODING ACTIVE"
                          : "CPU ENCODING ACTIVE"}
                      </span>
                    )}
                  </div>
                  <span className="font-retro text-2xl text-magenta-text/90">
                    {Math.round(renderProgress.progress)}%
                  </span>
                </div>
                <div className="retro-progress h-3">
                  <div
                    className={clsx(
                      "h-full transition-all",
                      renderProgress.status === "complete"
                        ? "retro-progress__bar !bg-status-ok"
                        : renderProgress.status === "error"
                          ? "retro-progress__bar !bg-status-error"
                          : "retro-progress__bar"
                    )}
                    style={{ width: `${renderProgress.progress}%` }}
                  />
                </div>
                {renderProgress.status === "rendering" && (
                  <div className="mt-4 flex items-center justify-between gap-4">
                    <p className="type-body">
                      Estimated time 12 minutes. So this should take about 5 or 10 minutes.
                    </p>
                    <button
                      onClick={handleCancelRender}
                      className="crt-action retro-button-danger inline-flex shrink-0 items-center gap-2 px-3 py-1.5"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      <span className="crt-action__label type-label" data-text="CANCEL">CANCEL</span>
                    </button>
                  </div>
                )}
                {renderProgress.status === "complete" && renderProgress.output_path && (
                  <div className="mt-4 flex flex-wrap gap-3">
                    <a
                      href={renderProgress.output_path}
                      target="_blank"
                      className="crt-action retro-button-secondary inline-flex items-center gap-2 px-4 py-2 font-retro text-lg tracking-[0.16em]"
                      rel="noreferrer"
                    >
                      <Play className="h-3.5 w-3.5" />
                      <span className="crt-action__label" data-text="WATCH">
                        WATCH
                      </span>
                    </a>
                    <Link
                      to="/power-hours"
                      className="crt-action retro-button-secondary inline-flex items-center gap-2 px-4 py-2 font-retro text-lg tracking-[0.16em]"
                    >
                      <span className="crt-action__label" data-text="OPEN TAPE SHELF">
                        OPEN TAPE SHELF
                      </span>
                    </Link>
                  </div>
                )}
              </div>
            </div>
          )}

          {sourceClips.length > 0 && !rendering ? (
            <div className="osd-notice osd-notice--warn mb-6">
              <p className="osd-notice__title">CHECK THE PICKS</p>
              <p className="type-body mt-1 !text-inherit">
                {sourceClips.length} clip{sourceClips.length === 1 ? " has" : "s have"} a range pre-selected on the full
                video (the AI&apos;s pick, or one you saved). Open REVIEW CLIPS to check each one and drag the window
                wherever you like; rendering trims them to these ranges.
              </p>
            </div>
          ) : null}

          {hasAiTransitions ? (
            <div className="retro-panel retro-panel--labeled mb-6 p-5 pt-6">
              <span className="retro-panel__label retro-panel__label--pink">AI TRANSITIONS</span>
              <div className="relative z-10">
                <AiTransitionReview
                  projectId={projectId}
                  powerHourPrompt={project.description}
                  transitionPrompt={transitionPrompt}
                  onTransitionPromptChange={setTransitionPrompt}
                  drinkText={drinkText}
                  onDrinkTextChange={setDrinkText}
                  count={4}
                  sources="both"
                />
              </div>
            </div>
          ) : null}

          {/* Shot notification (changeover) builder */}
          <ChangeoverBuilder projectId={projectId} />

          <div className="mb-5 max-w-xl">
            <SegmentedControl
              label="Project section"
              value={activeTab}
              onChange={setActiveTab}
              options={[
                { value: "search", label: "SEARCH & ADD" },
                { value: "timeline", label: `REVIEW CLIPS (${project.clips.length})`, pink: true },
              ]}
            />
          </div>

          {activeTab === "search" && (
            <div>
          <form onSubmit={handleSearch} className="mb-2 flex gap-2">
            <input
              type="text"
              className="retro-input w-full px-4 py-3 font-mono text-sm tracking-[0.12em]"
              placeholder={musicOnly ? "Search for music videos..." : "Search YouTube..."}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            <button
              type="submit"
              disabled={searching}
              className="crt-action retro-button-primary inline-flex shrink-0 items-center gap-2 px-4 py-3 font-retro text-lg tracking-[0.16em] disabled:cursor-not-allowed disabled:opacity-40"
            >
              {searching ? (
                <Spinner className="h-4 w-4" />
              ) : (
                <Search className="h-4 w-4" />
              )}
              <span className="crt-action__label" data-text="SEARCH">
                SEARCH
              </span>
            </button>
          </form>

          <label className="mb-4 inline-flex items-center gap-2.5">
            <button
              type="button"
              onClick={() => setMusicOnly((current) => !current)}
              role="switch"
              aria-checked={musicOnly}
              className={[
                "relative inline-flex h-5 w-9 shrink-0 items-center border transition-colors",
                musicOnly
                  ? "border-phosphor/40 bg-phosphor/15"
                  : "border-magenta-soft/40 bg-magenta-soft/10",
              ].join(" ")}
            >
              <span
                className={[
                  "inline-block h-3 w-3 transform bg-current transition-transform",
                  musicOnly ? "translate-x-[19px] text-phosphor" : "translate-x-1 text-magenta-soft",
                ].join(" ")}
              />
            </button>
            <span className="font-mono text-sm tracking-[0.08em] text-phosphor-text/70">
              Music videos only
            </span>
          </label>

          {searchResults.length > 0 && (
            <div className="tracklist retro-panel--labeled mb-6 pt-2">
              <span className="retro-panel__label">SEARCH RESULTS</span>
              {searchResults.map((result) => (
                <SearchResultCard
                  key={result.youtube_id}
                  result={result}
                  alreadyAdded={project.clips.some((clip) => clip.youtube_id === result.youtube_id)}
                  onAdd={() => handleAddClip(result)}
                  badgeLabel={result.match_score > 0 ? `Score ${result.match_score.toFixed(1)}` : ""}
                />
              ))}
            </div>
          )}

          <div className="mb-6">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <p className="font-retro text-lg tracking-[0.18em] text-zinc-200">RECOMMENDED NEXT PICKS</p>
                <p className="type-body">
                  Suggestions update from the artists already showing up in this project.
                </p>
              </div>
              {loadingRecommendations && (
                <div className="font-retro text-lg tracking-[0.16em] text-phosphor-text/70">
                  <Spinner className="inline h-3.5 w-3.5" /> Refreshing
                </div>
              )}
            </div>

            {recommendedResults.length > 0 ? (
              <div className="tracklist">
                {recommendedResults.map((result) => (
                  <SearchResultCard
                    key={`rec-${result.youtube_id}`}
                    result={result}
                    alreadyAdded={project.clips.some((clip) => clip.youtube_id === result.youtube_id)}
                    onAdd={() => handleAddClip(result)}
                    badgeLabel="Recommended"
                    subcopy={result.recommendation_reason}
                  />
                ))}
              </div>
            ) : (
              <div className="retro-panel px-4 py-4 type-body">
                Add a few songs and this section will start surfacing more picks from the same artists.
              </div>
            )}
          </div>
            </div>
          )}

          {activeTab === "timeline" && (
            <div className="space-y-3">
              {project.clips.length === 0 ? (
                <div className="retro-panel px-6 py-16 text-center">
                  <CrtStaticText
                    as="p"
                    text="NO CLIPS YET"
                    textClassName="font-retro text-3xl tracking-[0.2em] text-magenta-soft/85"
                  />
                  <p className="mt-4 type-body">
                    Search and add songs to begin the review flow.
                  </p>
                </div>
              ) : (
                <DndContext
                  sensors={dndSensors}
                  collisionDetection={closestCenter}
                  onDragStart={() => {
                    dragging.current = true;
                  }}
                  onDragCancel={() => {
                    dragging.current = false;
                  }}
                  onDragEnd={handleDragEnd}
                >
                  <SortableContext items={project.clips.map((c) => c.id)} strategy={verticalListSortingStrategy}>
                    <div className="tracklist">
                      {project.clips.map((clip, index) => (
                        <ClipReviewCard
                          key={clip.id}
                          clip={clip}
                          index={index}
                          expanded={expandedClipId === clip.id}
                          analysis={analysisByClip[clip.id]}
                          draft={draftRanges[clip.id]}
                          loadingAnalysis={loadingAnalysis[clip.id] ?? false}
                          saving={savingClipIds[clip.id] ?? false}
                          committing={committingClipIds[clip.id] ?? false}
                          trimError={trimErrors[clip.id] ?? ""}
                          onExpand={() => handleExpandClip(clip)}
                          onDelete={() => handleDeleteClip(clip)}
                          onUseSuggestion={() => handleUseSuggestion(clip)}
                          onSaveDraft={() => handleSaveDraft(clip)}
                          onCommit={() => handleCommitSelection(clip)}
                          onDraftChange={(range) =>
                            setDraftRanges((prev) => ({ ...prev, [clip.id]: range }))
                          }
                        />
                      ))}
                    </div>
                  </SortableContext>
                </DndContext>
              )}
            </div>
          )}

      </div>
    </StudioPage>
  );
}

function SearchResultCard({
  result,
  alreadyAdded,
  onAdd,
  badgeLabel,
  subcopy,
}: {
  result: SearchResult;
  alreadyAdded: boolean;
  onAdd: () => void;
  badgeLabel?: string;
  subcopy?: string;
}) {
  const sourceLabel = formatSearchSourceLabel(result.search_source);

  return (
    <div className="tracklist-row">
      <img
        src={result.thumbnail}
        alt={result.title}
        className="h-12 w-20 shrink-0 object-cover ring-1 ring-phosphor/10 sm:h-16 sm:w-28"
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="truncate font-retro text-lg tracking-[0.12em] text-magenta-text">{result.title}</p>
          {badgeLabel ? <span className="retro-chip retro-chip--info">{badgeLabel}</span> : null}
          {sourceLabel ? <span className="retro-chip retro-chip--pink">{sourceLabel}</span> : null}
        </div>
        <p className="type-body">
          {result.artist}
          {result.duration && ` · ${result.duration}`}
        </p>
        {subcopy ? <p className="mt-1 type-body">{subcopy}</p> : null}
      </div>
      <button
        onClick={onAdd}
        disabled={alreadyAdded}
        className="crt-action retro-button-primary inline-flex shrink-0 items-center gap-2 px-4 py-2 font-retro text-lg tracking-[0.16em] disabled:cursor-not-allowed disabled:opacity-40"
      >
        <Download className="h-3.5 w-3.5" />
        <span className="crt-action__label" data-text={alreadyAdded ? "ADDED" : "ADD"}>
          {alreadyAdded ? "ADDED" : "ADD"}
        </span>
      </button>
    </div>
  );
}

function ClipReviewCard({
  clip,
  index,
  expanded,
  analysis,
  draft,
  loadingAnalysis,
  saving,
  committing,
  trimError,
  onExpand,
  onDelete,
  onUseSuggestion,
  onSaveDraft,
  onCommit,
  onDraftChange,
}: {
  clip: Clip;
  index: number;
  expanded: boolean;
  analysis?: ClipAnalysis;
  draft?: DraftRange;
  loadingAnalysis: boolean;
  saving: boolean;
  committing: boolean;
  trimError: string;
  onExpand: () => void;
  onDelete: () => void;
  onUseSuggestion: () => void;
  onSaveDraft: () => void;
  onCommit: () => void;
  onDraftChange: (range: DraftRange) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: clip.id });
  const dragStyle = { transform: CSS.Transform.toString(transform), transition };
  const videoRef = useRef<HTMLVideoElement>(null);
  const [playhead, setPlayhead] = useState<number | null>(null);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !expanded) return;
    let frame = 0;
    const tick = () => {
      setPlayhead(video.currentTime);
      if (!video.paused && !video.ended) frame = window.requestAnimationFrame(tick);
    };
    const start = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(tick);
    };
    const update = () => setPlayhead(video.currentTime);
    video.addEventListener("play", start);
    video.addEventListener("seeked", update);
    video.addEventListener("loadedmetadata", update);
    return () => {
      window.cancelAnimationFrame(frame);
      video.removeEventListener("play", start);
      video.removeEventListener("seeked", update);
      video.removeEventListener("loadedmetadata", update);
    };
  }, [expanded, loadingAnalysis, clip.preview_url]);
  const selection = draft ?? { start: clip.start_time, end: clip.end_time };
  const maxDuration = analysis?.duration || clip.duration || 0;
  const hasValidSelection = selection.end > selection.start;
  const committedClip = clip.preview_url.includes("/media/clips/");

  function seekVideo(time: number) {
    if (videoRef.current) {
      videoRef.current.currentTime = time;
      videoRef.current.play();
    }
  }

  const statusCopy = {
    pending: "Waiting to download",
    downloading: "Downloading source video",
    analyzing: "Building waveform and recommendations",
    ready: clip.has_selection ? "Selection saved" : "Ready for review",
    error: "Something failed",
  }[clip.status];

  return (
    <div
      ref={setNodeRef}
      style={dragStyle}
      className={clsx(
        "tracklist-row flex-col !items-stretch gap-0 p-0",
        committedClip && "tracklist-row--locked",
        isDragging && "opacity-50"
      )}
    >
      <div className="flex flex-wrap items-center gap-3 p-3 sm:flex-nowrap sm:p-4">
        <button
          {...attributes}
          {...listeners}
          className="-m-2 shrink-0 cursor-grab touch-none p-2 text-phosphor-text/50 hover:text-phosphor-text/80 active:cursor-grabbing"
          aria-label="Drag to reorder"
          tabIndex={-1}
        >
          <GripVertical className="h-5 w-5" />
        </button>
        <span className="tracklist-row__num">{String(index + 1).padStart(2, "0")}</span>

        {clip.source_thumbnail ? (
          <img
            src={clip.source_thumbnail}
            alt={clip.source_title}
            className="hidden h-14 w-24 shrink-0 object-cover ring-1 ring-phosphor/10 sm:block"
          />
        ) : (
          <div className="hidden h-14 w-24 shrink-0 items-center justify-center bg-crt-panel sm:flex">
            <Play className="h-4 w-4 text-phosphor-text/50" />
          </div>
        )}

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-retro text-lg tracking-[0.12em] text-magenta-text max-sm:line-clamp-2 sm:truncate">{clip.source_title}</p>
            {committedClip && (
              <span className="retro-chip retro-chip--ok">
                <CheckCircle2 className="h-3 w-3" />
                Clipped
              </span>
            )}
            {clip.file_missing && (
              <span className="retro-chip retro-chip--error">⚠ File Missing</span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2 font-mono text-sm uppercase tracking-[0.14em] text-phosphor-text/70">
            <span>{clip.source_artist}</span>
            {clip.bpm && <span>· {Math.round(clip.bpm)} BPM</span>}
            <span>· {statusCopy}</span>
          </div>
        </div>

        {clip.has_selection && (
          <>
            <span className="tracklist-row__leader hidden sm:block" />
            <span className="tracklist-row__time max-sm:hidden">
              {formatTime(clip.start_time)}–{formatTime(clip.end_time)}
            </span>
          </>
        )}

        <div className="flex items-center gap-2 max-sm:w-full max-sm:justify-end">
        {clip.has_selection && (
          <span className="tracklist-row__time mr-auto sm:hidden">
            {formatTime(clip.start_time)}–{formatTime(clip.end_time)}
          </span>
        )}
        {clip.status === "ready" && !committedClip && (
          <button
            onClick={onExpand}
            className="crt-action retro-button-secondary inline-flex items-center gap-2 px-3 py-2 font-retro text-lg tracking-[0.16em]"
          >
            <ChevronDown className={clsx("h-4 w-4 transition-transform", expanded && "rotate-180")} />
            <span
              className="crt-action__label"
              data-text={clip.has_selection ? "EDIT REVIEW" : "OPEN REVIEW"}
            >
              {clip.has_selection ? "EDIT REVIEW" : "OPEN REVIEW"}
            </span>
          </button>
        )}

        <button
          onClick={onDelete}
          className="icon-button icon-button--danger shrink-0"
          aria-label={`Remove ${clip.source_title}`}
          title="Remove clip"
        >
          <Trash2 className="h-4 w-4" />
        </button>
        </div>
      </div>

      {clip.status !== "ready" && (
        <p className="px-4 pb-4 type-body">
          {clip.status === "error" ? clip.source_title + " failed to process." : statusCopy}
        </p>
      )}

      {clip.status === "ready" && committedClip && (
        <p className="px-4 pb-4 type-body">
          This clip is already trimmed. Replace or delete it to change the song selection.
        </p>
      )}

      {clip.status === "ready" && !expanded && !clip.has_selection && (
        <p className="px-4 pb-4 type-body">
          Analysis is ready. Click Open Review to see the waveform and choose a range.
        </p>
      )}

      {expanded && clip.status === "ready" && (
        <div className="retro-tray">
          {loadingAnalysis ? (
            <div className="flex h-56 items-center justify-center text-phosphor-text/60">
              <Spinner className="mr-2 h-4 w-4" />
              Loading analysis...
            </div>
          ) : (
            <div>
              <div className="mb-4 flex flex-col gap-3 border-b border-phosphor/10 pb-4 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <p className="font-retro text-lg tracking-[0.18em] text-zinc-200">TRIM ON THE WAVEFORM</p>
                  <p className="mt-1 type-body">
                    Drag the left or right edge of the selection window to choose the exact clip length.
                  </p>
                </div>
                {analysis && (
                  <button
                    onClick={onUseSuggestion}
                    disabled={saving}
                    className="crt-action retro-button-secondary inline-flex items-center gap-2 px-3 py-2 font-retro text-lg tracking-[0.16em]"
                  >
                    {saving ? (
                      <Spinner className="h-3.5 w-3.5" />
                    ) : (
                      <Sparkles className="h-3.5 w-3.5" />
                    )}
                    <span className="crt-action__label" data-text="USE RECOMMENDATION">
                      USE RECOMMENDATION
                    </span>
                  </button>
                )}
              </div>

              <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[1.05fr_0.95fr]">
                <div className="space-y-3">
                  {clip.preview_url && (
                    <video
                      ref={videoRef}
                      src={clip.preview_url}
                      controls
                      playsInline
                      preload="metadata"
                      className="w-full rounded-bezel border border-phosphor/12 bg-black"
                    />
                  )}
                  <div className="border border-phosphor/10 bg-crt-panel/90 p-3 type-body">
                    <div className="flex items-center justify-between">
                      <span>Chosen range</span>
                      <span className="font-mono text-zinc-200">
                        {formatTime(selection.start)} to {formatTime(selection.end)}
                      </span>
                    </div>
                    <div className="mt-1 flex items-center justify-between">
                      <span>Selection length</span>
                      <span className="font-mono text-zinc-200">
                        {formatTime(Math.max(selection.end - selection.start, 0))}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="space-y-4">
                  <WaveformRangeEditor
                    waveform={analysis?.waveform ?? []}
                    highlights={analysis?.highlights ?? []}
                    duration={maxDuration}
                    selection={selection}
                    onSeek={seekVideo}
                    playhead={playhead}
                    onChange={onDraftChange}
                  />

                  {analysis?.highlights?.length ? (
                    <div className="flex flex-wrap gap-2">
                      {analysis.highlights.map((highlight) => (
                        <button
                          key={`${highlight.start}-${highlight.end}`}
                          onClick={() => {
                            onDraftChange({ start: highlight.start, end: highlight.end });
                            seekVideo(highlight.start);
                          }}
                          className="retro-chip retro-chip--info transition-colors hover:border-magenta/40 hover:text-magenta-pale"
                        >
                          {highlight.label}: {formatTime(highlight.start)} to {formatTime(highlight.end)}
                        </button>
                      ))}
                    </div>
                  ) : null}

                  <div className="flex flex-wrap gap-2">
                    <button
                      onClick={onSaveDraft}
                      disabled={!hasValidSelection || saving}
                      className="crt-action retro-button-secondary inline-flex items-center gap-2 px-3 py-2 font-retro text-lg tracking-[0.16em] disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      {saving ? <Spinner className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
                      <span className="crt-action__label" data-text="SAVE RANGE">
                        SAVE RANGE
                      </span>
                    </button>
                    <button
                      onClick={onCommit}
                      disabled={!hasValidSelection || committing || saving || committedClip}
                      className={committedClip
                        ? "inline-flex items-center gap-2 px-3 py-2 font-retro text-lg tracking-[0.16em] border border-status-ok/30 bg-status-ok/5 text-status-ok/70 cursor-not-allowed"
                        : "crt-action retro-button-warn inline-flex items-center gap-2 px-3 py-2 font-retro text-lg tracking-[0.16em] disabled:cursor-not-allowed disabled:opacity-40"
                      }
                    >
                      {committing ? (
                        <Spinner className="h-3.5 w-3.5" />
                      ) : (
                        <Scissors className="h-3.5 w-3.5" />
                      )}
                      <span className="crt-action__label" data-text={committedClip ? "CLIP TRIMMED!" : "TRIM AND DISCARD FULL VIDEO"}>
                        {committedClip ? "CLIP TRIMMED!" : "TRIM AND DISCARD FULL VIDEO"}
                      </span>
                    </button>
                  </div>

                  {trimError ? (
                    <div className="osd-notice osd-notice--warn" role="alert">
                      <p className="osd-notice__title">TRIM NOT DONE</p>
                      <p className="type-body mt-1 !text-inherit">{trimError}</p>
                    </div>
                  ) : null}

                  <p className="type-body">
                    Saving keeps your chosen timestamps. Trimming creates the final clip file and frees the original download.
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
