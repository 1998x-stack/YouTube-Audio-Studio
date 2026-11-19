from __future__ import annotations
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def short_hash(value) -> str:
    data = value if isinstance(value, bytes) else str(value).encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:16]


def dump_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def publish(src: Path, target: Path) -> None:
    """Verify copy before replacing remote artifact; single-writer only."""
    target.parent.mkdir(parents=True, exist_ok=True)
    pending = target.with_name(target.name + ".uploading")
    try:
        shutil.copy2(src, pending)
        if src.stat().st_size != pending.stat().st_size or sha_file(src) != sha_file(pending):
            raise OSError("文件持久化校验失败: " + str(target))
        os.replace(pending, target)
    finally:
        pending.unlink(missing_ok=True)


def publish_text(content: str, target: Path, scratch: Path) -> None:
    scratch.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".tmp", dir=scratch, delete=False) as f:
        f.write(content)
        tmp = Path(f.name)
    try:
        publish(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def ffprobe_seconds(path: Path) -> float:
    command = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
    result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=90)
    return float(result.stdout.strip())


def slice_audio(source: Path, output: Path, start: float, length: float) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", str(start), "-i", str(source), "-t", str(length),
                    "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(output)],
                   check=True, timeout=max(120, int(length * 3)))


def fmt_ms(ms: int) -> str:
    secs = max(0, int(ms) // 1000)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def compatible_url(url: str) -> bool:
    from urllib.parse import urlparse
    u = urlparse(url)
    return u.scheme in ("http", "https") and u.hostname in {"localhost", "127.0.0.1", "::1"}


def redact_error(error: Exception | str, secrets: list[str] | tuple[str, ...] = ()) -> str:
    message = str(error)
    for secret in secrets:
        if secret and len(secret) >= 4:
            message = message.replace(secret, "[REDACTED]")
    return message
