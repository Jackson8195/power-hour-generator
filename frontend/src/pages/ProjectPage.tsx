import { useEffect, useState, useCallback, useRef } from "react";
import { useParams } from "react-router-dom";
import {
  Search,
  Download,
  Trash2,
  Play,
  Sparkles,
  Tv,
  Loader2,
  GripVertical,
  ChevronDown,
  Scissors,
  CheckCircle2,
} from "lucide-react";
import type {
  Clip,
  ClipAnalysis,
  ProjectDetail,
  RenderProgress,
  SearchResult,
} from "../utils/types";
import {
  addClip,
  commitClipSelection,
  connectRenderWs,
  deleteClip,
  getClipAnalysis,
  getRecommendedTracks,
  getProject,
  searchYouTube,
  startDownload,
  startRender,
  updateClip,
  useSuggestedSegment,
} from "../utils/api";
import clsx from "clsx";
import CrtStaticText from "../components/CrtStaticText";

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
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [recommendedResults, setRecommendedResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [loadingRecommendations, setLoadingRecommendations] = useState(false);
  const [renderProgress, setRenderProgress] = useState<RenderProgress | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"search" | "timeline">("search");
  const [expandedClipId, setExpandedClipId] = useState<number | null>(null);
  const [analysisByClip, setAnalysisByClip] = useState<Record<number, ClipAnalysis>>({});
  const [loadingAnalysis, setLoadingAnalysis] = useState<Record<number, boolean>>({});
  const [draftRanges, setDraftRanges] = useState<Record<number, DraftRange>>({});
  const [savingClipIds, setSavingClipIds] = useState<Record<number, boolean>>({});
  const [committingClipIds, setCommittingClipIds] = useState<Record<number, boolean>>({});

  const loadProject = useCallback(async () => {
    try {
      const data = await getProject(projectId);
      setProject(data);
      setDraftRanges((prev) => {
        const next = { ...prev };
        for (const clip of data.clips) {
          if (!(clip.id in next) || clip.has_selection) {
            next[clip.id] = {
              start: clip.start_time,
              end: clip.end_time,
            };
          }
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

  useEffect(() => {
    const pendingClips = project?.clips.filter(
      (c) => c.status === "downloading" || c.status === "analyzing"
    );
    if (!pendingClips?.length) return;

    const interval = setInterval(loadProject, 3000);
    return () => clearInterval(interval);
  }, [project, loadProject]);

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
      const results = await searchYouTube(searchQuery, 10, projectId);
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

  async function handleDeleteClip(clipId: number) {
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

    setCommittingClipIds((prev) => ({ ...prev, [clip.id]: true }));
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
      console.error("Failed to commit clip selection:", err);
    } finally {
      setCommittingClipIds((prev) => ({ ...prev, [clip.id]: false }));
    }
  }

  async function handleStartRender() {
    setRenderError(null);
    try {
      const { render_id } = await startRender(projectId);
      const ws = connectRenderWs(render_id, (data) => {
        setRenderProgress(data);
        if (data.status === "complete" || data.status === "error") {
          ws.close();
        }
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Render failed";
      setRenderError(msg);
    }
  }

  if (!project) {
    return (
      <div className="retro-panel rounded-[22px] px-6 py-16 text-center">
        <CrtStaticText
          as="p"
          text="LOADING PROJECT..."
          textClassName="animate-pulse font-retro text-2xl tracking-[0.22em] text-[#91fff2]/70"
        />
      </div>
    );
  }

  const reviewedClips = project.clips.filter((c) => c.has_selection);

  return (
    <div className="relative min-h-[calc(100vh-7rem)] overflow-hidden rounded-[28px] bg-[#070b10] px-4 py-6 scanlines sm:px-6">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(255,43,157,0.12),transparent_24%),radial-gradient(circle_at_bottom_right,rgba(26,255,228,0.08),transparent_26%)]" />

      <section className="retro-shell relative mx-auto max-w-7xl rounded-[28px] px-5 py-6 sm:px-8 sm:py-8">
        <div className="relative z-10">
          <div className="mb-6 flex flex-col gap-5 border-b border-[rgba(26,255,228,0.14)] pb-6 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <p className="font-retro text-xs tracking-[0.45em] text-[#1affe4]/60">
                EDIT MIXTAPE
              </p>
              <CrtStaticText
                as="h1"
                text={project.name.toUpperCase()}
                className="mt-2"
                textClassName="font-retro text-3xl tracking-[0.22em] text-[#ff77c2] glow-text sm:text-5xl"
              />
              <p className="mt-3 font-mono text-sm uppercase tracking-[0.18em] text-[#91fff2]/45">
                {reviewedClips.length} of {project.clips.length} clips have a locked-in range.
              </p>
            </div>
            <button
              onClick={handleStartRender}
              disabled={reviewedClips.length === 0 || renderProgress?.status === "rendering"}
              className="crt-action retro-button-primary inline-flex items-center justify-center gap-3 rounded-xl px-5 py-3 font-retro text-lg tracking-[0.18em] transition-all duration-150 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {renderProgress?.status === "rendering" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Play className="h-4 w-4" />
              )}
              <span className="crt-action__label" data-text="RENDER VIDEO">
                RENDER VIDEO
              </span>
            </button>
          </div>

          {renderError && (
            <div className="retro-panel mb-6 rounded-[22px] p-5">
              <p className="font-retro text-sm tracking-[0.18em] text-red-400">RENDER FAILED</p>
              <p className="mt-2 font-mono text-xs tracking-[0.14em] text-[#ffb6dd]/80">{renderError}</p>
            </div>
          )}

          {renderProgress && (
            <div className="retro-panel mb-6 rounded-[22px] p-5">
              <div className="relative z-10">
                <div className="mb-3 flex items-center justify-between">
                  <p className="font-retro text-sm tracking-[0.18em] text-[#91fff2]">
                    {renderProgress.status === "rendering"
                      ? "RENDERING..."
                      : renderProgress.status === "complete"
                        ? "RENDER COMPLETE"
                        : `STATUS: ${renderProgress.status.toUpperCase()}`}
                  </p>
                  <span className="font-mono text-sm text-[#ffb6dd]/75">
                    {Math.round(renderProgress.progress)}%
                  </span>
                </div>
                <div className="retro-progress h-2 overflow-hidden rounded-full">
                  <div
                    className={clsx(
                      "h-full rounded-full transition-all",
                      renderProgress.status === "complete"
                        ? "bg-green-500"
                        : renderProgress.status === "error"
                          ? "bg-red-500"
                          : "retro-progress__bar"
                    )}
                    style={{ width: `${renderProgress.progress}%` }}
                  />
                </div>
                {renderProgress.status === "rendering" && (
                  <p className="mt-4 font-mono text-xs uppercase tracking-[0.16em] text-[#91fff2]/45">
                    Estimated time 12 minutes. So this should take about 5 or 10 minutes.
                  </p>
                )}
                {renderProgress.status === "complete" && renderProgress.output_path && (
                  <div className="mt-4 flex flex-wrap gap-3">
                    <a
                      href={renderProgress.output_path}
                      target="_blank"
                      className="crt-action retro-button-secondary inline-flex items-center gap-2 rounded-xl px-4 py-2 font-retro text-sm tracking-[0.16em]"
                      rel="noreferrer"
                    >
                      <Play className="h-3.5 w-3.5" />
                      <span className="crt-action__label" data-text="WATCH">
                        WATCH
                      </span>
                    </a>
                    <button className="crt-action retro-button-secondary inline-flex items-center gap-2 rounded-xl px-4 py-2 font-retro text-sm tracking-[0.16em]">
                      <Tv className="h-3.5 w-3.5" />
                      <span className="crt-action__label" data-text="CAST TO TV">
                        CAST TO TV
                      </span>
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="mb-5 flex flex-wrap gap-3">
            <button
              onClick={() => setActiveTab("search")}
              className={clsx(
                "crt-action rounded-xl border px-4 py-2.5 font-retro text-sm tracking-[0.16em] transition-all",
                activeTab === "search"
                  ? "border-[#ff2b9d]/40 bg-[#2b0b1d] text-[#ffd7eb] shadow-[0_0_18px_rgba(255,43,157,0.16)]"
                  : "border-[#1affe4]/14 bg-[#08131a] text-[#91fff2]/70 hover:border-[#1affe4]/28 hover:text-[#defffb]"
              )}
            >
              <span className="inline-flex items-center gap-2">
                <Search className="h-4 w-4" />
                <span className="crt-action__label" data-text="SEARCH & ADD">
                  SEARCH & ADD
                </span>
              </span>
            </button>
            <button
              onClick={() => setActiveTab("timeline")}
              className={clsx(
                "crt-action rounded-xl border px-4 py-2.5 font-retro text-sm tracking-[0.16em] transition-all",
                activeTab === "timeline"
                  ? "border-[#ff2b9d]/40 bg-[#2b0b1d] text-[#ffd7eb] shadow-[0_0_18px_rgba(255,43,157,0.16)]"
                  : "border-[#1affe4]/14 bg-[#08131a] text-[#91fff2]/70 hover:border-[#1affe4]/28 hover:text-[#defffb]"
              )}
            >
              <span className="inline-flex items-center gap-2">
                <GripVertical className="h-4 w-4" />
                <span className="crt-action__label" data-text={`REVIEW CLIPS (${project.clips.length})`}>
                  REVIEW CLIPS ({project.clips.length})
                </span>
              </span>
            </button>
          </div>

          {activeTab === "search" && (
            <div>
          <form onSubmit={handleSearch} className="mb-4 flex gap-2">
            <input
              type="text"
              className="retro-input w-full rounded-xl px-4 py-3 font-mono text-sm tracking-[0.12em]"
              placeholder="Search for music videos..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            <button
              type="submit"
              disabled={searching}
              className="crt-action retro-button-primary inline-flex shrink-0 items-center gap-2 rounded-xl px-4 py-3 font-retro text-sm tracking-[0.16em] disabled:cursor-not-allowed disabled:opacity-40"
            >
              {searching ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Search className="h-4 w-4" />
              )}
              <span className="crt-action__label" data-text="SEARCH">
                SEARCH
              </span>
            </button>
          </form>

          {searchResults.length > 0 && (
            <div className="mb-6 space-y-2">
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
                <p className="font-retro text-sm tracking-[0.18em] text-zinc-200">RECOMMENDED NEXT PICKS</p>
                <p className="font-mono text-xs uppercase tracking-[0.14em] text-[#91fff2]/45">
                  Suggestions update from the artists already showing up in this project.
                </p>
              </div>
              {loadingRecommendations && (
                <div className="font-retro text-xs tracking-[0.16em] text-[#91fff2]/60">
                  <Loader2 className="inline h-3.5 w-3.5 animate-spin" /> Refreshing
                </div>
              )}
            </div>

            {recommendedResults.length > 0 ? (
              <div className="space-y-2">
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
              <div className="retro-panel rounded-[18px] px-4 py-4 font-mono text-sm uppercase tracking-[0.14em] text-[#91fff2]/45">
                Add a few songs and this section will start surfacing more picks from the same artists.
              </div>
            )}
          </div>
            </div>
          )}

          {activeTab === "timeline" && (
            <div className="space-y-3">
          {project.clips.length === 0 ? (
            <div className="retro-panel rounded-[22px] px-6 py-16 text-center">
              <CrtStaticText
                as="p"
                text="NO CLIPS YET"
                textClassName="font-retro text-3xl tracking-[0.2em] text-[#ff77c2]/85"
              />
              <p className="mt-4 font-mono text-sm uppercase tracking-[0.18em] text-[#91fff2]/45">
                Search and add songs to begin the review flow.
              </p>
            </div>
          ) : (
            project.clips.map((clip, index) => (
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
                onExpand={() => handleExpandClip(clip)}
                onDelete={() => handleDeleteClip(clip.id)}
                onUseSuggestion={() => handleUseSuggestion(clip)}
                onSaveDraft={() => handleSaveDraft(clip)}
                onCommit={() => handleCommitSelection(clip)}
                onDraftChange={(range) =>
                  setDraftRanges((prev) => ({ ...prev, [clip.id]: range }))
                }
              />
            ))
          )}
            </div>
          )}
        </div>
      </section>
    </div>
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
    <div className="retro-project-card flex items-center gap-4 rounded-[20px] p-4">
      <img
        src={result.thumbnail}
        alt={result.title}
        className="h-16 w-28 shrink-0 rounded-lg object-cover ring-1 ring-[#1affe4]/10"
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="truncate font-retro text-base tracking-[0.12em] text-[#ffb6dd]">{result.title}</p>
          {badgeLabel ? (
            <span className="rounded-full border border-[#1affe4]/14 bg-[#08141b] px-2 py-0.5 font-retro text-[10px] uppercase tracking-[0.18em] text-[#91fff2]/70">
              {badgeLabel}
            </span>
          ) : null}
          {sourceLabel ? (
            <span className="rounded-full border border-[#ff77c2]/18 bg-[#140913] px-2 py-0.5 font-retro text-[10px] uppercase tracking-[0.18em] text-[#ffb6dd]/80">
              {sourceLabel}
            </span>
          ) : null}
        </div>
        <p className="font-mono text-xs uppercase tracking-[0.14em] text-[#91fff2]/55">
          {result.artist}
          {result.duration && ` · ${result.duration}`}
        </p>
        {subcopy ? <p className="mt-1 font-mono text-xs uppercase tracking-[0.12em] text-[#91fff2]/35">{subcopy}</p> : null}
      </div>
      <button
        onClick={onAdd}
        disabled={alreadyAdded}
        className="crt-action retro-button-primary inline-flex shrink-0 items-center gap-2 rounded-xl px-4 py-2 font-retro text-xs tracking-[0.16em] disabled:cursor-not-allowed disabled:opacity-40"
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
  onExpand: () => void;
  onDelete: () => void;
  onUseSuggestion: () => void;
  onSaveDraft: () => void;
  onCommit: () => void;
  onDraftChange: (range: DraftRange) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
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
      className={clsx(
        "retro-project-card overflow-hidden rounded-[22px] p-4",
        committedClip && "border-l-2 border-l-green-500"
      )}
    >
      <div className="flex items-center gap-3">
        <div className="flex w-8 shrink-0 items-center justify-center">
          <span className="font-retro text-xs tracking-[0.2em] text-[#91fff2]/45">{index + 1}</span>
        </div>

        {clip.source_thumbnail ? (
          <img
            src={clip.source_thumbnail}
            alt={clip.source_title}
            className="h-14 w-24 shrink-0 rounded-lg object-cover ring-1 ring-[#1affe4]/10"
          />
        ) : (
          <div className="flex h-14 w-24 shrink-0 items-center justify-center rounded-lg bg-[#08131a]">
            <Play className="h-4 w-4 text-zinc-600" />
          </div>
        )}

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="truncate font-retro text-base tracking-[0.12em] text-[#ffb6dd]">{clip.source_title}</p>
            {committedClip && (
              <span className="flex shrink-0 items-center gap-1 rounded-full bg-green-500/15 px-2 py-0.5 font-retro text-[10px] uppercase tracking-[0.18em] text-green-400">
                <CheckCircle2 className="h-3 w-3" />
                Clipped
              </span>
            )}
            {clip.file_missing && (
              <span className="flex shrink-0 items-center gap-1 rounded-full bg-red-500/20 px-2 py-0.5 font-retro text-[10px] uppercase tracking-[0.18em] text-red-400">
                ⚠ File Missing
              </span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2 font-mono text-xs uppercase tracking-[0.14em] text-[#91fff2]/45">
            <span>{clip.source_artist}</span>
            {clip.bpm && <span>· {Math.round(clip.bpm)} BPM</span>}
            <span>· {statusCopy}</span>
            {clip.has_selection && (
              <span>
                · {formatTime(clip.start_time)} to {formatTime(clip.end_time)}
              </span>
            )}
          </div>
        </div>

        {clip.status === "ready" && !committedClip && (
          <button
            onClick={onExpand}
            className="crt-action retro-button-secondary inline-flex items-center gap-2 rounded-xl px-3 py-2 font-retro text-xs tracking-[0.16em]"
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
          className="rounded-lg p-1.5 text-zinc-600 transition-colors hover:bg-red-500/10 hover:text-red-300"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>

      {clip.status !== "ready" && (
        <div className="mt-3 rounded-xl border border-[#1affe4]/10 bg-[#08131a]/90 px-3 py-3 font-mono text-xs uppercase tracking-[0.14em] text-[#91fff2]/45">
          {clip.status === "error" ? clip.source_title + " failed to process." : statusCopy}
        </div>
      )}

      {clip.status === "ready" && committedClip && (
        <div className="mt-3 rounded-xl border border-[#1affe4]/10 bg-[#08131a]/90 px-3 py-3 font-mono text-xs uppercase tracking-[0.14em] text-[#91fff2]/45">
          This clip is already trimmed. Replace or delete it to change the song selection.
        </div>
      )}

      {clip.status === "ready" && !expanded && !clip.has_selection && (
        <div className="mt-3 rounded-xl border border-[#1affe4]/10 bg-[#08131a]/90 px-3 py-3 font-mono text-xs uppercase tracking-[0.14em] text-[#91fff2]/45">
          Analysis is ready. Click Open Review to see the waveform and choose a range.
        </div>
      )}

      {expanded && clip.status === "ready" && (
        <div className="mt-4">
          {loadingAnalysis ? (
            <div className="retro-panel flex h-56 items-center justify-center rounded-[22px] text-[#91fff2]/55">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Loading analysis...
            </div>
          ) : (
            <div className="retro-panel rounded-[22px] p-4">
              <div className="mb-4 flex flex-col gap-3 border-b border-[#1affe4]/10 pb-4 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <p className="font-retro text-sm tracking-[0.18em] text-zinc-200">TRIM ON THE WAVEFORM</p>
                  <p className="mt-1 font-mono text-xs uppercase tracking-[0.14em] text-[#91fff2]/45">
                    Drag the left or right edge of the selection window to choose the exact clip length.
                  </p>
                </div>
                {analysis && (
                  <button
                    onClick={onUseSuggestion}
                    disabled={saving}
                    className="crt-action retro-button-secondary inline-flex items-center gap-2 rounded-xl px-3 py-2 font-retro text-xs tracking-[0.16em]"
                  >
                    {saving ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Sparkles className="h-3.5 w-3.5" />
                    )}
                    <span className="crt-action__label" data-text="USE RECOMMENDATION">
                      USE RECOMMENDATION
                    </span>
                  </button>
                )}
              </div>

              <div className="grid gap-4 lg:grid-cols-[1.05fr_0.95fr]">
                <div className="space-y-3">
                  {clip.preview_url && (
                    <video
                      ref={videoRef}
                      src={clip.preview_url}
                      controls
                      preload="metadata"
                      className="w-full rounded-[22px] border border-[#1affe4]/12 bg-black"
                    />
                  )}
                  <div className="rounded-xl border border-[#1affe4]/10 bg-[#08131a]/90 p-3 font-mono text-xs uppercase tracking-[0.14em] text-[#91fff2]/45">
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
                          className="rounded-full border border-[#1affe4]/14 bg-[#08131a] px-3 py-1 font-retro text-xs tracking-[0.14em] text-[#91fff2]/70 transition-colors hover:border-[#ff2b9d]/30 hover:text-[#ffd7eb]"
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
                      className="crt-action retro-button-secondary inline-flex items-center gap-2 rounded-xl px-3 py-2 font-retro text-xs tracking-[0.16em] disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
                      <span className="crt-action__label" data-text="SAVE RANGE">
                        SAVE RANGE
                      </span>
                    </button>
                    <button
                      onClick={onCommit}
                      disabled={!hasValidSelection || committing || saving}
                      className="crt-action retro-button-primary inline-flex items-center gap-2 rounded-xl px-3 py-2 font-retro text-xs tracking-[0.16em] disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      {committing ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Scissors className="h-3.5 w-3.5" />
                      )}
                      <span className="crt-action__label" data-text="TRIM AND DISCARD FULL VIDEO">
                        TRIM AND DISCARD FULL VIDEO
                      </span>
                    </button>
                  </div>

                  <p className="font-mono text-xs uppercase tracking-[0.12em] text-[#91fff2]/40">
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

function WaveformRangeEditor({
  waveform,
  highlights,
  duration,
  selection,
  onSeek,
  onChange,
}: {
  waveform: number[];
  highlights: ClipAnalysis["highlights"];
  duration: number;
  selection: DraftRange;
  onSeek?: (time: number) => void;
  onChange: (range: DraftRange) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const dragStateRef = useRef<"start" | "end" | null>(null);
  const minSelection = 0.5;

  useEffect(() => {
    function handlePointerMove(event: PointerEvent) {
      if (!dragStateRef.current || !containerRef.current || !duration) return;
      const rect = containerRef.current.getBoundingClientRect();
      const ratio = Math.max(0, Math.min((event.clientX - rect.left) / rect.width, 1));
      const nextTime = ratio * duration;

      if (dragStateRef.current === "start") {
        onChange({
          start: Math.min(nextTime, Math.max(selection.end - minSelection, 0)),
          end: selection.end,
        });
      } else {
        onChange({
          start: selection.start,
          end: Math.max(nextTime, selection.start + minSelection),
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
  }, [duration, onChange, selection.end, selection.start]);

  function handleWaveformClick(e: React.MouseEvent<HTMLDivElement>) {
    if (!duration || !onSeek) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const ratio = (e.clientX - rect.left) / rect.width;
    onSeek(Math.max(0, Math.min(ratio * duration, duration)));
  }

  return (
    <div
      ref={containerRef}
      className={clsx(
        "relative overflow-hidden rounded-[20px] border border-[#1affe4]/12 bg-gradient-to-b from-[#08131b] to-[#050c12] px-3 py-5",
        onSeek && "cursor-pointer"
      )}
      onClick={handleWaveformClick}
      title={onSeek ? "Click to seek video" : undefined}
    >
      <div className="mb-4 flex items-center justify-between">
        <div>
          <p className="font-retro text-sm tracking-[0.18em] text-zinc-200">WAVEFORM RANGE</p>
          <p className="font-mono text-xs uppercase tracking-[0.14em] text-[#91fff2]/45">
            Drag either edge of the pink window to trim.
          </p>
        </div>
        <div className="rounded-full border border-[#ff77c2]/18 bg-[#150913] px-3 py-1 font-retro text-xs tracking-[0.18em] text-[#ffb6dd]">
          {formatTime(Math.max(selection.end - selection.start, 0))}
        </div>
      </div>

      <div className="pointer-events-none absolute inset-0">
        {selection.end > selection.start && (
          <div
            className="absolute inset-y-[54px] rounded-lg border border-[#ff77c2]/75 bg-[#ff2b9d]/12"
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
            className="absolute inset-y-[54px] rounded-lg bg-[#1affe4]/10 transition-colors hover:bg-[#1affe4]/20"
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

      <div className="pointer-events-none relative flex h-28 items-end gap-[2px]">
        {(waveform.length ? waveform : new Array(80).fill(0.15)).map((bar, index) => (
          <div
            key={`${index}-${bar}`}
            className="flex-1 rounded-full bg-[#91fff2]/75"
            style={{ height: `${Math.max(bar * 100, 8)}%` }}
          />
        ))}
      </div>

      {duration > 0 && selection.end > selection.start ? (
        <>
          <button
            type="button"
            onPointerDown={(event) => {
              event.stopPropagation();
              dragStateRef.current = "start";
            }}
            className="absolute inset-y-[54px] z-10 w-4 -translate-x-1/2 cursor-ew-resize rounded-full border border-[#ffd7eb]/70 bg-[#ff77c2] shadow-[0_0_18px_rgba(255,119,194,0.55)]"
            style={{ left: `${(selection.start / duration) * 100}%` }}
            aria-label="Drag selection start"
          />
          <button
            type="button"
            onPointerDown={(event) => {
              event.stopPropagation();
              dragStateRef.current = "end";
            }}
            className="absolute inset-y-[54px] z-10 w-4 -translate-x-1/2 cursor-ew-resize rounded-full border border-[#ffd7eb]/70 bg-[#ff77c2] shadow-[0_0_18px_rgba(255,119,194,0.55)]"
            style={{ left: `${(selection.end / duration) * 100}%` }}
            aria-label="Drag selection end"
          />
        </>
      ) : null}

      <div className="mt-4 flex items-center justify-between font-mono text-[11px] uppercase tracking-[0.14em] text-[#91fff2]/45">
        <span>0:00</span>
        <span>{formatTime(duration)}</span>
      </div>
    </div>
  );
}

function formatTime(seconds: number): string {
  const safeSeconds = Math.max(0, Math.floor(seconds));
  const m = Math.floor(safeSeconds / 60);
  const s = safeSeconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}
