from __future__ import annotations
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

VIDEO_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
CHANNEL_SEGMENTS = {"videos", "shorts", "streams", "featured", "playlists", "community"}

@dataclass(frozen=True)
class Link:
    kind: str  # video | channel | playlist
    url: str
    video_id: str = ""


def parse_link(raw: str) -> Link:
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("请输入 YouTube 视频、频道或播放列表链接")
    if raw.startswith("@"):
        raw = "https://www.youtube.com/" + raw
    if raw.startswith("www.youtube.com/") or raw.startswith("youtube.com/") or raw.startswith("youtu.be/"):
        raw = "https://" + raw
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in HOSTS:
        raise ValueError("仅支持 youtube.com 和 youtu.be 的 HTTPS 链接，不接受其他域名")
    # Strip query parameters and fragments from user/channel links; do not forward
    # arbitrary options or unsupported remote URL protocols to yt-dlp.
    path = parsed.path.strip("/")
    pieces = [p for p in path.split("/") if p]
    query = parse_qs(parsed.query)
    vid = ""
    if parsed.hostname == "youtu.be":
        vid = pieces[0] if len(pieces) == 1 else ""
    elif pieces and pieces[0] == "watch":
        vid = query.get("v", [""])[0]
    elif len(pieces) == 2 and pieces[0] in ("shorts", "live", "embed"):
        vid = pieces[1]
    if vid:
        if not VIDEO_RE.fullmatch(vid):
            raise ValueError("无效的 YouTube 视频 ID")
        return Link("video", f"https://www.youtube.com/watch?v={vid}", vid)
    if parsed.hostname == "youtu.be":
        raise ValueError("无效的 youtu.be 视频链接")
    if path == "playlist" and query.get("list", [""])[0]:
        pl = query["list"][0]
        if not re.fullmatch(r"[A-Za-z0-9_-]{10,128}", pl):
            raise ValueError("无效的 YouTube 播放列表 ID")
        return Link("playlist", f"https://www.youtube.com/playlist?list={pl}")
    if pieces and (pieces[0].startswith("@") or pieces[0] in {"channel", "c", "user"}):
        if pieces[0].startswith("@"):
            if len(pieces) > 2 or not re.fullmatch(r"@[\w.\-]{1,100}", pieces[0]):
                raise ValueError("无效的频道 Handle")
            handle = pieces[0]
            if len(pieces) == 2 and pieces[1] not in CHANNEL_SEGMENTS:
                raise ValueError("不支持的频道子页面")
            return Link("channel", f"https://www.youtube.com/{handle}/videos")
        if len(pieces) not in {2, 3} or not re.fullmatch(r"[A-Za-z0-9_\-]{2,120}", pieces[1]):
            raise ValueError("无效的频道地址")
        if len(pieces) == 3 and pieces[2] not in CHANNEL_SEGMENTS:
            raise ValueError("不支持的频道子页面")
        return Link("channel", f"https://www.youtube.com/{pieces[0]}/{pieces[1]}/videos")
    raise ValueError("无法识别：请粘贴 /watch、/shorts、频道首页或 /playlist 链接")
