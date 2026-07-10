SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  author_handle TEXT,
  source_path TEXT,
  output_dir TEXT NOT NULL,
  created_at TEXT NOT NULL,
  status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_videos (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  path TEXT NOT NULL,
  uploaded_at TEXT,
  duration REAL,
  width INTEGER,
  height INTEGER,
  fps REAL,
  video_codec TEXT,
  audio_codec TEXT,
  metadata_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transcripts (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  language TEXT,
  duration REAL,
  transcript_json_path TEXT NOT NULL,
  srt_path TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS moments (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  start REAL NOT NULL,
  end REAL NOT NULL,
  duration REAL NOT NULL,
  text TEXT NOT NULL,
  summary TEXT NOT NULL,
  moment_type TEXT NOT NULL,
  hook_text TEXT NOT NULL,
  payoff_text TEXT,
  semantic_interest_score REAL NOT NULL,
  hook_score REAL NOT NULL,
  clarity_score REAL NOT NULL,
  emotion_score REAL NOT NULL,
  novelty_score REAL NOT NULL,
  standalone_score REAL NOT NULL,
  retention_score REAL NOT NULL,
  speech_density_score REAL NOT NULL,
  audio_energy_score REAL NOT NULL,
  visual_energy_score REAL NOT NULL,
  base_score REAL NOT NULL,
  personal_score REAL NOT NULL,
  final_score REAL NOT NULL,
  reason TEXT NOT NULL,
  problems_json TEXT NOT NULL,
  suggested_title TEXT NOT NULL,
  suggested_caption TEXT NOT NULL,
  source_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clips (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  moment_id TEXT NOT NULL REFERENCES moments(id) ON DELETE CASCADE,
  start REAL NOT NULL,
  end REAL NOT NULL,
  duration REAL NOT NULL,
  selected INTEGER NOT NULL DEFAULT 1,
  rendered INTEGER NOT NULL DEFAULT 0,
  output_path TEXT,
  subtitle_srt_path TEXT,
  subtitle_ass_path TEXT,
  edit_plan_path TEXT,
  metadata_path TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS edit_plans (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  clip_id TEXT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
  profile TEXT NOT NULL,
  operations_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  clip_id TEXT,
  moment_id TEXT,
  action TEXT NOT NULL,
  user_rating INTEGER,
  user_note TEXT,
  old_start REAL,
  old_end REAL,
  new_start REAL,
  new_end REAL,
  features_json TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS publish_metrics (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  clip_id TEXT NOT NULL,
  moment_id TEXT,
  platform TEXT NOT NULL,
  published_url TEXT,
  views INTEGER,
  likes INTEGER,
  comments INTEGER,
  shares INTEGER,
  saves INTEGER,
  avg_watch_time_sec REAL,
  retention_percent REAL,
  posted_at TEXT,
  captured_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ranking_models (
  id TEXT PRIMARY KEY,
  version TEXT NOT NULL,
  model_path TEXT NOT NULL,
  training_rows INTEGER NOT NULL,
  metrics_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 0
);
"""
