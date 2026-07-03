import { useEffect, useRef, useState } from "react";
import { Film, Loader2, Trash2, Image, Youtube, Upload, Music, Search, Scissors } from "lucide-react";
import clsx from "clsx";
import type { ChangoverClip, SearchResult } from "../utils/types";
import {
  getChangoverClip,
  buildChangoverImageAudio,
  startChangoverYoutubeDownload,
  startChangoverYoutubeAudioDownload,
  buildChangoverYoutubeAudio,
  setChangoverImage,
  uploadChangoverVideo,
  buildChangoverVideoTrim,
  deleteChangoverClip,
  searchYouTube,
} from "../utils/api";

interface ChangeoverBuilderProps {
  projectId: number;
  /** Fired whenever the changeover clip changes (built, downloaded, deleted). */
  onClipChange?: (clip: ChangoverClip | null) => void;
}

/**
 * Self-contained "shot notification" (changeover) clip builder. Used both in the
 * project editor and on the AI Auto Generate approval screen. All state is local
 * and scoped to a single project id.
 */
export default function ChangeoverBuilder({ projectId, onClipChange }: ChangeoverBuilderProps) {
  const [changoverClip, setChangoverClip] = useState<ChangoverClip | null>(null);
  const [showChangoverBuilder, setShowChangoverBuilder] = useState(false);
  const [changoverMode, setChangoverMode] = useState<"image_audio" | "youtube" | "local_video">("image_audio");
  // image+audio mode
  const [changoverImageFile, setChangoverImageFile] = useState<File | null>(null);
  const [changoverAudioFile, setChangoverAudioFile] = useState<File | null>(null);
  const [changoverDuration, setChangoverDuration] = useState(3);
  // audio source sub-toggle inside image_audio mode
  const [audioSource, setAudioSource] = useState<"local" | "youtube">("local");
  const [ytAudioSearchQuery, setYtAudioSearchQuery] = useState("");
  const [ytAudioSearchResults, setYtAudioSearchResults] = useState<SearchResult[]>([]);
  const [ytAudioSearching, setYtAudioSearching] = useState(false);
  const [ytAudioTrimStart, setYtAudioTrimStart] = useState(0);
  // youtube mode
  const [changoverSearchQuery, setChangoverSearchQuery] = useState("");
  const [changoverSearchResults, setChangoverSearchResults] = useState<SearchResult[]>([]);
  const [changoverSearching, setChangoverSearching] = useState(false);
  // video trim (youtube + local_video)
  const [changoverTrimStart, setChangoverTrimStart] = useState(0);
  const [changoverTrimEnd, setChangoverTrimEnd] = useState(5);
  const [changoverVideoDropActive, setChangoverVideoDropActive] = useState(false);
  // general
  const [buildingChangover, setBuildingChangover] = useState(false);
  const [changoverError, setChangoverError] = useState<string | null>(null);
  const changoverImageInputRef = useRef<HTMLInputElement>(null);
  const changoverAudioInputRef = useRef<HTMLInputElement>(null);
  const changoverVideoInputRef = useRef<HTMLInputElement>(null);

  // Keep the latest onClipChange in a ref so notifying never re-subscribes effects.
  const notifyRef = useRef(onClipChange);
  notifyRef.current = onClipChange;
  function applyClip(clip: ChangoverClip | null) {
    setChangoverClip(clip);
    notifyRef.current?.(clip);
  }

  useEffect(() => {
    getChangoverClip(projectId).then(applyClip).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  useEffect(() => {
    if (changoverClip?.status !== "downloading") return;
    const interval = setInterval(() => {
      getChangoverClip(projectId).then((clip) => {
        applyClip(clip);
        // When youtube_audio finishes downloading, reset trim start
        if (clip && clip.status === "downloaded" && clip.source_type === "youtube_audio") {
          setYtAudioTrimStart(0);
        }
      }).catch(() => {});
    }, 2000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [changoverClip?.status, projectId]);

  async function handleBuildImageAudioChangover() {
    if (!changoverImageFile && !changoverAudioFile) return;
    setBuildingChangover(true);
    setChangoverError(null);
    try {
      const clip = await buildChangoverImageAudio(projectId, {
        image: changoverImageFile ?? undefined,
        audio: changoverAudioFile ?? undefined,
        duration: changoverDuration,
      });
      applyClip(clip);
      setShowChangoverBuilder(false);
      setChangoverImageFile(null);
      setChangoverAudioFile(null);
    } catch (err) {
      setChangoverError(err instanceof Error ? err.message : "Build failed");
    } finally {
      setBuildingChangover(false);
    }
  }

  async function handleYtAudioSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!ytAudioSearchQuery.trim()) return;
    setYtAudioSearching(true);
    try {
      const results = await searchYouTube(ytAudioSearchQuery, 8, undefined, false);
      setYtAudioSearchResults(results);
    } catch (err) {
      setChangoverError(err instanceof Error ? err.message : "Search failed");
    } finally {
      setYtAudioSearching(false);
    }
  }

  async function handlePickYtAudio(result: SearchResult) {
    setChangoverError(null);
    try {
      const clip = await startChangoverYoutubeAudioDownload(projectId, {
        youtube_id: result.youtube_id,
        title: result.title,
      });
      applyClip(clip);
      setYtAudioSearchResults([]);
      setYtAudioSearchQuery("");
    } catch (err) {
      setChangoverError(err instanceof Error ? err.message : "Download start failed");
    }
  }

  async function handleBuildYoutubeAudio() {
    setBuildingChangover(true);
    setChangoverError(null);
    try {
      // If user picked an image, upload it first
      if (changoverImageFile) {
        await setChangoverImage(projectId, changoverImageFile);
      }
      const clip = await buildChangoverYoutubeAudio(projectId, {
        audio_trim_start: ytAudioTrimStart,
        duration: changoverDuration,
      });
      applyClip(clip);
      setShowChangoverBuilder(false);
      setChangoverImageFile(null);
    } catch (err) {
      setChangoverError(err instanceof Error ? err.message : "Build failed");
    } finally {
      setBuildingChangover(false);
    }
  }

  async function handleChangoverYoutubeSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!changoverSearchQuery.trim()) return;
    setChangoverSearching(true);
    try {
      const results = await searchYouTube(changoverSearchQuery, 8, undefined, false);
      setChangoverSearchResults(results);
    } catch (err) {
      setChangoverError(err instanceof Error ? err.message : "Search failed");
    } finally {
      setChangoverSearching(false);
    }
  }

  async function handleChangoverPickYoutube(result: SearchResult) {
    setChangoverError(null);
    try {
      const clip = await startChangoverYoutubeDownload(projectId, {
        youtube_id: result.youtube_id,
        title: result.title,
      });
      applyClip(clip);
      setChangoverSearchResults([]);
      setChangoverSearchQuery("");
    } catch (err) {
      setChangoverError(err instanceof Error ? err.message : "Download start failed");
    }
  }

  async function handleChangoverVideoUpload(file: File) {
    setChangoverError(null);
    try {
      const clip = await uploadChangoverVideo(projectId, file);
      applyClip(clip);
      setChangoverTrimStart(0);
      setChangoverTrimEnd(Math.min(5, clip.duration || 5));
    } catch (err) {
      setChangoverError(err instanceof Error ? err.message : "Upload failed");
    }
  }

  async function handleBuildVideoChangover() {
    if (changoverTrimEnd <= changoverTrimStart) return;
    setBuildingChangover(true);
    setChangoverError(null);
    try {
      const clip = await buildChangoverVideoTrim(projectId, {
        trim_start: changoverTrimStart,
        trim_end: changoverTrimEnd,
      });
      applyClip(clip);
      setShowChangoverBuilder(false);
    } catch (err) {
      setChangoverError(err instanceof Error ? err.message : "Build failed");
    } finally {
      setBuildingChangover(false);
    }
  }

  async function handleDeleteChangover() {
    try {
      await deleteChangoverClip(projectId);
      applyClip(null);
      setShowChangoverBuilder(false);
      setChangoverError(null);
    } catch (err) {
      setChangoverError(err instanceof Error ? err.message : "Delete failed");
    }
  }

  return (
    <div className="retro-panel mb-6 rounded-[22px] p-5">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <Film className="h-4 w-4 text-[#ff77c2]" />
          <p className="font-retro text-sm tracking-[0.18em] text-zinc-200">SHOT NOTIFICATION</p>
          {changoverClip?.status === "ready" && (
            <span className="rounded-full border border-green-500/25 bg-green-500/10 px-2 py-0.5 font-retro text-[10px] uppercase tracking-[0.18em] text-green-400">
              READY · {changoverClip.duration.toFixed(1)}s
            </span>
          )}
          {changoverClip?.status === "downloading" && (
            <span className="flex items-center gap-1 rounded-full border border-[#1affe4]/20 bg-[#08131a] px-2 py-0.5 font-retro text-[10px] uppercase tracking-[0.18em] text-[#91fff2]/70">
              <Loader2 className="h-3 w-3 animate-spin" /> DOWNLOADING
            </span>
          )}
          {changoverClip?.status === "downloaded" && (
            <span className="rounded-full border border-[#1affe4]/20 bg-[#08131a] px-2 py-0.5 font-retro text-[10px] uppercase tracking-[0.18em] text-[#91fff2]/70">
              READY TO TRIM
            </span>
          )}
          {changoverClip?.status === "error" && (
            <span className="rounded-full border border-red-500/25 bg-red-500/10 px-2 py-0.5 font-retro text-[10px] uppercase tracking-[0.18em] text-red-400">
              ERROR
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {changoverClip && (
            <button
              onClick={handleDeleteChangover}
              className="rounded-lg p-1.5 text-zinc-600 transition-colors hover:bg-red-500/10 hover:text-red-300"
              title="Delete shot notification"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          )}
          <button
            onClick={() => {
              setShowChangoverBuilder((v) => !v);
              setChangoverError(null);
            }}
            className="crt-action retro-button-secondary inline-flex items-center gap-2 rounded-xl px-3 py-2 font-retro text-xs tracking-[0.16em]"
          >
            <span className="crt-action__label" data-text={showChangoverBuilder ? "CANCEL" : changoverClip ? "REBUILD" : "CREATE"}>
              {showChangoverBuilder ? "CANCEL" : changoverClip ? "REBUILD" : "CREATE"}
            </span>
          </button>
        </div>
      </div>

      {/* Ready preview */}
      {!showChangoverBuilder && changoverClip?.status === "ready" && changoverClip.preview_url && (
        <div className="mt-4">
          <video
            src={changoverClip.preview_url}
            controls
            className="w-full max-w-sm rounded-[18px] border border-[#1affe4]/12 bg-black"
          />
        </div>
      )}

      {/* No clip note */}
      {!showChangoverBuilder && !changoverClip && (
        <p className="mt-3 font-mono text-xs uppercase tracking-[0.14em] text-[#91fff2]/35">
          No shot notification — render will play clips back to back.
        </p>
      )}

      {/* Downloading state */}
      {!showChangoverBuilder && changoverClip?.status === "downloading" && (
        <p className="mt-3 font-mono text-xs uppercase tracking-[0.14em] text-[#91fff2]/55">
          Downloading from YouTube… this will be ready to trim shortly.
        </p>
      )}

      {/* Downloaded — show trim UI inline */}
      {!showChangoverBuilder && changoverClip?.status === "downloaded" && (
        <div className="mt-4 space-y-3">
          {changoverClip.raw_video_url && (
            <video
              src={changoverClip.raw_video_url}
              controls
              className="w-full max-w-sm rounded-[18px] border border-[#1affe4]/12 bg-black"
            />
          )}
          <div className="flex flex-wrap items-center gap-4">
            <label className="flex items-center gap-2 font-mono text-xs uppercase tracking-[0.14em] text-[#91fff2]/60">
              START (s)
              <input
                type="number"
                min={0}
                step={0.5}
                value={changoverTrimStart}
                onChange={(e) => setChangoverTrimStart(Number(e.target.value))}
                className="retro-input w-20 rounded-lg px-2 py-1 font-mono text-sm"
              />
            </label>
            <label className="flex items-center gap-2 font-mono text-xs uppercase tracking-[0.14em] text-[#91fff2]/60">
              END (s)
              <input
                type="number"
                min={0.5}
                step={0.5}
                value={changoverTrimEnd}
                onChange={(e) => setChangoverTrimEnd(Number(e.target.value))}
                className="retro-input w-20 rounded-lg px-2 py-1 font-mono text-sm"
              />
            </label>
            <button
              onClick={handleBuildVideoChangover}
              disabled={buildingChangover || changoverTrimEnd <= changoverTrimStart}
              className="crt-action retro-button-primary inline-flex items-center gap-2 rounded-xl px-4 py-2 font-retro text-xs tracking-[0.16em] disabled:cursor-not-allowed disabled:opacity-40"
            >
              {buildingChangover ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Scissors className="h-3.5 w-3.5" />}
              <span className="crt-action__label" data-text="BUILD SHOT CLIP">BUILD SHOT CLIP</span>
            </button>
          </div>
          {changoverError && (
            <p className="font-mono text-xs uppercase tracking-[0.14em] text-red-400">{changoverError}</p>
          )}
        </div>
      )}

      {/* Builder panel */}
      {showChangoverBuilder && (
        <div className="mt-5 space-y-4">
          {/* Mode tabs */}
          <div className="flex flex-wrap gap-2">
            {(["image_audio", "youtube", "local_video"] as const).map((mode) => {
              const labels = { image_audio: "IMAGE + AUDIO", youtube: "YOUTUBE VIDEO", local_video: "DROP VIDEO FILE" };
              const icons = { image_audio: <Image className="h-3.5 w-3.5" />, youtube: <Youtube className="h-3.5 w-3.5" />, local_video: <Upload className="h-3.5 w-3.5" /> };
              return (
                <button
                  key={mode}
                  onClick={() => { setChangoverMode(mode); setChangoverError(null); }}
                  className={clsx(
                    "inline-flex items-center gap-2 rounded-xl border px-3 py-2 font-retro text-xs tracking-[0.16em] transition-all",
                    changoverMode === mode
                      ? "border-[#ff2b9d]/40 bg-[#2b0b1d] text-[#ffd7eb]"
                      : "border-[#1affe4]/14 bg-[#08131a] text-[#91fff2]/70 hover:border-[#1affe4]/28"
                  )}
                >
                  {icons[mode]}
                  {labels[mode]}
                </button>
              );
            })}
          </div>

          {/* IMAGE + AUDIO mode */}
          {changoverMode === "image_audio" && (
            <div className="space-y-3">
              {/* Image picker (always available) */}
              <div>
                <button
                  onClick={() => changoverImageInputRef.current?.click()}
                  className="inline-flex items-center gap-2 rounded-xl border border-[#1affe4]/20 bg-[#08131a] px-3 py-2 font-retro text-xs tracking-[0.16em] text-[#91fff2]/70 hover:border-[#1affe4]/40 transition-colors"
                >
                  <Image className="h-3.5 w-3.5" />
                  {changoverImageFile ? changoverImageFile.name : "CHOOSE IMAGE (OPTIONAL)"}
                </button>
                <input
                  ref={changoverImageInputRef}
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={(e) => setChangoverImageFile(e.target.files?.[0] ?? null)}
                />
              </div>

              {/* Audio source sub-toggle */}
              <div className="flex gap-2">
                <button
                  onClick={() => { setAudioSource("local"); setChangoverError(null); }}
                  className={clsx(
                    "inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 font-retro text-[11px] tracking-[0.14em] transition-all",
                    audioSource === "local"
                      ? "border-[#1affe4]/40 bg-[#08131a] text-[#defffb]"
                      : "border-[#1affe4]/14 bg-transparent text-[#91fff2]/50 hover:border-[#1affe4]/28"
                  )}
                >
                  <Music className="h-3 w-3" /> UPLOAD FILE
                </button>
                <button
                  onClick={() => { setAudioSource("youtube"); setChangoverError(null); }}
                  className={clsx(
                    "inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 font-retro text-[11px] tracking-[0.14em] transition-all",
                    audioSource === "youtube"
                      ? "border-[#ff2b9d]/40 bg-[#2b0b1d] text-[#ffd7eb]"
                      : "border-[#1affe4]/14 bg-transparent text-[#91fff2]/50 hover:border-[#1affe4]/28"
                  )}
                >
                  <Youtube className="h-3 w-3" /> FROM YOUTUBE
                </button>
              </div>

              {/* Local audio upload */}
              {audioSource === "local" && (
                <div className="flex flex-wrap gap-3">
                  <div>
                    <button
                      onClick={() => changoverAudioInputRef.current?.click()}
                      className="inline-flex items-center gap-2 rounded-xl border border-[#1affe4]/20 bg-[#08131a] px-3 py-2 font-retro text-xs tracking-[0.16em] text-[#91fff2]/70 hover:border-[#1affe4]/40 transition-colors"
                    >
                      <Music className="h-3.5 w-3.5" />
                      {changoverAudioFile ? changoverAudioFile.name : "CHOOSE AUDIO"}
                    </button>
                    <input
                      ref={changoverAudioInputRef}
                      type="file"
                      accept="audio/*"
                      className="hidden"
                      onChange={(e) => setChangoverAudioFile(e.target.files?.[0] ?? null)}
                    />
                  </div>
                  <label className="flex items-center gap-3 font-mono text-xs uppercase tracking-[0.14em] text-[#91fff2]/60">
                    DURATION: {changoverDuration}s
                    <input type="range" min={1} max={10} step={0.5} value={changoverDuration} onChange={(e) => setChangoverDuration(Number(e.target.value))} className="w-32" />
                  </label>
                  <button
                    onClick={handleBuildImageAudioChangover}
                    disabled={buildingChangover || (!changoverImageFile && !changoverAudioFile)}
                    className="crt-action retro-button-primary inline-flex items-center gap-2 rounded-xl px-4 py-2 font-retro text-xs tracking-[0.16em] disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {buildingChangover ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Film className="h-3.5 w-3.5" />}
                    <span className="crt-action__label" data-text="BUILD SHOT CLIP">BUILD SHOT CLIP</span>
                  </button>
                </div>
              )}

              {/* YouTube audio rip */}
              {audioSource === "youtube" && (
                <div className="space-y-3">
                  {/* Show search if no audio downloaded yet */}
                  {(!changoverClip || changoverClip.source_type !== "youtube_audio" || changoverClip.status === "ready") && (
                    <>
                      <form onSubmit={handleYtAudioSearch} className="flex gap-2">
                        <input
                          type="text"
                          className="retro-input flex-1 rounded-xl px-3 py-2 font-mono text-sm tracking-[0.12em]"
                          placeholder="Search YouTube for audio..."
                          value={ytAudioSearchQuery}
                          onChange={(e) => setYtAudioSearchQuery(e.target.value)}
                        />
                        <button
                          type="submit"
                          disabled={ytAudioSearching}
                          className="crt-action retro-button-primary inline-flex shrink-0 items-center gap-2 rounded-xl px-3 py-2 font-retro text-xs tracking-[0.16em] disabled:opacity-40"
                        >
                          {ytAudioSearching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Search className="h-3.5 w-3.5" />}
                        </button>
                      </form>
                      {ytAudioSearchResults.length > 0 && (
                        <div className="space-y-2 max-h-56 overflow-y-auto">
                          {ytAudioSearchResults.map((result) => (
                            <div key={result.youtube_id} className="retro-project-card flex items-center gap-3 rounded-[16px] p-3">
                              <img src={result.thumbnail} alt={result.title} className="h-10 w-16 shrink-0 rounded-lg object-cover" />
                              <div className="min-w-0 flex-1">
                                <p className="truncate font-retro text-sm tracking-[0.12em] text-[#ffb6dd]">{result.title}</p>
                                <p className="font-mono text-xs uppercase tracking-[0.12em] text-[#91fff2]/45">{result.artist}{result.duration && ` · ${result.duration}`}</p>
                              </div>
                              <button
                                onClick={() => handlePickYtAudio(result)}
                                className="crt-action retro-button-primary shrink-0 rounded-xl px-3 py-1.5 font-retro text-xs tracking-[0.14em]"
                              >
                                <span className="crt-action__label" data-text="RIP">RIP</span>
                              </button>
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                  {/* Downloading */}
                  {changoverClip?.status === "downloading" && changoverClip.source_type === "youtube_audio" && (
                    <div className="flex items-center gap-2 font-mono text-xs uppercase tracking-[0.14em] text-[#91fff2]/55">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      Ripping audio from YouTube…
                    </div>
                  )}
                  {/* Downloaded — show trim + duration + build */}
                  {changoverClip?.status === "downloaded" && changoverClip.source_type === "youtube_audio" && (
                    <div className="space-y-3">
                      <p className="font-mono text-xs uppercase tracking-[0.12em] text-green-400/70">Audio ready — set start offset and duration</p>
                      <div className="flex flex-wrap items-center gap-4">
                        <label className="flex items-center gap-2 font-mono text-xs uppercase tracking-[0.14em] text-[#91fff2]/60">
                          START (s)
                          <input type="number" min={0} step={0.5} value={ytAudioTrimStart} onChange={(e) => setYtAudioTrimStart(Number(e.target.value))} className="retro-input w-20 rounded-lg px-2 py-1 font-mono text-sm" />
                        </label>
                        <label className="flex items-center gap-3 font-mono text-xs uppercase tracking-[0.14em] text-[#91fff2]/60">
                          DURATION: {changoverDuration}s
                          <input type="range" min={1} max={10} step={0.5} value={changoverDuration} onChange={(e) => setChangoverDuration(Number(e.target.value))} className="w-32" />
                        </label>
                      </div>
                      <button
                        onClick={handleBuildYoutubeAudio}
                        disabled={buildingChangover}
                        className="crt-action retro-button-primary inline-flex items-center gap-2 rounded-xl px-4 py-2 font-retro text-xs tracking-[0.16em] disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        {buildingChangover ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Film className="h-3.5 w-3.5" />}
                        <span className="crt-action__label" data-text="BUILD SHOT CLIP">BUILD SHOT CLIP</span>
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* YOUTUBE mode */}
          {changoverMode === "youtube" && (
            <div className="space-y-3">
              {(!changoverClip || changoverClip.status === "ready" || changoverClip.source_type !== "youtube") && (
                <>
                  <form onSubmit={handleChangoverYoutubeSearch} className="flex gap-2">
                    <input
                      type="text"
                      className="retro-input flex-1 rounded-xl px-3 py-2 font-mono text-sm tracking-[0.12em]"
                      placeholder="Search YouTube..."
                      value={changoverSearchQuery}
                      onChange={(e) => setChangoverSearchQuery(e.target.value)}
                    />
                    <button
                      type="submit"
                      disabled={changoverSearching}
                      className="crt-action retro-button-primary inline-flex shrink-0 items-center gap-2 rounded-xl px-3 py-2 font-retro text-xs tracking-[0.16em] disabled:opacity-40"
                    >
                      {changoverSearching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Search className="h-3.5 w-3.5" />}
                    </button>
                  </form>
                  {changoverSearchResults.length > 0 && (
                    <div className="space-y-2 max-h-64 overflow-y-auto">
                      {changoverSearchResults.map((result) => (
                        <div key={result.youtube_id} className="retro-project-card flex items-center gap-3 rounded-[16px] p-3">
                          <img src={result.thumbnail} alt={result.title} className="h-12 w-20 shrink-0 rounded-lg object-cover" />
                          <div className="min-w-0 flex-1">
                            <p className="truncate font-retro text-sm tracking-[0.12em] text-[#ffb6dd]">{result.title}</p>
                            <p className="font-mono text-xs uppercase tracking-[0.12em] text-[#91fff2]/45">{result.artist}{result.duration && ` · ${result.duration}`}</p>
                          </div>
                          <button
                            onClick={() => handleChangoverPickYoutube(result)}
                            className="crt-action retro-button-primary shrink-0 rounded-xl px-3 py-1.5 font-retro text-xs tracking-[0.14em]"
                          >
                            <span className="crt-action__label" data-text="USE">USE</span>
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
              {changoverClip?.status === "downloading" && changoverClip.source_type === "youtube" && (
                <div className="flex items-center gap-2 font-mono text-xs uppercase tracking-[0.14em] text-[#91fff2]/55">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Downloading from YouTube… Once complete the trim controls will appear.
                </div>
              )}
              {changoverClip?.status === "downloaded" && changoverClip.source_type === "youtube" && (
                <div className="space-y-3">
                  {changoverClip.raw_video_url && (
                    <video src={changoverClip.raw_video_url} controls className="w-full max-w-sm rounded-[18px] border border-[#1affe4]/12 bg-black" />
                  )}
                  <div className="flex flex-wrap items-center gap-4">
                    <label className="flex items-center gap-2 font-mono text-xs uppercase tracking-[0.14em] text-[#91fff2]/60">
                      START (s)
                      <input type="number" min={0} step={0.5} value={changoverTrimStart} onChange={(e) => setChangoverTrimStart(Number(e.target.value))} className="retro-input w-20 rounded-lg px-2 py-1 font-mono text-sm" />
                    </label>
                    <label className="flex items-center gap-2 font-mono text-xs uppercase tracking-[0.14em] text-[#91fff2]/60">
                      END (s)
                      <input type="number" min={0.5} step={0.5} value={changoverTrimEnd} onChange={(e) => setChangoverTrimEnd(Number(e.target.value))} className="retro-input w-20 rounded-lg px-2 py-1 font-mono text-sm" />
                    </label>
                    <button
                      onClick={handleBuildVideoChangover}
                      disabled={buildingChangover || changoverTrimEnd <= changoverTrimStart}
                      className="crt-action retro-button-primary inline-flex items-center gap-2 rounded-xl px-4 py-2 font-retro text-xs tracking-[0.16em] disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      {buildingChangover ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Scissors className="h-3.5 w-3.5" />}
                      <span className="crt-action__label" data-text="BUILD SHOT CLIP">BUILD SHOT CLIP</span>
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* LOCAL VIDEO / DROP mode */}
          {changoverMode === "local_video" && (
            <div className="space-y-3">
              {(!changoverClip || changoverClip.status === "ready" || changoverClip.source_type !== "local_video") && (
                <div
                  className={clsx(
                    "flex flex-col items-center justify-center gap-3 rounded-[18px] border-2 border-dashed px-6 py-10 transition-colors cursor-pointer",
                    changoverVideoDropActive
                      ? "border-[#ff2b9d]/60 bg-[#2b0b1d]/40"
                      : "border-[#1affe4]/20 bg-[#08131a] hover:border-[#1affe4]/40"
                  )}
                  onDragOver={(e) => { e.preventDefault(); setChangoverVideoDropActive(true); }}
                  onDragLeave={() => setChangoverVideoDropActive(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setChangoverVideoDropActive(false);
                    const file = e.dataTransfer.files[0];
                    if (file) handleChangoverVideoUpload(file);
                  }}
                  onClick={() => changoverVideoInputRef.current?.click()}
                >
                  <Upload className="h-6 w-6 text-[#1affe4]/50" />
                  <p className="font-retro text-sm tracking-[0.16em] text-[#91fff2]/60">DROP VIDEO FILE HERE</p>
                  <p className="font-mono text-xs uppercase tracking-[0.12em] text-[#91fff2]/35">or click to browse · mp4 mov avi mkv webm</p>
                  <input
                    ref={changoverVideoInputRef}
                    type="file"
                    accept="video/*"
                    className="hidden"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) handleChangoverVideoUpload(file);
                    }}
                  />
                </div>
              )}
              {changoverClip?.status === "downloaded" && changoverClip.source_type === "local_video" && (
                <div className="space-y-3">
                  {changoverClip.raw_video_url && (
                    <video src={changoverClip.raw_video_url} controls className="w-full max-w-sm rounded-[18px] border border-[#1affe4]/12 bg-black" />
                  )}
                  <div className="flex flex-wrap items-center gap-4">
                    <label className="flex items-center gap-2 font-mono text-xs uppercase tracking-[0.14em] text-[#91fff2]/60">
                      START (s)
                      <input type="number" min={0} step={0.5} value={changoverTrimStart} onChange={(e) => setChangoverTrimStart(Number(e.target.value))} className="retro-input w-20 rounded-lg px-2 py-1 font-mono text-sm" />
                    </label>
                    <label className="flex items-center gap-2 font-mono text-xs uppercase tracking-[0.14em] text-[#91fff2]/60">
                      END (s)
                      <input type="number" min={0.5} step={0.5} value={changoverTrimEnd} onChange={(e) => setChangoverTrimEnd(Number(e.target.value))} className="retro-input w-20 rounded-lg px-2 py-1 font-mono text-sm" />
                    </label>
                    <button
                      onClick={handleBuildVideoChangover}
                      disabled={buildingChangover || changoverTrimEnd <= changoverTrimStart}
                      className="crt-action retro-button-primary inline-flex items-center gap-2 rounded-xl px-4 py-2 font-retro text-xs tracking-[0.16em] disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      {buildingChangover ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Scissors className="h-3.5 w-3.5" />}
                      <span className="crt-action__label" data-text="BUILD SHOT CLIP">BUILD SHOT CLIP</span>
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {changoverError && (
            <p className="font-mono text-xs uppercase tracking-[0.14em] text-red-400">{changoverError}</p>
          )}
        </div>
      )}
    </div>
  );
}
