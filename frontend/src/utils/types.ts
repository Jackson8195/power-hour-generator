export interface SearchResult {
  youtube_id: string;
  title: string;
  artist: string;
  thumbnail: string;
  duration: string;
  view_count: string;
  search_source: string;
  match_score: number;
  recommendation_reason: string;
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
  preview_url: string;
  has_selection: boolean;
  file_missing: boolean;
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
  gpu_active?: boolean;
}

export interface RenderLibraryEntry {
  render_id: number;
  project_id: number;
  project_name: string;
  output_url: string;
  completed_at: string | null;
}

export interface CastDevice {
  id: string;
  name: string;
  type: string;
  model: string;
}

export interface ClipHighlight {
  start: number;
  end: number;
  score: number;
  label: string;
}

export interface ClipAnalysis {
  clip_id: number;
  preview_url: string;
  duration: number;
  suggested_start: number;
  suggested_end: number;
  waveform: number[];
  highlights: ClipHighlight[];
}

export interface AutoGenerateProposalItem {
  slot_index: number;
  requested_title: string;
  requested_artist: string;
  youtube_id: string;
  title: string;
  artist: string;
  thumbnail: string;
  duration: string;
  resolution_source: string;
  reason: string;
  status: "resolved" | "unresolved";
}

export interface AutoGenerateProposal {
  proposal_id: string;
  normalized_prompt: string;
  items: AutoGenerateProposalItem[];
  unresolved_count: number;
  expires_at: string;
}

export interface AutoGenerateApproval {
  project_id: number;
  job_id: string;
  clip_ids: number[];
}

export interface AutoGenerateJobProgress {
  job_id: string;
  project_id: number;
  phase: "queued" | "processing" | "rendering" | "complete" | "error";
  progress: number;
  total_clips: number;
  processed_clips: number;
  current_step: string;
  current_title: string;
  current_artist: string;
  render_id: number | null;
  output_path: string;
  error_message: string;
  updated_at: string;
}

export interface AutoGenerateProposalJobStart {
  proposal_job_id: string;
}

export interface AutoGenerateReplaceJobStart {
  replace_job_id: string;
}

export interface AutoGenerateProposalJobStatus {
  job_id: string;
  status: "pending" | "complete" | "error";
  error_message: string;
  proposal: AutoGenerateProposal | null;
  updated_at: string;
}
