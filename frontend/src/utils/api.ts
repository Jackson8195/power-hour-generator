import type {
  AutoGenerateApproval,
  AutoGenerateProject,
  AutoGenerateJobProgress,
  AutoGenerateProposalJobStart,
  AutoGenerateProposalJobStatus,
  AutoGenerateReplaceJobStart,
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

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `Request failed: ${res.status}`);
  }
  return res.json();
}

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
  music = true
): Promise<AutoGenerateProposalJobStart> {
  return request("/api/auto-generate/proposals", {
    method: "POST",
    body: JSON.stringify({ prompt, music }),
  });
}

export async function startReplaceAutoGenerateProposalItem(
  proposalId: string,
  slotIndex: number
): Promise<AutoGenerateReplaceJobStart> {
  return request(`/api/auto-generate/proposals/${proposalId}/replace`, {
    method: "POST",
    body: JSON.stringify({ slot_index: slotIndex }),
  });
}

export async function getAutoGenerateProposalJob(
  jobId: string
): Promise<AutoGenerateProposalJobStatus> {
  return request(`/api/auto-generate/proposal-jobs/${jobId}`);
}

export async function approveAutoGenerateProposal(
  proposalId: string,
  opts: { projectName?: string; projectId?: number | null; includeTransition?: boolean } = {}
): Promise<AutoGenerateApproval> {
  return request(`/api/auto-generate/proposals/${proposalId}/approve`, {
    method: "POST",
    body: JSON.stringify({
      project_name: opts.projectName ?? "",
      project_id: opts.projectId ?? null,
      include_transition: opts.includeTransition ?? true,
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
  }
): Promise<{ render_id: number }> {
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
}> {
  return request("/api/health");
}

// ─── Changeover Clip ─────────────────────────────────────

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
  params: { image?: File; audio?: File; duration: number }
): Promise<ChangoverClip> {
  const form = new FormData();
  if (params.image) form.append("image", params.image);
  if (params.audio) form.append("audio", params.audio);
  form.append("duration", String(params.duration));
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
  params: { trim_start: number; trim_end: number }
): Promise<ChangoverClip> {
  return request(`/api/changeover/${projectId}/build`, {
    method: "POST",
    body: JSON.stringify(params),
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
  params: { audio_trim_start: number; duration: number }
): Promise<ChangoverClip> {
  return request(`/api/changeover/${projectId}/build`, {
    method: "POST",
    body: JSON.stringify(params),
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
