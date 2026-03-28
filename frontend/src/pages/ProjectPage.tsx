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

type DraftRange = { start: number; end: number };

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
    try {
      const { render_id } = await startRender(projectId);
      const ws = connectRenderWs(render_id, (data) => {
        setRenderProgress(data);
        if (data.status === "complete" || data.status === "error") {
          ws.close();
        }
      });
    } catch (err) {
      console.error("Render failed:", err);
    }
  }

  if (!project) {
    return <div className="py-20 text-center text-zinc-500">Loading project...</div>;
  }

  const reviewedClips = project.clips.filter((c) => c.has_selection);

  return (
    <div>
      <div className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold text-zinc-100">{project.name}</h1>
          <p className="mt-1 text-sm text-zinc-500">
            {reviewedClips.length} / {project.clips.length} clips have a selected range
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleStartRender}
            disabled={reviewedClips.length === 0 || renderProgress?.status === "rendering"}
            className="btn-primary"
          >
            {renderProgress?.status === "rendering" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Play className="h-4 w-4" />
            )}
            Render Video
          </button>
        </div>
      </div>

      {renderProgress && (
        <div className="card mb-6">
          <div className="mb-2 flex items-center justify-between text-sm">
            <span className="text-zinc-400">
              {renderProgress.status === "rendering"
                ? "Rendering..."
                : renderProgress.status === "complete"
                  ? "Render complete!"
                  : `Status: ${renderProgress.status}`}
            </span>
            <span className="font-mono text-zinc-500">
              {Math.round(renderProgress.progress)}%
            </span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-zinc-800">
            <div
              className={clsx(
                "h-full rounded-full transition-all",
                renderProgress.status === "complete"
                  ? "bg-green-500"
                  : renderProgress.status === "error"
                    ? "bg-red-500"
                    : "bg-brand-500"
              )}
              style={{ width: `${renderProgress.progress}%` }}
            />
          </div>
          {renderProgress.status === "complete" && renderProgress.output_path && (
            <div className="mt-3 flex gap-2">
              <a
                href={`/static/renders/${renderProgress.output_path.split("/").pop()}`}
                target="_blank"
                className="btn-secondary text-xs"
                rel="noreferrer"
              >
                <Play className="h-3.5 w-3.5" />
                Watch
              </a>
              <button className="btn-secondary text-xs">
                <Tv className="h-3.5 w-3.5" />
                Cast to TV
              </button>
            </div>
          )}
        </div>
      )}

      <div className="mb-4 flex gap-1 border-b border-zinc-800">
        <button
          onClick={() => setActiveTab("search")}
          className={clsx(
            "px-4 py-2 text-sm font-medium transition-colors",
            activeTab === "search"
              ? "border-b-2 border-brand-500 text-zinc-100"
              : "text-zinc-500 hover:text-zinc-300"
          )}
        >
          <Search className="mr-1.5 inline h-4 w-4" />
          Search & Add
        </button>
        <button
          onClick={() => setActiveTab("timeline")}
          className={clsx(
            "px-4 py-2 text-sm font-medium transition-colors",
            activeTab === "timeline"
              ? "border-b-2 border-brand-500 text-zinc-100"
              : "text-zinc-500 hover:text-zinc-300"
          )}
        >
          <GripVertical className="mr-1.5 inline h-4 w-4" />
          Review Clips ({project.clips.length})
        </button>
      </div>

      {activeTab === "search" && (
        <div>
          <form onSubmit={handleSearch} className="mb-4 flex gap-2">
            <input
              type="text"
              className="input-field"
              placeholder="Search for music videos..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            <button type="submit" disabled={searching} className="btn-primary shrink-0">
              {searching ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Search className="h-4 w-4" />
              )}
              Search
            </button>
          </form>

          <div className="mb-6">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-zinc-200">Recommended next picks</p>
                <p className="text-xs text-zinc-500">
                  Suggestions update from the artists already showing up in this project.
                </p>
              </div>
              {loadingRecommendations && (
                <div className="text-xs text-zinc-500">
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
              <div className="rounded-xl border border-zinc-800 bg-zinc-950/40 px-4 py-3 text-sm text-zinc-500">
                Add a few songs and this section will start surfacing more picks from the same artists.
              </div>
            )}
          </div>

          <div className="space-y-2">
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
        </div>
      )}

      {activeTab === "timeline" && (
        <div className="space-y-3">
          {project.clips.length === 0 ? (
            <div className="py-16 text-center text-zinc-500">
              No clips yet. Search and add songs to get started!
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
  return (
    <div className="card flex items-center gap-4">
      <img
        src={result.thumbnail}
        alt={result.title}
        className="h-16 w-28 shrink-0 rounded object-cover"
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="truncate text-sm font-medium text-zinc-100">{result.title}</p>
          {badgeLabel ? (
            <span className="rounded-full border border-zinc-700 px-2 py-0.5 text-[10px] uppercase tracking-wide text-zinc-400">
              {badgeLabel}
            </span>
          ) : null}
        </div>
        <p className="text-xs text-zinc-500">
          {result.artist}
          {result.duration && ` · ${result.duration}`}
        </p>
        {subcopy ? <p className="mt-1 text-xs text-zinc-600">{subcopy}</p> : null}
      </div>
      <button
        onClick={onAdd}
        disabled={alreadyAdded}
        className="btn-primary shrink-0 text-xs"
      >
        <Download className="h-3.5 w-3.5" />
        {alreadyAdded ? "Added" : "Add"}
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
    <div className={clsx("card overflow-hidden", committedClip && "border-l-2 border-l-green-500")}>
      <div className="flex items-center gap-3">
        <div className="flex w-8 shrink-0 items-center justify-center">
          <span className="font-mono text-xs text-zinc-600">{index + 1}</span>
        </div>

        {clip.source_thumbnail ? (
          <img
            src={clip.source_thumbnail}
            alt={clip.source_title}
            className="h-14 w-24 shrink-0 rounded object-cover"
          />
        ) : (
          <div className="flex h-14 w-24 shrink-0 items-center justify-center rounded bg-zinc-800">
            <Play className="h-4 w-4 text-zinc-600" />
          </div>
        )}

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="truncate text-sm font-medium text-zinc-100">{clip.source_title}</p>
            {committedClip && (
              <span className="flex shrink-0 items-center gap-1 rounded-full bg-green-500/15 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-green-400">
                <CheckCircle2 className="h-3 w-3" />
                Clipped
              </span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-500">
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

        {clip.status === "ready" && (
          <button onClick={onExpand} className="btn-secondary px-3 py-2 text-xs">
            <ChevronDown className={clsx("h-4 w-4 transition-transform", expanded && "rotate-180")} />
            {clip.has_selection ? "Edit Review" : "Open Review"}
          </button>
        )}

        <button
          onClick={onDelete}
          className="rounded p-1.5 text-zinc-600 transition-colors hover:bg-zinc-800 hover:text-red-400"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>

      {clip.status !== "ready" && (
        <div className="mt-3 rounded-lg border border-zinc-800 bg-zinc-950/60 px-3 py-2 text-xs text-zinc-500">
          {clip.status === "error" ? clip.source_title + " failed to process." : statusCopy}
        </div>
      )}

      {clip.status === "ready" && !expanded && !clip.has_selection && (
        <div className="mt-3 rounded-lg border border-zinc-800 bg-zinc-950/60 px-3 py-2 text-xs text-zinc-500">
          Analysis is ready. Click Open Review to see the waveform and choose a range.
        </div>
      )}

      {expanded && clip.status === "ready" && (
        <div className="mt-4 grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
          <div className="space-y-4">
            {loadingAnalysis ? (
              <div className="flex h-56 items-center justify-center rounded-xl border border-zinc-800 bg-zinc-950/40 text-zinc-500">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Loading analysis...
              </div>
            ) : (
              <>
                {clip.preview_url && (
                  <video
                    ref={videoRef}
                    src={clip.preview_url}
                    controls
                    preload="metadata"
                    className="w-full rounded-xl border border-zinc-800 bg-black"
                  />
                )}

                <div className="rounded-xl border border-zinc-800 bg-zinc-950/50 p-4">
                  <div className="mb-3 flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium text-zinc-200">Suggested energy map</p>
                      <p className="text-xs text-zinc-500">
                        Bright blocks point to likely chorus or high-energy sections.
                      </p>
                    </div>
                    {analysis && (
                      <button
                        onClick={onUseSuggestion}
                        disabled={saving}
                        className="btn-secondary px-3 py-2 text-xs"
                      >
                        {saving ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Sparkles className="h-3.5 w-3.5" />
                        )}
                        Use recommendation
                      </button>
                    )}
                  </div>

                  <WaveformPreview
                    waveform={analysis?.waveform ?? []}
                    highlights={analysis?.highlights ?? []}
                    duration={maxDuration}
                    selection={selection}
                    onSeek={seekVideo}
                  />

                  {analysis?.highlights?.length ? (
                    <div className="mt-4 flex flex-wrap gap-2">
                      {analysis.highlights.map((highlight) => (
                        <button
                          key={`${highlight.start}-${highlight.end}`}
                          onClick={() => {
                            onDraftChange({ start: highlight.start, end: highlight.end });
                            seekVideo(highlight.start);
                          }}
                          className="rounded-full border border-zinc-700 bg-zinc-900 px-3 py-1 text-xs text-zinc-300 transition-colors hover:border-brand-500 hover:text-white"
                        >
                          {highlight.label}: {formatTime(highlight.start)} to {formatTime(highlight.end)}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
              </>
            )}
          </div>

          <div className="rounded-xl border border-zinc-800 bg-zinc-950/50 p-4">
            <p className="text-sm font-medium text-zinc-200">Pick the exact range</p>
            <p className="mt-1 text-xs text-zinc-500">
              Choose any start and end time. It does not need to be exactly 60 seconds.
            </p>

            <div className="mt-4 space-y-4">
              <RangeControl
                label="Start"
                value={selection.start}
                max={Math.max(maxDuration, selection.end || 0)}
                onChange={(value) =>
                  onDraftChange({
                    start: Math.min(value, Math.max(selection.end - 0.5, 0)),
                    end: selection.end,
                  })
                }
              />
              <RangeControl
                label="End"
                value={selection.end}
                max={Math.max(maxDuration, selection.end || 0)}
                onChange={(value) =>
                  onDraftChange({
                    start: selection.start,
                    end: Math.max(value, selection.start + 0.5),
                  })
                }
              />
            </div>

            <div className="mt-4 rounded-lg border border-zinc-800 bg-zinc-900/70 p-3 text-xs text-zinc-400">
              <div className="flex items-center justify-between">
                <span>Chosen range</span>
                <span className="font-mono text-zinc-200">
                  {formatTime(selection.start)} to {formatTime(selection.end)}
                </span>
              </div>
              <div className="mt-1 flex items-center justify-between">
                <span>Duration</span>
                <span className="font-mono text-zinc-200">
                  {formatTime(Math.max(selection.end - selection.start, 0))}
                </span>
              </div>
            </div>

            <div className="mt-4 flex flex-wrap gap-2">
              <button
                onClick={onSaveDraft}
                disabled={!hasValidSelection || saving}
                className="btn-secondary px-3 py-2 text-xs"
              >
                {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
                Save range
              </button>
              <button
                onClick={onCommit}
                disabled={!hasValidSelection || committing}
                className="btn-primary px-3 py-2 text-xs"
              >
                {committing ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Scissors className="h-3.5 w-3.5" />
                )}
                Trim and discard full video
              </button>
            </div>

            <p className="mt-3 text-xs text-zinc-500">
              Saving keeps your chosen timestamps. Trimming creates the final clip file and frees the original download.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

function WaveformPreview({
  waveform,
  highlights,
  duration,
  selection,
  onSeek,
}: {
  waveform: number[];
  highlights: ClipAnalysis["highlights"];
  duration: number;
  selection: DraftRange;
  onSeek?: (time: number) => void;
}) {
  function handleWaveformClick(e: React.MouseEvent<HTMLDivElement>) {
    if (!duration || !onSeek) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const ratio = (e.clientX - rect.left) / rect.width;
    onSeek(Math.max(0, Math.min(ratio * duration, duration)));
  }

  return (
    <div
      className={clsx(
        "relative overflow-hidden rounded-xl border border-zinc-800 bg-gradient-to-b from-zinc-950 to-zinc-900 px-2 py-5",
        onSeek && "cursor-pointer"
      )}
      onClick={handleWaveformClick}
      title={onSeek ? "Click to seek video" : undefined}
    >
      {/* selection overlay — non-interactive */}
      <div className="pointer-events-none absolute inset-0">
        {selection.end > selection.start && (
          <div
            className="absolute inset-y-0 rounded-lg border border-emerald-400/70 bg-emerald-400/12"
            style={{
              left: `${duration ? (selection.start / duration) * 100 : 0}%`,
              width: `${duration ? ((selection.end - selection.start) / duration) * 100 : 0}%`,
            }}
          />
        )}
      </div>

      {/* clickable highlight regions */}
      <div className="absolute inset-0">
        {highlights.map((highlight) => (
          <div
            key={`${highlight.start}-${highlight.end}`}
            className="absolute inset-y-0 rounded-lg bg-brand-500/12 transition-colors hover:bg-brand-500/25"
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

      {/* waveform bars */}
      <div className="pointer-events-none relative flex h-28 items-end gap-[2px]">
        {(waveform.length ? waveform : new Array(80).fill(0.15)).map((bar, index) => (
          <div
            key={`${index}-${bar}`}
            className="flex-1 rounded-full bg-zinc-600/90"
            style={{ height: `${Math.max(bar * 100, 8)}%` }}
          />
        ))}
      </div>
    </div>
  );
}

function RangeControl({
  label,
  value,
  max,
  onChange,
}: {
  label: string;
  value: number;
  max: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="block">
      <div className="mb-1 flex items-center justify-between text-xs text-zinc-400">
        <span>{label}</span>
        <span className="font-mono text-zinc-200">{formatTime(value)}</span>
      </div>
      <input
        type="range"
        min={0}
        max={Math.max(max, 1)}
        step={0.5}
        value={Math.min(value, Math.max(max, 1))}
        onChange={(event) => onChange(Number(event.target.value))}
        className="w-full accent-brand-500"
      />
    </label>
  );
}

function formatTime(seconds: number): string {
  const safeSeconds = Math.max(0, Math.floor(seconds));
  const m = Math.floor(safeSeconds / 60);
  const s = safeSeconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}
