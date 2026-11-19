# YouTube Audio Studio

[中文文档](README.zh.md) · [架构](docs/architecture.md) · [代码分类与路线图](docs/roadmap.md)

YouTube 视频/频道/播放列表 → MP3 → 本地 Whisper 或 Whisper API 转写 → 可选 OpenAI 兼容 LLM → 时间戳文本及 Markdown 文章。

## Quick start

```bash
# Python 3.10–3.13; install FFmpeg and a JavaScript runtime compatible with yt-dlp first
python -m pip install -e .
python -m studio.preflight
python app.py
```

Open `http://127.0.0.1:7860`. For Google Colab, import `YouTube_Audio_Studio_Colab.ipynb`.

## Source categories

| Category | Implementation |
|---|---|
| Domain | `studio/domain/links.py`, `studio/domain/models.py` |
| Application | `studio/application/offline_selection.py`, `studio/engine.py` |
| YouTube adapter | `studio/youtube.py` |
| ASR adapter | `studio/asr.py` |
| LLM adapter | `studio/articles.py` |
| Persistence | `studio/store.py`, `studio/utils.py` |
| UI / CLI | `studio/ui.py`, `studio/cli.py` |
| Tests | `tests/`, `scripts/check_notebook_sync.py` |

This repository is evolving through small, tested PRs. Use only media you are authorized to download, transcribe and reuse. Do not commit datasets, credentials, media, model weights or database files.
