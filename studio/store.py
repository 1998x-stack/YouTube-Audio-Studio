from __future__ import annotations

import json
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .links import VIDEO_RE
from .utils import publish, publish_text, dump_json

SCHEMA = """
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
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    """Thread-safe single-process SQLite writer with verified Drive snapshots.

    The Drive directory is NOT a distributed lock. Run one app process per ROOT.
    Existing zhuweiyi catalog.db is left unchanged; Studio uses studio_catalog.db.
    """

    def __init__(self, root: Path, scratch: Path):
        self.root, self.scratch = Path(root), Path(scratch)
        self.lock = threading.RLock()
        for name in ["db", "media", "metadata", "transcripts", "articles", "models", "exports"]:
            (self.root / name).mkdir(parents=True, exist_ok=True)
        for name in ["db", "downloads", "chunks", "exports", "tmp"]:
            (self.scratch / name).mkdir(parents=True, exist_ok=True)
        self.local = self.scratch / "db/studio_catalog.db"
        self.remote = self.root / "db/studio_catalog.db"
        self.previous = self.root / "db/studio_catalog.prev.db"
        if not self.local.exists():
            found_bad = []
            for candidate in (self.remote, self.previous):
                if not candidate.exists():
                    continue
                try:
                    shutil.copy2(candidate, self.local)
                    with sqlite3.connect(self.local) as check:
                        if check.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                            raise RuntimeError("SQLite quick_check failed")
                    break
                except Exception as e:
                    found_bad.append((str(candidate), str(e)))
                    self.local.unlink(missing_ok=True)
            if not self.local.exists() and found_bad:
                raise RuntimeError("两个 SQLite 快照均损坏，请备份后人工修复：" + str(found_bad))
        self.conn = sqlite3.connect(self.local, timeout=60, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=60000")
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self.reconcile_assets()
        self.checkpoint()

    @contextmanager
    def tx(self):
        with self.lock:
            with self.conn:
                yield self.conn

    def checkpoint(self):
        """Serialize local transactions then use SQLite online backup, publish verified snapshot."""
        with self.lock:
            self.conn.commit()
            snapshot = self.scratch / "db/studio_catalog.snapshot.db"
            snapshot.unlink(missing_ok=True)
            target = sqlite3.connect(snapshot)
            try:
                self.conn.backup(target)
            finally:
                target.close()
            try:
                if self.remote.exists():
                    # Validate old snapshot before keeping as previous version.
                    try:
                        with sqlite3.connect(self.remote) as old:
                            if old.execute("PRAGMA quick_check").fetchone()[0] == "ok":
                                publish(self.remote, self.previous)
                    except (sqlite3.DatabaseError, OSError):
                        pass
                publish(snapshot, self.remote)
            finally:
                snapshot.unlink(missing_ok=True)

    def close(self):
        with self.lock:
            self.checkpoint()
            self.conn.close()

    def video(self, vid: str) -> dict | None:
        with self.lock:
            row = self.conn.execute("SELECT * FROM videos WHERE video_id=?", (vid,)).fetchone()
            return dict(row) if row else None

    def put_video(self, vid: str, title: str = "", metadata: dict | None = None):
        if not VIDEO_RE.fullmatch(vid):
            raise ValueError("invalid youtube ID")
        metadata = metadata or {}
        title = str(metadata.get("title") or title or vid)
        with self.tx() as db:
            db.execute("""INSERT INTO videos(video_id,title,source_url,uploader,published,description,metadata_json,discovered_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(video_id) DO UPDATE SET
              title=CASE WHEN excluded.title != videos.video_id THEN excluded.title ELSE videos.title END,
              uploader=COALESCE(excluded.uploader,videos.uploader),
              published=COALESCE(excluded.published,videos.published),
              description=COALESCE(excluded.description,videos.description),
              metadata_json=CASE WHEN excluded.metadata_json != '{}' THEN excluded.metadata_json ELSE videos.metadata_json END,
              updated_at=excluded.updated_at""",
              (vid, title, f"https://www.youtube.com/watch?v={vid}",
               metadata.get("uploader") or metadata.get("channel"), metadata.get("upload_date"),
               metadata.get("description"), dump_json(metadata), now(), now()))

    def put_audio(self, vid: str, path: Path, sha256: str, duration: float):
        with self.tx() as db:
            db.execute("""INSERT INTO assets(video_id,media_path,sha256,byte_size,duration_seconds,saved_at)
              VALUES(?,?,?,?,?,?) ON CONFLICT(video_id) DO UPDATE SET
              media_path=excluded.media_path,sha256=excluded.sha256,byte_size=excluded.byte_size,
              duration_seconds=excluded.duration_seconds,saved_at=excluded.saved_at""",
              (vid, str(path.relative_to(self.root)), sha256, path.stat().st_size, duration, now()))

    def get_audio(self, vid: str) -> dict | None:
        with self.lock:
            row = self.conn.execute("SELECT * FROM assets WHERE video_id=?", (vid,)).fetchone()
            return dict(row) if row else None

    def job(self, vid: str, stage: str, status: str, error: str = ""):
        with self.tx() as db:
            db.execute("""INSERT INTO jobs(video_id,stage,status,attempts,error,updated_at)
              VALUES(?,?,?,1,?,?) ON CONFLICT(video_id,stage) DO UPDATE SET
              status=excluded.status,
              attempts=jobs.attempts+CASE WHEN excluded.status='running' THEN 1 ELSE 0 END,
              error=excluded.error,updated_at=excluded.updated_at""",
              (vid, stage, status, str(error)[:800], now()))

    def transcript(self, vid: str, run_key: str) -> dict | None:
        with self.lock:
            row = self.conn.execute("SELECT * FROM transcripts WHERE video_id=? AND run_key=?", (vid, run_key)).fetchone()
            return dict(row) if row else None

    def start_transcript(self, vid: str, run_key: str, engine: str, model: str, audio_sha: str, cfg: dict):
        with self.tx() as db:
            db.execute("""INSERT INTO transcripts(video_id,run_key,engine,model,audio_sha,config_json,status,updated_at)
              VALUES(?,?,?,?,?,?,'running',?) ON CONFLICT(video_id,run_key) DO UPDATE SET
              status=CASE WHEN transcripts.status='complete' THEN 'complete' ELSE 'running' END,
              error=NULL,updated_at=excluded.updated_at""",
              (vid, run_key, engine, model, audio_sha, dump_json(cfg), now()))

    def save_chunk(self, vid: str, run_key: str, index: int, start_ms: int, end_ms: int, segments: list[dict]):
        with self.tx() as db:
            db.execute("""INSERT INTO chunks(video_id,run_key,chunk_index,start_ms,end_ms,segments_json,updated_at)
              VALUES(?,?,?,?,?,?,?) ON CONFLICT(video_id,run_key,chunk_index) DO UPDATE SET
              segments_json=excluded.segments_json,start_ms=excluded.start_ms,
              end_ms=excluded.end_ms,updated_at=excluded.updated_at""",
              (vid, run_key, index, start_ms, end_ms, dump_json(segments), now()))
        self.checkpoint()  # essential: survive Colab runtime teardown after each audio chunk

    def chunk_indices(self, vid: str, run_key: str) -> set[int]:
        with self.lock:
            return {int(row[0]) for row in self.conn.execute(
                "SELECT chunk_index FROM chunks WHERE video_id=? AND run_key=?", (vid, run_key))}

    def segments(self, vid: str, run_key: str) -> list[dict]:
        with self.lock:
            rows = self.conn.execute("""SELECT segments_json FROM chunks
              WHERE video_id=? AND run_key=? ORDER BY chunk_index""", (vid, run_key)).fetchall()
        out = []
        for row in rows:
            out.extend(json.loads(row[0]))
        return out

    def finish_transcript(self, vid: str, run_key: str, txt: Path, js: Path):
        with self.tx() as db:
            db.execute("""UPDATE transcripts SET status='complete',error=NULL,text_path=?,json_path=?,updated_at=?
              WHERE video_id=? AND run_key=?""",
              (str(txt.relative_to(self.root)), str(js.relative_to(self.root)), now(), vid, run_key))
        self.checkpoint()

    def fail_transcript(self, vid: str, run_key: str, error: str):
        with self.tx() as db:
            db.execute("UPDATE transcripts SET status='failed',error=?,updated_at=? WHERE video_id=? AND run_key=?",
                       (error[:800], now(), vid, run_key))
        self.checkpoint()

    def article(self, vid: str, run_key: str, prompt_hash: str, llm_model: str) -> dict | None:
        with self.lock:
            r = self.conn.execute("""SELECT * FROM articles
              WHERE video_id=? AND run_key=? AND prompt_hash=? AND llm_model=?""",
              (vid, run_key, prompt_hash, llm_model)).fetchone()
            return dict(r) if r else None

    def put_article(self, vid: str, run_key: str, prompt_hash: str, llm_model: str, path: Path, body: str):
        with self.tx() as db:
            db.execute("""INSERT INTO articles(video_id,run_key,prompt_hash,llm_model,article_path,body,updated_at)
              VALUES(?,?,?,?,?,?,?) ON CONFLICT(video_id,run_key,prompt_hash,llm_model)
              DO UPDATE SET article_path=excluded.article_path,body=excluded.body,updated_at=excluded.updated_at""",
              (vid, run_key, prompt_hash, llm_model, str(path.relative_to(self.root)), body, now()))
        self.checkpoint()

    def reconcile_assets(self):
        """Re-discover existing media/metadata after restoring old DB checkpoint.
        No YouTube requests; do not confuse existing audio with a completed transcript.
        """
        from .utils import sha_file, ffprobe_seconds
        found = set()
        for kind, ext in (("metadata", ".json"), ("media", ".mp3")):
            found.update(p.stem for p in (self.root / kind).glob("*" + ext) if VIDEO_RE.fullmatch(p.stem))
        for vid in sorted(found):
            info = {}
            meta_path = self.root / "metadata" / f"{vid}.json"
            if meta_path.exists():
                try:
                    info = json.loads(meta_path.read_text("utf-8"))
                except (OSError, ValueError):
                    pass
            self.put_video(vid, str(info.get("title", vid)), info)
            audio = self.root / "media" / f"{vid}.mp3"
            if audio.is_file() and audio.stat().st_size > 1024:
                row = self.get_audio(vid)
                if not row or row["byte_size"] != audio.stat().st_size:
                    try:
                        self.put_audio(vid, audio, sha_file(audio), ffprobe_seconds(audio))
                    except Exception:
                        pass
