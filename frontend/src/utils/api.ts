import type {
  AiSession,
  AiSessionState,
  AutoGenerateApproval,
  AutoGenerateProject,
  AutoGenerateJobProgress,
  AutoGenerateMode,
  AutoGenerateProposalJobStart,
  AutoGenerateProposalJobStatus,
  AutoGenerateReplaceJobStart,
  AutoGenerateReviseJobStart,
  AutoGenerateProposal,
  SearchResult,
  Project,
  ProjectDetail,
  Clip,
  ClipAnalysis,
  RenderProgress,
  RenderLibraryEntry,
  CastDevice,
  ChangoverClip,
} from "./types";

const BASE = "";

/** FastAPI sends a string for HTTPException but a list of objects for validation errors (422). */
function formatErrorDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object" && "msg" in item) {
          const loc = Array.isArray((item as { loc?: unknown[] }).loc)
            ? (item as { loc: unknown[] }).loc.filter((part) => part !== "body").join(".")
            : "";
          const msg = String((item as { msg: unknown }).msg);
          return loc ? `${loc}: ${msg}` : msg;
        }
        return "";
      })
      .filter(Boolean);
    if (messages.length) return messages.join("; ");
  }
  return fallback;
}

/** An Error that keeps the HTTP status, so callers can tell "gone" (404) from a network blip. */
export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

export function isNotFound(err: unknown): boolean {
  return err instanceof ApiError && err.status === 404;
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(formatErrorDetail(error.detail, `Request failed: ${res.status}`), res.status);
  }
  return res.json();
}

/** localStorage key for the AI job the user last started (so the page can reattach to it). */
export const ACTIVE_AI_JOB_KEY = "power-hour-active-ai-job";

// ─── Search ──────────────────────────────────────────────

export async function searchYouTube(
  query: string,
  maxResults = 10,
  projectId?: number,
  music = true
): Promise<SearchResult[]> {
  return request("/api/search/youtube", {
    method: "POST",
    body: JSON.stringify({
      query,
      max_results: maxResults,
      project_id: projectId,
      music,
    }),
  });
}

export async function getRecommendedTracks(
  projectId: number,
  maxResults = 8
): Promise<SearchResult[]> {
  return request(`/api/search/recommendations/${projectId}?max_results=${maxResults}`);
}

export async function startAutoGenerateProposal(
  prompt: string,
  mode: AutoGenerateMode = "music"
): Promise<AutoGenerateProposalJobStart> {
  return request("/api/auto-generate/proposals", {
    method: "POST",
    body: JSON.stringify({ prompt, mode }),
  });
}

export async function startReplaceAutoGenerateProposalItem(
  proposalId: string,
  slotIndex: number,
  note = ""
): Promise<AutoGenerateReplaceJobStart> {
  return request(`/api/auto-generate/proposals/${proposalId}/replace`, {
    method: "POST",
    body: JSON.stringify({ slot_index: slotIndex, note }),
  });
}

/** REVISE: a comment on the whole playlist; poll the job with getAutoGenerateProposalJob. */
export async function startReviseAutoGenerateProposal(
  proposalId: string,
  comment: string
): Promise<AutoGenerateReviseJobStart> {
  return request(`/api/auto-generate/proposals/${proposalId}/revise`, {
    method: "POST",
    body: JSON.stringify({ comment }),
  });
}

export async function undoAutoGenerateRevision(proposalId: string): Promise<AutoGenerateProposal> {
  return request(`/api/auto-generate/proposals/${proposalId}/undo`, { method: "POST" });
}

export async function lockAutoGenerateSlot(
  proposalId: string,
  slotIndex: number,
  locked: boolean
): Promise<AutoGenerateProposal> {
  return request(`/api/auto-generate/proposals/${proposalId}/lock`, {
    method: "POST",
    body: JSON.stringify({ slot_index: slotIndex, locked }),
  });
}

export async function getAutoGenerateProposalJob(
  jobId: string
): Promise<AutoGenerateProposalJobStatus> {
  return request(`/api/auto-generate/proposal-jobs/${jobId}`);
}

/** fetch() rejects with a TypeError ("Failed to fetch") when the server can't be reached at all,
 *  as opposed to an ApiError for a real HTTP answer. */
export function isNetworkError(err: unknown): boolean {
  return err instanceof TypeError;
}

/** Thrown when the server stayed unreachable for the whole retry window. The job itself keeps
 *  running on the backend, so callers should keep it attached for a reload to pick up. */
export class LostContactError extends Error {}

// About two minutes of retries (each failed fetch also takes a moment) before giving up.
const MAX_POLL_NETWORK_FAILURES = 60;

/** Poll a proposal / replace / revise job until it leaves "pending". A blip in the connection
 *  (Wi-Fi drop, firewall or network-profile change) is retried instead of abandoning the job.
 *  Returns null if cancelled. */
export async function waitForProposalJob(
  jobId: string,
  isCancelled: () => boolean = () => false,
  intervalMs = 2000
): Promise<AutoGenerateProposalJobStatus | null> {
  let failures = 0;
  while (!isCancelled()) {
    // Wait one interval, or less if the tab comes back into view (a phone screen waking up:
    // Chrome pauses hidden tabs, and the request in flight when it locked fails).
    await new Promise<void>((res) => {
      const done = () => {
        window.clearTimeout(timer);
        document.removeEventListener("visibilitychange", onVisible);
        res();
      };
      const onVisible = () => {
        if (!document.hidden) done();
      };
      const timer = window.setTimeout(done, intervalMs);
      document.addEventListener("visibilitychange", onVisible);
    });
    if (isCancelled()) return null;
    // Hidden tab: don't count requests the browser is about to kill as failures.
    if (document.hidden) continue;
    let status: AutoGenerateProposalJobStatus;
    try {
      status = await getAutoGenerateProposalJob(jobId);
      failures = 0;
    } catch (err) {
      if (isNetworkError(err)) {
        failures += 1;
        if (failures < MAX_POLL_NETWORK_FAILURES) continue;
        throw new LostContactError(
          "Lost contact with the app server. The job is still running there: reload the page to pick it up."
        );
      }
      throw err;
    }
    if (status.status !== "pending") return status;
  }
  return null;
}

export async function approveAutoGenerateProposal(
  proposalId: string,
  opts: {
    projectName?: string;
    projectId?: number | null;
    includeTransition?: boolean;
    aiTransitionCount?: number;
    aiTransitionSources?: "cards" | "youtube" | "both";
    aiTransitionsReviewed?: boolean;
    aiTransitionPrompt?: string;
    /** The user's call word for transitions the AI creates during the build. */
    aiTransitionText?: string;
  } = {}
): Promise<AutoGenerateApproval> {
  return request(`/api/auto-generate/proposals/${proposalId}/approve`, {
    method: "POST",
    body: JSON.stringify({
      project_name: opts.projectName ?? "",
      project_id: opts.projectId ?? null,
      include_transition: opts.includeTransition ?? true,
      ai_transition_count: opts.aiTransitionCount ?? 0,
      ai_transition_sources: opts.aiTransitionSources ?? "both",
      ai_transitions_reviewed: opts.aiTransitionsReviewed ?? false,
      ai_transition_prompt: opts.aiTransitionPrompt ?? "",
      ai_transition_text: opts.aiTransitionText ?? null,
    }),
  });
}

export async function createProjectForProposal(
  proposalId: string,
  projectName?: string
): Promise<AutoGenerateProject> {
  return request(`/api/auto-generate/proposals/${proposalId}/project`, {
    method: "POST",
    body: JSON.stringify({ project_name: projectName ?? "" }),
  });
}

export async function getAutoGenerateJob(
  jobId: string
): Promise<AutoGenerateJobProgress> {
  return request(`/api/auto-generate/jobs/${jobId}`);
}

/** The running AI build, wherever it was started (null when nothing is running). */
export async function getActiveAutoGenerateJob(): Promise<AutoGenerateJobProgress | null> {
  return request("/api/auto-generate/jobs/active");
}

/** The shared AI draft: lets the phone pick up a playlist started on the desktop and back. */
export async function getAiSession(): Promise<AiSession> {
  return request("/api/auto-generate/session");
}

export async function saveAiSession(state: AiSessionState): Promise<AiSession> {
  return request("/api/auto-generate/session", { method: "PUT", body: JSON.stringify(state) });
}

// ─── Projects ────────────────────────────────────────────

export async function listProjects(): Promise<Project[]> {
  return request("/api/projects/");
}

export async function createProject(data: {
  name: string;
  description?: string;
  clip_duration?: number;
  transition_type?: string;
}): Promise<Project> {
  return request("/api/projects/", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function getProject(id: number): Promise<ProjectDetail> {
  return request(`/api/projects/${id}`);
}

export async function deleteProject(id: number): Promise<void> {
  return request(`/api/projects/${id}`, { method: "DELETE" });
}

// ─── Clips ───────────────────────────────────────────────

export async function addClip(
  projectId: number,
  clip: {
    source_url: string;
    source_title: string;
    source_artist: string;
    source_thumbnail: string;
    youtube_id: string;
    position: number;
  }
): Promise<Clip> {
  return request(`/api/clips/?project_id=${projectId}`, {
    method: "POST",
    body: JSON.stringify(clip),
  });
}

export async function updateClip(
  clipId: number,
  data: { start_time?: number; end_time?: number; position?: number }
): Promise<Clip> {
  return request(`/api/clips/${clipId}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export async function deleteClip(clipId: number): Promise<void> {
  return request(`/api/clips/${clipId}`, { method: "DELETE" });
}

export async function reorderClips(
  projectId: number,
  clipIds: number[]
): Promise<void> {
  return request(`/api/clips/reorder?project_id=${projectId}`, {
    method: "POST",
    body: JSON.stringify(clipIds),
  });
}

export async function useSuggestedSegment(clipId: number): Promise<Clip> {
  return request(`/api/clips/${clipId}/use-suggestion`, { method: "POST" });
}

export async function getClipAnalysis(clipId: number): Promise<ClipAnalysis> {
  return request(`/api/clips/${clipId}/analysis`);
}

export async function commitClipSelection(
  clipId: number,
  data: { start_time: number; end_time: number }
): Promise<Clip> {
  return request(`/api/clips/${clipId}/commit`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

// ─── Downloads ───────────────────────────────────────────

export async function startDownload(
  clipId: number
): Promise<{ status: string }> {
  return request(`/api/downloads/${clipId}/start`, { method: "POST" });
}

export async function getDownloadStatus(
  clipId: number
): Promise<{ clip_id: number; status: string; has_media: boolean; error_message: string }> {
  return request(`/api/downloads/${clipId}/status`);
}

// ─── Render ──────────────────────────────────────────────

export async function startRender(
  projectId: number,
  options?: {
    resolution?: string;
    transition_type?: string;
    include_countdown?: boolean;
    /** After a good render, trim clips still on their full source and delete the sources. */
    finalize_sources?: boolean;
  }
): Promise<{ render_id: number; clips_included: number; clips_skipped: string[] }> {
  return request(`/api/render/${projectId}`, {
    method: "POST",
    body: JSON.stringify(options ?? {}),
  });
}

export async function getRenderStatus(
  renderId: number
): Promise<RenderProgress> {
  return request(`/api/render/${renderId}/status`);
}

export async function listRenderedVideos(): Promise<RenderLibraryEntry[]> {
  return request("/api/render/library");
}

export async function getActiveRender(
  projectId: number
): Promise<{ render_id: number; status: string } | null> {
  return request(`/api/render/active/${projectId}`);
}

export async function cancelRender(renderId: number): Promise<void> {
  return request(`/api/render/${renderId}`, { method: "DELETE" });
}

export function connectRenderWs(
  renderId: number,
  onMessage: (data: RenderProgress) => void
): WebSocket {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(
    `${protocol}//${window.location.host}/api/render/ws/${renderId}`
  );
  ws.onmessage = (event) => {
    onMessage(JSON.parse(event.data));
  };
  return ws;
}

// ─── Casting ─────────────────────────────────────────────

export async function discoverCastDevices(): Promise<CastDevice[]> {
  const res = await request<{ devices: CastDevice[] }>("/api/cast/devices");
  return res.devices;
}

export async function castVideo(
  deviceId: string,
  videoUrl: string,
  title?: string
): Promise<{ status: string }> {
  return request("/api/cast/play", {
    method: "POST",
    body: JSON.stringify({
      device_id: deviceId,
      video_url: videoUrl,
      title: title ?? "Power Hour",
    }),
  });
}

export async function stopCasting(): Promise<void> {
  return request("/api/cast/stop", { method: "POST" });
}

// ─── Health ──────────────────────────────────────────────

export async function healthCheck(): Promise<{
  status: string;
  version: string;
  /** This PC's LAN address ("" when unknown) and the frontend port, for share links. */
  lan_host?: string;
  frontend_port?: number;
}> {
  return request("/api/health");
}

// ─── Changeover Clip ─────────────────────────────────────

/** Extras the builder can add around a manual transition. */
export interface TransitionWrap {
  countdown: boolean; // corner 3·2·1 over the end of the clip
  drinkEnding: string; // "" = none, else a cue sound name ("can", "clink", ...)
  drinkArt: string; // bundled art file name ("" = pick one)
  drinkWord: string; // "DRINK!", "SHOT!", ...
}

export const DEFAULT_TRANSITION_WRAP: TransitionWrap = {
  countdown: true,
  drinkEnding: "",
  drinkArt: "",
  drinkWord: "DRINK!",
};

function wrapBody(wrap?: TransitionWrap) {
  const w = wrap ?? DEFAULT_TRANSITION_WRAP;
  return {
    countdown: w.countdown,
    drink_ending: w.drinkEnding,
    drink_art: w.drinkArt,
    drink_word: w.drinkWord,
  };
}

export interface TransitionAssets {
  art: { name: string; url: string }[];
  sounds: string[];
  words: string[];
}

export async function getTransitionAssets(): Promise<TransitionAssets> {
  return request(`/api/changeover/assets/catalog`);
}

// ─── AI transition review ────────────────────────────────

export interface AiTransitionItem {
  id: number;
  position: number;
  label: string;
  kind: "card" | "youtube";
  youtube_id: string;
  status: "building" | "ready" | "error" | string;
  error_message: string;
  duration: number;
  preview_url: string;
  /** Video moments only: the whole kept source video (until the render) for re-trimming. */
  source_url: string;
  source_seconds: number;
  /** Waveform of the whole source, for the trim editor. */
  waveform: number[];
  /** Seconds into the whole source. */
  trim_start: number;
  trim_end: number;
  /** The call word shown at the end ("" = none). */
  drink_text: string;
}

export interface AiTransitionReview {
  state: "idle" | "planning" | "building";
  error: string;
  transitions: AiTransitionItem[];
}

export async function getAiTransitions(projectId: number): Promise<AiTransitionReview> {
  return request(`/api/ai-transitions/${projectId}`);
}

export async function generateAiTransitions(
  projectId: number,
  params: { prompt: string; count: number; sources: "cards" | "youtube" | "both"; drink_text?: string }
): Promise<{ state: string }> {
  return request(`/api/ai-transitions/${projectId}/generate`, {
    method: "POST",
    body: JSON.stringify(params),
  });
}

export async function regenerateAiTransition(
  projectId: number,
  rowId: number,
  params: { prompt: string; kind?: "card" | "youtube"; drink_text?: string }
): Promise<AiTransitionItem> {
  return request(`/api/ai-transitions/${projectId}/${rowId}/regenerate`, {
    method: "POST",
    body: JSON.stringify(params),
  });
}

export async function addAiTransition(
  projectId: number,
  params: { prompt: string; kind: "card" | "youtube"; drink_text?: string }
): Promise<{ id: number }> {
  return request(`/api/ai-transitions/${projectId}/add`, {
    method: "POST",
    body: JSON.stringify(params),
  });
}

export async function trimAiTransition(
  projectId: number,
  rowId: number,
  range: { start: number; end: number; drink_text?: string }
): Promise<AiTransitionItem> {
  return request(`/api/ai-transitions/${projectId}/${rowId}/trim`, {
    method: "POST",
    body: JSON.stringify(range),
  });
}

/** Rebuild one transition with a new call word ("" = no text), same range / art. */
export async function setAiTransitionText(
  projectId: number,
  rowId: number,
  drinkText: string
): Promise<AiTransitionItem> {
  return request(`/api/ai-transitions/${projectId}/${rowId}/text`, {
    method: "POST",
    body: JSON.stringify({ drink_text: drinkText }),
  });
}

export async function deleteAiTransition(projectId: number, rowId: number): Promise<void> {
  return request(`/api/ai-transitions/${projectId}/${rowId}`, { method: "DELETE" });
}

export async function getChangoverClip(projectId: number): Promise<ChangoverClip | null> {
  try {
    return await request<ChangoverClip>(`/api/changeover/${projectId}`);
  } catch (err) {
    // 404 means no clip configured yet — not an error
    if (err instanceof Error && err.message.includes("404")) return null;
    throw err;
  }
}

export async function buildChangoverImageAudio(
  projectId: number,
  params: { image?: File; audio?: File; duration: number },
  wrap?: TransitionWrap
): Promise<ChangoverClip> {
  const form = new FormData();
  if (params.image) form.append("image", params.image);
  if (params.audio) form.append("audio", params.audio);
  form.append("duration", String(params.duration));
  const w = wrapBody(wrap);
  form.append("countdown", String(w.countdown));
  form.append("drink_ending", w.drink_ending);
  form.append("drink_art", w.drink_art);
  form.append("drink_word", w.drink_word);
  const res = await fetch(`/api/changeover/${projectId}`, { method: "POST", body: form });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

export async function startChangoverYoutubeDownload(
  projectId: number,
  params: { youtube_id: string; title: string }
): Promise<ChangoverClip> {
  return request(`/api/changeover/${projectId}/youtube`, {
    method: "POST",
    body: JSON.stringify(params),
  });
}

export async function uploadChangoverVideo(
  projectId: number,
  video: File
): Promise<ChangoverClip> {
  const form = new FormData();
  form.append("video", video);
  const res = await fetch(`/api/changeover/${projectId}/upload-video`, { method: "POST", body: form });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

export async function buildChangoverVideoTrim(
  projectId: number,
  params: { trim_start: number; trim_end: number },
  wrap?: TransitionWrap
): Promise<ChangoverClip> {
  return request(`/api/changeover/${projectId}/build`, {
    method: "POST",
    body: JSON.stringify({ ...params, ...wrapBody(wrap) }),
  });
}

export async function startChangoverYoutubeAudioDownload(
  projectId: number,
  params: { youtube_id: string; title: string }
): Promise<ChangoverClip> {
  return request(`/api/changeover/${projectId}/youtube-audio`, {
    method: "POST",
    body: JSON.stringify(params),
  });
}

export async function buildChangoverYoutubeAudio(
  projectId: number,
  params: { audio_trim_start: number; duration: number },
  wrap?: TransitionWrap
): Promise<ChangoverClip> {
  return request(`/api/changeover/${projectId}/build`, {
    method: "POST",
    body: JSON.stringify({ ...params, ...wrapBody(wrap) }),
  });
}

export async function setChangoverImage(
  projectId: number,
  image: File | null
): Promise<ChangoverClip> {
  const form = new FormData();
  if (image) form.append("image", image);
  const res = await fetch(`/api/changeover/${projectId}/image`, { method: "PATCH", body: form });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

export async function deleteChangoverClip(projectId: number): Promise<void> {
  return request(`/api/changeover/${projectId}`, { method: "DELETE" });
}
