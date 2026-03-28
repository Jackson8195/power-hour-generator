import type {
  AutoGenerateApproval,
  AutoGenerateJobProgress,
  AutoGenerateProposal,
  SearchResult,
  Project,
  ProjectDetail,
  Clip,
  ClipAnalysis,
  RenderProgress,
  RenderLibraryEntry,
  CastDevice,
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
  projectId?: number
): Promise<SearchResult[]> {
  return request("/api/search/youtube", {
    method: "POST",
    body: JSON.stringify({
      query,
      max_results: maxResults,
      project_id: projectId,
    }),
  });
}

export async function getRecommendedTracks(
  projectId: number,
  maxResults = 8
): Promise<SearchResult[]> {
  return request(`/api/search/recommendations/${projectId}?max_results=${maxResults}`);
}

export async function createAutoGenerateProposal(
  prompt: string
): Promise<AutoGenerateProposal> {
  return request("/api/auto-generate/proposals", {
    method: "POST",
    body: JSON.stringify({ prompt }),
  });
}

export async function replaceAutoGenerateProposalItem(
  proposalId: string,
  slotIndex: number
): Promise<AutoGenerateProposal> {
  return request(`/api/auto-generate/proposals/${proposalId}/replace`, {
    method: "POST",
    body: JSON.stringify({ slot_index: slotIndex }),
  });
}

export async function approveAutoGenerateProposal(
  proposalId: string,
  projectName?: string
): Promise<AutoGenerateApproval> {
  return request(`/api/auto-generate/proposals/${proposalId}/approve`, {
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
): Promise<{ clip_id: number; status: string; file_path: string }> {
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
  ffmpeg_path: string;
  youtube_api_configured: boolean;
}> {
  return request("/api/health");
}
