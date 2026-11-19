
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS videos (
    video_id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL,
    uploader TEXT,
    published TEXT,
    description TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    discovered_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assets (
    video_id TEXT PRIMARY KEY REFERENCES videos(video_id),
    media_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    duration_seconds REAL NOT NULL,
    saved_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transcripts (
    video_id TEXT NOT NULL REFERENCES videos(video_id),
    run_key TEXT NOT NULL,
    engine TEXT NOT NULL,
    model TEXT NOT NULL,
    audio_sha TEXT NOT NULL,
    config_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    error TEXT,
    text_path TEXT,
    json_path TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(video_id, run_key)
);
CREATE TABLE IF NOT EXISTS chunks (
    video_id TEXT NOT NULL,
    run_key TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    segments_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(video_id, run_key, chunk_index),
    FOREIGN KEY(video_id,run_key) REFERENCES transcripts(video_id,run_key)
);
CREATE TABLE IF NOT EXISTS articles (
    video_id TEXT NOT NULL,
    run_key TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    llm_model TEXT NOT NULL,
    article_path TEXT NOT NULL,
    body TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(video_id,run_key,prompt_hash,llm_model),
    FOREIGN KEY(video_id,run_key) REFERENCES transcripts(video_id,run_key)
);
CREATE TABLE IF NOT EXISTS jobs (
    video_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(video_id,stage)
);
CREATE INDEX IF NOT EXISTS idx_chunks_video ON chunks(video_id,run_key);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
