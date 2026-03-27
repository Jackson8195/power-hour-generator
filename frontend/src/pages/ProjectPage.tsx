import { useEffect, useState, useCallback } from "react";
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
  ChevronRight,
} from "lucide-react";
import type { ProjectDetail, SearchResult, Clip, RenderProgress } from "../utils/types";
import {
  getProject,
  searchYouTube,
  addClip,
  deleteClip,
  startDownload,
  startRender,
  connectRenderWs,
  useSuggestedSegment,
  updateClip,
} from "../utils/api";
import clsx from "clsx";

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const projectId = Number(id);

  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [renderProgress, setRenderProgress] = useState<RenderProgress | null>(null);
  const [activeTab, setActiveTab] = useState<"search" | "timeline">("search");

  const loadProject = useCallback(async () => {
    try {
      const data = await getProject(projectId);
      setProject(data);
    } catch (err) {
      console.error("Failed to load project:", err);
    }
  }, [projectId]);

  useEffect(() => {
    loadProject();
  }, [loadProject]);

  // Poll for clip status updates
  useEffect(() => {
    const pendingClips = project?.clips.filter(
      (c) => c.status === "downloading" || c.status === "analyzing"
    );
    if (!pendingClips?.length) return;

    const interval = setInterval(loadProject, 3000);
    return () => clearInterval(interval);
  }, [project, loadProject]);

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!searchQuery.trim()) return;

    setSearching(true);
    try {
      const results = await searchYouTube(searchQuery);
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

      // Auto-start download
      await startDownload(clip.id);
      await loadProject();

      // Remove from search results
      setSearchResults((prev) => prev.filter((r) => r.youtube_id !== result.youtube_id));
    } catch (err) {
      console.error("Failed to add clip:", err);
    }
  }

  async function handleDeleteClip(clipId: number) {
    try {
      await deleteClip(clipId);
      await loadProject();
    } catch (err) {
      console.error("Failed to delete clip:", err);
    }
  }

  async function handleUseSuggestion(clipId: number) {
    try {
      await useSuggestedSegment(clipId);
      await loadProject();
    } catch (err) {
      console.error("Failed to apply suggestion:", err);
    }
  }

  async function handleStartRender() {
    try {
      const { render_id } = await startRender(projectId);

      // Connect WebSocket for progress
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

  const readyClips = project.clips.filter((c) => c.status === "ready");

  return (
    <div>
      {/* Project header */}
      <div className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold text-zinc-100">{project.name}</h1>
          <p className="mt-1 text-sm text-zinc-500">
            {readyClips.length} / 60 clips ready
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleStartRender}
            disabled={readyClips.length === 0 || renderProgress?.status === "rendering"}
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

      {/* Render progress */}
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

      {/* Tabs */}
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
          Timeline ({project.clips.length})
        </button>
      </div>

      {/* Search Tab */}
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
            <button
              type="submit"
              disabled={searching}
              className="btn-primary shrink-0"
            >
              {searching ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Search className="h-4 w-4" />
              )}
              Search
            </button>
          </form>

          <div className="space-y-2">
            {searchResults.map((result) => (
              <div
                key={result.youtube_id}
                className="card flex items-center gap-4"
              >
                <img
                  src={result.thumbnail}
                  alt={result.title}
                  className="h-16 w-28 shrink-0 rounded object-cover"
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-zinc-100">
                    {result.title}
                  </p>
                  <p className="text-xs text-zinc-500">
                    {result.artist}
                    {result.duration && ` · ${result.duration}`}
                  </p>
                </div>
                <button
                  onClick={() => handleAddClip(result)}
                  className="btn-primary shrink-0 text-xs"
                >
                  <Download className="h-3.5 w-3.5" />
                  Add
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Timeline Tab */}
      {activeTab === "timeline" && (
        <div className="space-y-2">
          {project.clips.length === 0 ? (
            <div className="py-16 text-center text-zinc-500">
              No clips yet. Search and add songs to get started!
            </div>
          ) : (
            project.clips.map((clip, index) => (
              <ClipRow
                key={clip.id}
                clip={clip}
                index={index}
                onDelete={handleDeleteClip}
                onUseSuggestion={handleUseSuggestion}
              />
            ))
          )}
        </div>
      )}
    </div>
  );
}

function ClipRow({
  clip,
  index,
  onDelete,
  onUseSuggestion,
}: {
  clip: Clip;
  index: number;
  onDelete: (id: number) => void;
  onUseSuggestion: (id: number) => void;
}) {
  const statusColor = {
    pending: "bg-zinc-600",
    downloading: "bg-blue-500 animate-pulse",
    analyzing: "bg-purple-500 animate-pulse",
    ready: "bg-green-500",
    error: "bg-red-500",
  }[clip.status];

  return (
    <div className="card flex items-center gap-3">
      {/* Position number */}
      <div className="flex w-8 shrink-0 items-center justify-center">
        <span className="font-mono text-xs text-zinc-600">{index + 1}</span>
      </div>

      {/* Drag handle placeholder */}
      <GripVertical className="h-4 w-4 shrink-0 cursor-grab text-zinc-700" />

      {/* Thumbnail */}
      {clip.source_thumbnail ? (
        <img
          src={clip.source_thumbnail}
          alt={clip.source_title}
          className="h-12 w-20 shrink-0 rounded object-cover"
        />
      ) : (
        <div className="flex h-12 w-20 shrink-0 items-center justify-center rounded bg-zinc-800">
          <Play className="h-4 w-4 text-zinc-600" />
        </div>
      )}

      {/* Info */}
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-zinc-200">
          {clip.source_title || "Untitled"}
        </p>
        <div className="flex items-center gap-2 text-xs text-zinc-500">
          <span>{clip.source_artist}</span>
          {clip.bpm && <span>· {Math.round(clip.bpm)} BPM</span>}
          {clip.status === "ready" && (
            <span>
              · {formatTime(clip.start_time)} → {formatTime(clip.end_time)}
            </span>
          )}
        </div>
      </div>

      {/* Status indicator */}
      <div className={clsx("h-2 w-2 shrink-0 rounded-full", statusColor)} />

      {/* Actions */}
      <div className="flex shrink-0 items-center gap-1">
        {clip.suggested_start !== null && clip.status === "ready" && (
          <button
            onClick={() => onUseSuggestion(clip.id)}
            className="rounded p-1.5 text-zinc-500 transition-colors hover:bg-zinc-800 hover:text-purple-400"
            title="Use AI-suggested segment"
          >
            <Sparkles className="h-4 w-4" />
          </button>
        )}
        <button
          onClick={() => onDelete(clip.id)}
          className="rounded p-1.5 text-zinc-600 transition-colors hover:bg-zinc-800 hover:text-red-400"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}
