from __future__ import annotations
import json
import math
import threading
from pathlib import Path
from typing import Callable

from .config import RunOptions
from .store import Store
from .utils import dump_json, fmt_ms, publish_text, sha_file, short_hash, slice_audio, ffprobe_seconds, redact_error


class Whisper:
    def __init__(self, root: Path):
        self.root = root
        self._lock = threading.RLock()  # Protect shared CTranslate2 model & GPU VRAM.
        self._model = None
        self.selected_model = None
        self.device = None

    def init_local(self, requested: str):
        with self._lock:
            if self._model is not None and self.selected_model:
                return self.selected_model
            import av
            if int(av.__version__.split(".")[0]) >= 19:
                from importlib.metadata import version
                if version("faster-whisper") == "1.2.1":
                    raise RuntimeError("faster-whisper 1.2.1 与 PyAV 19 不兼容。请安装 av==18.0.0")
            from faster_whisper import WhisperModel
            import ctranslate2
            try:
                available = ctranslate2.get_cuda_device_count() > 0
            except Exception:
                available = False
            if available:
                try:
                    m = WhisperModel(requested, device="cuda", compute_type="float16",
                                     download_root=str(self.root / "models"))
                    # Runtime CUDA/cuDNN failures are sometimes lazy: make sure inference really works.
                    import numpy as np
                    list(m.transcribe(np.zeros(16000, dtype=np.float32), language="zh",
                                      beam_size=1, vad_filter=False)[0])
                    self._model, self.selected_model, self.device = m, requested, "cuda"
                    return self.selected_model
                except Exception:
                    # A CPU fallback is explicit and fingerprinted, never silently mixes chunks.
                    pass
            cpu_model = requested if requested in ("tiny", "base", "small") else "small"
            self._model = WhisperModel(cpu_model, device="cpu", compute_type="int8",
                                       download_root=str(self.root / "models"))
            self.selected_model, self.device = cpu_model, "cpu"
            return cpu_model

    def decode(self, file: Path, opts: RunOptions) -> list[dict]:
        if opts.asr_mode == "api":
            from openai import OpenAI
            from .utils import compatible_url
            if not compatible_url(opts.whisper_base_url) and not opts.whisper_key.strip():
                raise ValueError("远程 Whisper API 必须设置 API Key；localhost 可以留空")
            client = OpenAI(base_url=opts.whisper_base_url, api_key=opts.whisper_key or "local",
                            timeout=600, max_retries=2)
            kwargs = {"model": opts.whisper_api_model, "response_format": "verbose_json"}
            if opts.language != "auto":
                kwargs["language"] = opts.language
            with file.open("rb") as f:
                answer = client.audio.transcriptions.create(file=f, **kwargs)
            raw = answer.model_dump() if hasattr(answer, "model_dump") else (answer if isinstance(answer, dict) else {})
            segs = raw.get("segments") or []
            if segs:
                return [{"start_ms": round(float(s.get("start", 0)) * 1000),
                         "end_ms": round(float(s.get("end", 0)) * 1000),
                         "text": str(s.get("text", "")).strip()} for s in segs]
            # Compatible providers may return only whole-chunk text.
            return [{"start_ms": 0, "end_ms": 0, "text": str(raw.get("text") or "").strip()}]
        with self._lock:
            model = self._model
            if model is None:
                raise RuntimeError("本地 Whisper 模型尚未初始化")
            result, _ = model.transcribe(str(file), language=None if opts.language == "auto" else opts.language,
                                          beam_size=5, vad_filter=True,
                                          condition_on_previous_text=False)
            return [{"start_ms": round(float(s.start) * 1000),
                     "end_ms": round(float(s.end) * 1000), "text": s.text.strip(),
                     "avg_logprob": s.avg_logprob, "no_speech_prob": s.no_speech_prob}
                    for s in result]


def transcript_key(opts: RunOptions, actual_model: str, audio_sha: str) -> tuple[str, dict]:
    cfg = {"engine": opts.asr_mode, "model": actual_model, "language": opts.language,
           "chunk_seconds": opts.chunk_seconds, "audio_sha": audio_sha,
           "api_base_hash": short_hash(opts.whisper_base_url) if opts.asr_mode == "api" else ""}
    return short_hash(dump_json(cfg)), cfg


def transcribe(store: Store, vid: str, audio: Path, opts: RunOptions, whisper: Whisper,
               notify: Callable[[str], None] = lambda s: None) -> tuple[str, str, Path]:
    selected = (whisper.init_local(opts.whisper_model) if opts.asr_mode == "local"
                else opts.whisper_api_model)
    asset = store.get_audio(vid)
    audio_sha = sha_file(audio)  # Verify actual file, not just stored metadata.
    notify(f"{vid}: ASR 使用 {selected} / {whisper.device if opts.asr_mode == 'local' else 'api'}")
    key, cfg = transcript_key(opts, selected, audio_sha)
    existing = store.transcript(vid, key)
    txt_path = store.root / "transcripts" / f"{vid}.{key}.txt"
    json_path = store.root / "transcripts" / f"{vid}.{key}.json"
    if existing and existing["status"] == "complete" and txt_path.is_file() and json_path.is_file():
        notify(f"{vid}: 已完成 Whisper 转写，直接复用")
        return key, txt_path.read_text("utf-8"), txt_path
    store.start_transcript(vid, key, opts.asr_mode, selected, audio_sha, cfg)
    store.job(vid, "transcribe", "running")
    store.checkpoint()
    duration = float(asset["duration_seconds"] if asset and asset["sha256"] == audio_sha
                     else ffprobe_seconds(audio))
    n = math.ceil(duration / opts.chunk_seconds)
    try:
        completed = store.chunk_indices(vid, key)
        for i in range(n):
            if i in completed:
                notify(f"{vid}: 分块 {i+1}/{n} 已完成，跳过")
                continue
            start = i * opts.chunk_seconds
            length = min(opts.chunk_seconds, duration - start)
            clip = store.scratch / "chunks" / f"{vid}.{key}.{i:05d}.wav"
            try:
                slice_audio(audio, clip, start, length)
                segs = whisper.decode(clip, opts)
                absolute = [{**s, "start_ms": s["start_ms"] + int(start * 1000),
                             "end_ms": s["end_ms"] + int(start * 1000)} for s in segs]
                if any(s["end_ms"] == int(start * 1000) for s in absolute):
                    for s in absolute:
                        if s["end_ms"] <= s["start_ms"]:
                            s["end_ms"] = int((start + length) * 1000)
                store.save_chunk(vid, key, i, round(start * 1000), round((start + length) * 1000), absolute)
                notify(f"{vid}: Whisper 分块 {i+1}/{n} 已持久化")
            finally:
                clip.unlink(missing_ok=True)
        segments = store.segments(vid, key)
        transcript_text = "\n".join(f"[{fmt_ms(s['start_ms'])}] {s['text']}" for s in segments if s.get("text", "").strip())
        if not transcript_text.strip():
            raise RuntimeError("Whisper 没有产生有效文本，请检查语言和音频内容")
        report = {"video_id": vid, "model": selected, "engine": opts.asr_mode,
                  "audio_sha256": audio_sha, "run_key": key,
                  "source_url": f"https://www.youtube.com/watch?v={vid}", "segments": segments}
        publish_text(transcript_text + "\n", txt_path, store.scratch / "tmp")
        publish_text(json.dumps(report, ensure_ascii=False, indent=2), json_path, store.scratch / "tmp")
        store.finish_transcript(vid, key, txt_path, json_path)
        store.job(vid, "transcribe", "complete")
        store.checkpoint()
        notify(f"{vid}: 完整转写保存成功（{len(segments)} 段）")
        return key, transcript_text, txt_path
    except Exception as exc:
        safe = redact_error(exc, [opts.whisper_key, opts.llm_key])
        store.fail_transcript(vid, key, safe)
        store.job(vid, "transcribe", "failed", safe)
        store.checkpoint()
        raise
