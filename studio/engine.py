from __future__ import annotations
import csv
import json
import queue
import threading
import traceback
import zipfile
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .articles import create_article
from .domain.models import VideoResult
from .asr import Whisper, transcribe
from .config import RunOptions
from .links import Link, parse_link
from .store import Store
from .youtube import discover, ensure_audio
from .utils import short_hash, redact_error




class Engine:
    def __init__(self, root: Path, scratch: Path):
        self.store = Store(root, scratch)
        self.whisper = Whisper(root)

    def close(self):
        self.store.close()

    def one(self, vid: str, opts: RunOptions, notify: Callable[[str], None]) -> VideoResult:
        result = VideoResult(video_id=vid, title=(self.store.video(vid) or {}).get("title", vid))
        try:
            audio, meta, reused = ensure_audio(self.store, vid, only_existing=opts.only_existing)
            result.audio = str(audio)
            result.title = meta.get("title", result.title)
            notify(f"{vid}: {'复用已有' if reused else '下载成功'} MP3")
            run_key, transcript_text, txt = transcribe(self.store, vid, audio, opts, self.whisper, notify)
            result.transcript = str(txt)
            article = create_article(self.store, vid, run_key, transcript_text, meta, opts, notify)
            result.article = str(article)
            result.status = "complete"
        except Exception as exc:
            result.status = "failed"
            result.error = f"{type(exc).__name__}: {redact_error(exc, [opts.whisper_key, opts.llm_key])}"
            notify(f"{vid}: 失败: {result.error[:320]}")
        return result

    def run(self, options: RunOptions, notify: Callable[[str], None] = lambda s: None,
            on_result: Callable[[VideoResult], None] = lambda r: None):
        opts = options.validate()
        link = parse_link(opts.url)
        notify(f"输入类型: {link.kind}；并发: {opts.concurrency}；来源: {link.url}")
        ids = discover(self.store, link, opts.limit, opts.only_existing, opts.include_shorts_streams)
        notify(f"发现 {len(ids)} 条视频，已保存视频 ID；处理中断可从文件与数据库恢复")
        if not ids:
            raise RuntimeError("未找到可处理视频；请检查链接、频道内容及 ROOT 已有音频")
        results = []
        # Bounded queue: an entire channel can contain thousands of videos.
        with ThreadPoolExecutor(max_workers=int(opts.concurrency), thread_name_prefix="video-job") as pool:
            iterator = iter(ids)
            pending = set()
            for _ in range(min(int(opts.concurrency), len(ids))):
                pending.add(pool.submit(self.one, next(iterator), opts, notify))
            while pending:
                completed, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in completed:
                    result = future.result()
                    results.append(result)
                    on_result(result)
                    notify(f"结果 {len(results)}/{len(ids)} | {result.video_id} | {result.status}")
                    try:
                        new_id = next(iterator)
                    except StopIteration:
                        continue
                    pending.add(pool.submit(self.one, new_id, opts, notify))
        self.store.checkpoint()
        return results

    def make_export(self, results: list[VideoResult], include_audio: bool = False) -> Path:
        """Return single export ZIP; raw media optional because channel archive can be massive."""
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = self.store.scratch / "exports" / f"youtube_audio_{stamp}_{short_hash(str([x.video_id for x in results]))[:8]}.zip"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=4, allowZip64=True) as z:
            manifest = []
            for item in results:
                manifest.append(asdict(item))
                candidates = [item.transcript, item.article,
                              str(self.store.root / "metadata" / f"{item.video_id}.json")]
                if include_audio:
                    candidates.append(item.audio)
                for raw in candidates:
                    if not raw:
                        continue
                    p = Path(raw)
                    if not p.is_file():
                        continue
                    try:
                        rel = p.relative_to(self.store.root)
                    except ValueError:
                        continue
                    z.write(p, arcname=str(rel))
                json_transcript = Path(item.transcript).with_suffix(".json") if item.transcript else None
                if json_transcript and json_transcript.is_file():
                    z.write(json_transcript, arcname=str(json_transcript.relative_to(self.store.root)))
            z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        return path


def stream_run(root: Path, scratch: Path, opts: RunOptions):
    """Thread-safe generator yielding events suitable for Gradio's live UI."""
    messages = queue.Queue()
    done = threading.Event()
    output = {}

    def notify(message: str):
        messages.put(("log", message))

    def worker():
        engine = None
        try:
            engine = Engine(root, scratch)
            items = engine.run(opts, notify, on_result=lambda item: messages.put(("result", item)))
            output["results"] = items
            output["export"] = engine.make_export(items, opts.export_audio)
        except Exception as exc:
            output["error"] = f"{type(exc).__name__}: {exc}"
            notify("运行停止：" + output["error"])
        finally:
            try:
                if engine:
                    engine.close()
            except Exception as close_exc:
                output["error"] = "无法保存最终数据库快照：" + str(close_exc)
                notify(output["error"])
            finally:
                done.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    while not done.is_set() or not messages.empty():
        try:
            yield messages.get(timeout=0.5)
        except queue.Empty:
            pass
    yield ("finished", output)
