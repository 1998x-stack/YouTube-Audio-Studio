"""Noninteractive mode, useful when the UI is not available."""
from __future__ import annotations
import argparse
import os
from .config import RunOptions, DEFAULT_PROMPT, resolve_paths
from .engine import Engine


def main():
    parser = argparse.ArgumentParser(description="YouTube link → audio → transcript → optional article")
    parser.add_argument("url", help="YouTube video, channel or playlist URL")
    parser.add_argument("--limit", choices=["5", "10", "全部"], default="5")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--asr", choices=["local", "api"], default="local")
    parser.add_argument("--whisper-model", default="large-v3-turbo")
    parser.add_argument("--whisper-api-model", default="whisper-1")
    parser.add_argument("--whisper-base-url", default=os.environ.get("WHISPER_BASE_URL", "http://localhost:8000/v1"))
    parser.add_argument("--lang", default="auto", choices=["auto", "zh", "en"])
    parser.add_argument("--llm", action="store_true")
    parser.add_argument("--llm-base-url", default=os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1"))
    parser.add_argument("--llm-model", default=os.environ.get("LLM_MODEL", "qwen3:8b"))
    parser.add_argument("--prompt-file", help="UTF-8 custom prompt template")
    parser.add_argument("--local-only", action="store_true")
    parser.add_argument("--include-audio", action="store_true")
    parser.add_argument("--include-shorts-streams", action="store_true")
    args = parser.parse_args()
    opts = RunOptions(url=args.url, limit=args.limit, concurrency=args.concurrency,
                      asr_mode=args.asr, whisper_model=args.whisper_model,
                      whisper_base_url=args.whisper_base_url,
                      whisper_api_model=args.whisper_api_model,
                      whisper_key=os.environ.get("WHISPER_API_KEY", ""),
                      language=args.lang, llm_enabled=args.llm,
                      llm_base_url=args.llm_base_url, llm_model=args.llm_model,
                      llm_key=os.environ.get("LLM_API_KEY", ""),
                      prompt=open(args.prompt_file, encoding="utf-8").read() if args.prompt_file else DEFAULT_PROMPT,
                      only_existing=args.local_only, export_audio=args.include_audio,
                      include_shorts_streams=args.include_shorts_streams)
    root, scratch = resolve_paths()
    engine = Engine(root, scratch)
    try:
        results = engine.run(opts, print)
        archive = engine.make_export(results, args.include_audio)
        for r in results:
            print(r.status, r.video_id, r.error)
        print("EXPORT:", archive)
        return 0 if all(r.status == "complete" for r in results) else 1
    finally:
        engine.close()

if __name__ == "__main__":
    raise SystemExit(main())
