# YouTube Audio Studio

[中文文档](README.zh.md) · [架构](docs/architecture.md) · [路线图](docs/roadmap.md)

一个通用的 YouTube 视频/频道/播放列表音频工作台：yt-dlp 下载、faster-whisper 本地 GPU / Whisper API 转写、可选 OpenAI 兼容 LLM + 自定义 Prompt、Gradio 控制台、SQLite 断点续跑及 ZIP 导出。

## 快速启动

```bash
# Python 3.10–3.13；须先安装 FFmpeg 和适配 yt-dlp 的 JavaScript 运行时
python -m pip install -e .
python -m studio.preflight
python app.py
```

访问 http://127.0.0.1:7860。Colab 使用仓库内 `YouTube_Audio_Studio_Colab.ipynb`。

## 现阶段的模块分类

- `studio/config.py`, `studio/links.py`：配置和输入契约
- `studio/youtube.py`：视频发现与下载 adapter
- `studio/asr.py`：Whisper 转写 adapter
- `studio/articles.py`：可选 LLM 转换 adapter
- `studio/store.py`：SQLite 与 Drive 持久化
- `studio/engine.py`：任务编排与恢复
- `studio/ui.py`, `studio/cli.py`：Gradio / 命令行入口
- `tests/`：自动化验证

后续采取**小步 PR、先测试后重构**，详见路线图。请确认有权处理输入的视频/音频内容；不要提交媒体文件、API Key、数据库或模型缓存。
