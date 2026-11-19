from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from .links import Link, VIDEO_RE
from .store import Store
from .utils import ffprobe_seconds, publish, publish_text, sha_file

PUBLIC_META_FIELDS = ["id", "title", "description", "webpage_url", "channel", "channel_id",
                      "uploader", "uploader_id", "upload_date", "duration", "view_count",
                      "like_count", "comment_count", "categories", "tags", "chapters", "language", "license"]


def clean_meta(info: dict) -> dict:
    return {k: info[k] for k in PUBLIC_META_FIELDS if info.get(k) is not None}


def discover(store: Store, link: Link, limit: str, only_existing: bool = False,
             include_extra: bool = False) -> list[str]:
    if link.kind == "video":
        store.put_video(link.video_id)
        store.checkpoint()
        return [link.video_id]
    if only_existing:
        # Filter locally cached audio by uploader handle where possible.
        from urllib.parse import urlparse
        handle = urlparse(link.url).path.split("/")[1].lower().lstrip("@") if "/@" in link.url else ""
        with store.lock:
            rows = store.conn.execute("SELECT video_id,metadata_json FROM videos ORDER BY discovered_at DESC").fetchall()
        matches = []
        for vid, raw in rows:
            if not (store.root / "media" / f"{vid}.mp3").exists():
                continue
            meta = json.loads(raw or "{}")
            if handle and handle not in str(meta.get("uploader_id", "")).lower().lstrip("@"):
                continue
            matches.append(vid)
        if limit != "全部":
            matches = matches[:int(limit)]
        return matches
    from yt_dlp import YoutubeDL
    opts = {"extract_flat": "in_playlist", "skip_download": True,
            "ignoreerrors": True, "quiet": True, "no_warnings": False,
            "socket_timeout": 35, "retries": 3,
            "playlistend": int(limit) if limit != "全部" else -1}
    # Standard /videos page only covers long-form videos. Optional channel-wide
    # discovery also scans Shorts and live-stream archives and deduplicates IDs.
    urls = [link.url]
    if include_extra and link.kind == "channel":
        base = link.url.rsplit("/", 1)[0]
        urls += [base + "/shorts", base + "/streams"]
    found = []
    for url in urls:
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception:
            if len(urls) == 1:
                raise
            continue
        if not info or not info.get("entries"):
            if len(urls) == 1:
                raise RuntimeError("频道/播放列表未返回视频。确认链接、网络、Deno/EJS、视频是否公开。")
            continue
        for entry in info["entries"]:
            if not isinstance(entry, dict):
                continue
            vid = entry.get("id")
            if not isinstance(vid, str) or not VIDEO_RE.fullmatch(vid) or vid in found:
                continue
            store.put_video(vid, entry.get("title", ""))
            found.append(vid)
            if limit != "全部" and len(found) >= int(limit):
                break
        if limit != "全部" and len(found) >= int(limit):
            break
    store.checkpoint()
    return found


def ensure_audio(store: Store, vid: str, only_existing: bool = False) -> tuple[Path, dict, bool]:
    root = store.root
    audio = root / "media" / f"{vid}.mp3"
    metapath = root / "metadata" / f"{vid}.json"
    if audio.exists() and audio.stat().st_size > 1024:
        try:
            duration = ffprobe_seconds(audio)
            if duration > 0:
                meta = {}
                if metapath.exists():
                    try:
                        meta = json.loads(metapath.read_text(encoding="utf-8"))
                    except (ValueError, OSError):
                        pass
                if not meta:
                    meta = {"id": vid, "title": (store.video(vid) or {}).get("title", vid),
                            "webpage_url": f"https://www.youtube.com/watch?v={vid}"}
                    publish_text(json.dumps(meta, ensure_ascii=False, indent=2), metapath, store.scratch / "tmp")
                store.put_video(vid, meta.get("title", ""), meta)
                asset = store.get_audio(vid)
                if not asset or asset["byte_size"] != audio.stat().st_size:
                    store.put_audio(vid, audio, sha_file(audio), duration)
                store.job(vid, "download", "complete")
                store.checkpoint()
                return audio, meta, True
        except Exception:
            # Invalid local media -> download a fresh copy unless in offline-only mode.
            if only_existing:
                raise RuntimeError(f"本地 MP3 不可解码: {audio}")
    if only_existing:
        raise FileNotFoundError("当前 ROOT 中没有该视频的有效 MP3：" + vid)
    from yt_dlp import YoutubeDL
    store.job(vid, "download", "running")
    store.checkpoint()
    work = store.scratch / "downloads" / vid
    work.mkdir(parents=True, exist_ok=True)
    opts = {"format": "bestaudio/best", "noplaylist": True,
            "quiet": True, "ignoreerrors": False,
            "continuedl": True, "retries": 5, "fragment_retries": 5,
            "socket_timeout": 45, "outtmpl": str(work / "%(id)s.%(ext)s"),
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "64"}],
            "overwrites": False}
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=True)
        if not isinstance(info, dict):
            raise RuntimeError("yt-dlp 未返回可用视频元数据")
        file = work / f"{vid}.mp3"
        if not file.exists() or file.stat().st_size <= 1024:
            raise RuntimeError("FFmpeg 未生成完整 MP3: " + str(file))
        duration = ffprobe_seconds(file)
        if duration <= 0:
            raise RuntimeError("音频时长无效")
        publish(file, audio)
        meta = clean_meta(info)
        publish_text(json.dumps(meta, ensure_ascii=False, indent=2), metapath, store.scratch / "tmp")
        store.put_video(vid, meta.get("title", ""), meta)
        store.put_audio(vid, audio, sha_file(audio), duration)
        store.job(vid, "download", "complete")
        store.checkpoint()
        return audio, meta, False
    except Exception as exc:
        store.job(vid, "download", "failed", str(exc))
        store.checkpoint()
        raise
    finally:
        # Keep only .part files if download failed? Scratch may be recycled anyway.
        for file in work.glob(f"{vid}.*"):
            if file.suffix == ".mp3":
                file.unlink(missing_ok=True)
