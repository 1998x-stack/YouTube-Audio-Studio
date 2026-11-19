# YouTube Audio Studio — 视频 / 频道批量转写控制台

用户输入任意一个受支持的 YouTube 视频、频道主页或播放列表链接，即可获得可持久化的 MP3、逐段时间戳 TXT/JSON，并可按自定义 Prompt 调用 **OpenAI 兼容 LLM** 生成 Markdown 文章。默认无 LLM 时输出忠实的时间戳口述稿。使用前请确认你拥有处理相应素材的权利，并遵守 YouTube 条款及著作权约定。

## 界面功能

- **链接**：单个视频 `watch?v=...` / `youtu.be` / Shorts / Live 回放、频道 `@handle` 首页与 `/videos`、播放列表 `?list=...`。
- **数量**：5、10、全部；单个视频忽略数量。默认扫描频道 `/videos`，可以额外勾选 Shorts 与直播回放（按视频 ID 去重）。
- **并发**：默认 3，可调 1～8；不同视频任务并行；本地 GPU Whisper 推理加锁（减少显存峰值）；Whisper API 模式可同时发起多个请求。
- **转写**：本地 `faster-whisper`（GPU 优先、CPU 自动退至 `small`），或 OpenAI 兼容 Whisper 服务（默认 `http://localhost:8000/v1`，可填 API Key）。
- **LLM**：开关默认关闭；OpenAI 兼容接口默认 `http://localhost:11434/v1`（适合 Ollama）、模型名称与 API Key 可在 UI 输入；Prompt 可直接粘贴，支持 `{title}`、`{url}`、`{description}`、`{transcript}`。
- **恢复**：重启恢复 Studio SQLite 数据库；完整 MP3 不再下载；转写按 10 分钟一块持久化；中断的 LLM 分段稿也会复用。失败任务再次点击运行时重试。
- **结果**：`ROOT/media/*.mp3`、`ROOT/transcripts/*.txt|json`、`ROOT/articles/*.md`、每次运行的 ZIP/manifest（默认文本 + metadata，可选包含音频）。

## 本地运行

需要 Python 3.10～3.13、FFmpeg、Deno >= 2.3（YouTube EJS challenge solver）。建议 Python 3.11/3.12。

```bash
# Ubuntu 示例
sudo apt-get update && sudo apt-get install -y ffmpeg curl unzip
curl -fsSL https://deno.land/install.sh | sh
export PATH="$HOME/.deno/bin:$PATH"

python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e .
python -m studio.preflight
python app.py
```

打开 http://127.0.0.1:7860 ，输入链接并开始。Windows 可安装 FFmpeg、Deno 并在 PowerShell 启动；Mac 可使用 Homebrew 安装 `ffmpeg` 与 `deno`。

> 安装必须约束 `faster-whisper==1.2.1`、`av==18.0.0`；如果任意升级至 `av>=19` 但 faster-whisper 未同步修复，将再次出现 `TypeError: open() got an unexpected keyword argument 'metadata_errors'`。

## 在 Google Colab 上使用

打开随附的 **YouTube_Audio_Studio_Colab.ipynb**，切换 GPU Runtime（若可用），从头运行。Notebook 自带整个 Python 项目源码，不依赖 Drive 中已有代码。启动时使用：

```python
STUDIO_ROOT = "/content/drive/MyDrive/zhuweiyi_corpus"
STUDIO_SCRATCH = "/content/zhuweiyi_scratch"
```

你现有 `zhuweiyi_corpus/media/*.mp3` 与 `metadata/*.json` 会被自动发现并复用。旧版 `db/catalog.db` **原封不动保留**；新版写在 `db/studio_catalog.db`。Colab 重启、重新挂载后会从 Drive 恢复快照，不必复制整个 ROOT。

**Colab 的 `localhost` 是 Colab 虚拟机，不是你自己电脑**。本地 Whisper 在 Colab GPU 直接运行不需要 API Key；如果希望访问电脑上的 Ollama/Whisper API，需要你自己配置安全的远程 endpoint。不要将暴露的 Gradio 公开链接或 API Key 发给他人。

## CLI / 自动化使用

```bash
# 处理单视频（必须有权处理相应内容）
python -m studio.cli "https://www.youtube.com/watch?v=gFcjsbA_xqc"

# 频道中最近 10 条视频（按 yt-dlp 返回的目录顺序）
python -m studio.cli "https://www.youtube.com/@zhuweiyi/videos" --limit 10 --concurrency 3

# 断网 / 不重新访问 YouTube：处理已有 Drive 音频
export STUDIO_ROOT="/content/drive/MyDrive/zhuweiyi_corpus"
export STUDIO_SCRATCH="/content/zhuweiyi_scratch"
python -m studio.cli "https://www.youtube.com/watch?v=gFcjsbA_xqc" --local-only

# 兼容 OpenAI 的 LLM（API Key 应放在环境变量里，不能写入仓库）
export LLM_BASE_URL="https://api.example.com/v1"
export LLM_MODEL="your-model"
export LLM_API_KEY="your-secret"
python -m studio.cli "https://www.youtube.com/@zhuweiyi" --limit 5 --llm
```

## Docker

```bash
docker compose up --build
```

默认为只在 `127.0.0.1:7860` 暴露端口。Docker 部署的 localhost 指的是容器；调用宿主 Ollama 时需按平台配置宿主地址。

## 文件目录

```text
youtube-audio-studio/
├── app.py                       # Gradio 控制台
├── studio/
│   ├── ui.py                    # 表单、任务结果与导出
│   ├── links.py                 # URL 安全解析
│   ├── youtube.py               # yt-dlp 发现 / 下载 / metadata
│   ├── asr.py                   # Whisper 本地 / API、分块恢复
│   ├── articles.py              # 可选 LLM 生成 & Prompt
│   ├── store.py                 # SQLite + Drive 持久化
│   ├── engine.py                # 有界线程池与事件流
│   ├── config.py                # 参数与默认 Prompt
│   ├── preflight.py             # 环境诊断
│   └── cli.py                   # 非 UI 命令行
├── docs/schema.sql             # 数据库表结构
├── docs/architecture.md        # 架构与可靠性边界
├── tests/test_studio.py         # 不依赖 YouTube 网络的恢复测试
├── Dockerfile / docker-compose.yml
└── YouTube_Audio_Studio_Colab.ipynb
```

## 数据库与恢复

初次启动时：优先恢复 `ROOT/db/studio_catalog.db`，如果损坏则回退 `studio_catalog.prev.db`；每个 Whisper 分块提交至 SQLite 并快照回 ROOT。已下载音频的 SHA-256 绑定转写配置生成 `run_key`，防止不同模型、不同音频混用。文章与所用 Prompt 哈希一同存储，修改 Prompt 会生成新的整理版本。

> 不支持多个 Colab 实例**同时**写入同一个 ROOT。该场景需要 PostgreSQL + 分布式任务队列或独立分片合并；当前设计针对同一实例内 1～8 个线程的并发，以及不同 Colab 会话**先后**重启。

## 故障排查

| 症状 | 可能原因 / 处理 |
|---|---|
| `open() ... metadata_errors` | 检查 `faster-whisper==1.2.1` + `av==18.0.0`，重新安装并重启运行时 |
| `yt-dlp` 缺少 JS challenge support | `python -m studio.preflight` 查看 Deno 和 `yt-dlp-ejs`；升级 `yt-dlp[default]` |
| Whisper 无 GPU | Colab Runtime → GPU；若无 GPU，自动使用 CPU small |
| 音频下载失败 / 403 / 429 | 检查视频公开权限、网络与 yt-dlp 版本；不尝试绕过付费或访问控制 |
| LLM 连接错误 | 检查 Base URL 是否是实际可访问的 API 地址；Colab localhost 与自己电脑不同 |
| Colab 中断 | 重新运行 Notebook；同一 ROOT 重建本地 SQLite；已有 MP3 与已完成分块会跳过 |
| `studio_catalog.db` 损坏 | 程序自动尝试 `studio_catalog.prev.db`；勿删除 Drive 下其它文件 |
| 同时打开两个 Colab Notebook | 不要让它们同时写同一个 ROOT；停止其中一个实例再恢复 |

## 测试

```bash
pip install pytest
pytest -q
```

测试全程使用模拟媒体、断点重启及 mock Whisper，不会向 YouTube 发起请求；真实 GPU 推理、网络下载和第三方 API 仍需在目标运行环境做一次端到端验收。
