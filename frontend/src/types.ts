export type VideoMetadata = {
  duration: number;
  width: number;
  height: number;
  fps: number;
  video_codec: string;
  audio_codec: string;
  raw?: Record<string, unknown>;
};

export type Project = {
  id: string;
  name: string;
  author_handle: string;
  source_path?: string | null;
  output_dir: string;
  created_at: string;
  status: string;
  video?: VideoMetadata | null;
};

export type JobRecord = {
  job_id: string;
  project_id?: string | null;
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled';
  stage: string;
  progress: number;
  message: string;
  logs: string[];
  error?: string | null;
};

export type ClipCandidate = {
  id: string;
  moment_id: string;
  start: number;
  end: number;
  duration: number;
  selected: boolean;
  rendered: boolean;
  final_score: number;
  base_score: number;
  personal_score: number;
  moment_type: string;
  hook_text: string;
  summary: string;
  reason: string;
  problems: string[];
  text: string;
  suggested_title: string;
  suggested_caption: string;
  edit_profile: string;
  latest_feedback_action?: string | null;
  output_path?: string | null;
  metadata_path?: string | null;
};

export type AnalysisState = {
  project: Project;
  clips: ClipCandidate[];
  transcript_preview: string;
};

export type LearningSummary = {
  total_clips_analyzed: number;
  accepted_count: number;
  rejected_count: number;
  top_moment_types: Array<{ moment_type: string; count: number }>;
  average_score_accepted: number;
  metrics_entered: number;
  active_ranker_version: string;
  training_ready: boolean;
  preferred_types: string[];
};
