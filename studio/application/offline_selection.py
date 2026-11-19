"""Strict scope filtering for cached assets.

When offline, neither playlist membership nor a channel's custom URL can be
verified from the legacy catalog. Prefer an explicit error to processing
unrelated media in a shared ROOT directory.
"""
from __future__ import annotations

import json
from urllib.parse import urlparse

from ..domain.links import Link


def select_cached_videos(store, link: Link, limit: str) -> list[str]:
    if link.kind == "playlist":
        raise ValueError(
            "离线模式无法确认播放列表成员。先联网扫描并保存列表清单，"
            "或输入单视频链接；拒绝处理 ROOT 中无关的视频。"
        )
    if link.kind != "channel":
        raise ValueError("本地选择器仅支持频道；单视频由视频 ID 直接定位")

    pieces = [part for part in urlparse(link.url).path.split("/") if part]
    expected_handle = ""
    expected_channel_id = ""
    if pieces and pieces[0].startswith("@"):
        expected_handle = pieces[0].casefold()
    elif len(pieces) >= 2 and pieces[0] == "channel":
        expected_channel_id = pieces[1].casefold()
    else:
        raise ValueError("无法离线核验此频道地址的身份；请使用 /@handle 或 /channel/UC... 格式")

    with store.lock:
        rows = store.conn.execute(
            "SELECT video_id, metadata_json FROM videos "
            "ORDER BY COALESCE(published, '') DESC, discovered_at DESC, video_id"
        ).fetchall()
    found = []
    for vid, raw in rows:
        audio = store.root / "media" / f"{vid}.mp3"
        if not audio.is_file() or audio.stat().st_size <= 1024:
            continue
        try:
            meta = json.loads(raw or "{}")
        except (ValueError, TypeError):
            continue
        if not isinstance(meta, dict):
            continue
        if expected_handle and str(meta.get("uploader_id") or "").casefold() != expected_handle:
            continue
        if expected_channel_id and str(meta.get("channel_id") or "").casefold() != expected_channel_id:
            continue
        found.append(vid)
        if limit != "全部" and len(found) >= int(limit):
            break
    return found
