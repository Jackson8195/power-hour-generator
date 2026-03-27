export interface SearchResult {
  youtube_id: string;
  title: string;
  artist: string;
  thumbnail: string;
  duration: string;
  view_count: string;
}

export type ClipStatus = "pending" | "downloading" | "analyzing" | "ready" | "error";
export type RenderStatus = "queued" | "rendering" | "complete" | "error";

export interface Clip {
  id: number;
  project_id: number;
  position: number;
  source_title: string;
  source_artist: string;
  source_thumbnail: string;
  youtube_id: string;
  file_path: string;
  duration: number;
  start_time: number;
  end_time: number;
  suggested_start: number | null;
  bpm: number | null;
  energy: number | null;
  status: ClipStatus;
}

export interface Project {
  id: number;
  name: string;
  description: string;
  clip_duration: number;
  transition_type: string;
  created_at: string;
  updated_at: string;
  clip_count: number;
}

export interface ProjectDetail extends Project {
  clips: Clip[];
}

export interface RenderProgress {
  render_id: number;
  status: RenderStatus;
  progress: number;
  output_path: string;
  error_message: string;
}

export interface CastDevice {
  id: string;
  name: string;
  type: string;
  model: string;
}
