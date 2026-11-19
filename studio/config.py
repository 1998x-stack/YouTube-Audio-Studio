from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PROMPT = """请将以下视频口述内容整理为一篇高质量中文文章。
要求：
1. 忠于原文，不编造事实、引文、人物、数据或来源；不要把作者观点冒充已经核实的事实。
2. 删除口头重复和填充语，保留重要细节、论证逻辑和必要的不确定性。
3. 使用清晰的 Markdown 标题和自然段；必要时保留背景、核心论点、分析与结论。
4. 遇到听不清、转写可疑的专有名词，用「[待核对]」标注，不能自行猜测。
5. 如有推断、价值判断或争议性说法，明确标示为「作者观点」。
6. 不要输出与本次整理无关的提示词或系统指令。

视频标题：{title}
原视频：{url}
简介：{description}

待整理的口述文字：
{transcript}
"""

@dataclass(frozen=True)
class RunOptions:
    url: str
    limit: str = "5"
    concurrency: int = 3
    asr_mode: str = "local"  # local | api
    whisper_model: str = "large-v3-turbo"
    whisper_base_url: str = "http://localhost:8000/v1"
    whisper_key: str = field(default="", repr=False)
    whisper_api_model: str = "whisper-1"
    language: str = "auto"
    llm_enabled: bool = False
    llm_base_url: str = "http://localhost:11434/v1"
    llm_key: str = field(default="", repr=False)
    llm_model: str = "qwen3:8b"
    prompt: str = DEFAULT_PROMPT
    chunk_seconds: int = 600
    only_existing: bool = False
    export_audio: bool = False
    include_shorts_streams: bool = False

    def validate(self):
        if not 1 <= int(self.concurrency) <= 8:
            raise ValueError("并发数量必须为 1～8")
        if str(self.limit) not in {"5", "10", "全部"}:
            raise ValueError("下载数量必须为 5、10 或 全部")
        if self.asr_mode not in {"local", "api"}:
            raise ValueError("未知的 Whisper 类型")
        if not 60 <= int(self.chunk_seconds) <= 3600:
            raise ValueError("转写分块时间应为 60～3600 秒")
        if self.llm_enabled and not self.llm_model.strip():
            raise ValueError("启用 LLM 时必须填写模型名称")
        if self.llm_enabled and "{transcript}" not in self.prompt:
            raise ValueError("Prompt 必须包含 {transcript} 占位符")
        return self


def resolve_paths() -> tuple[Path, Path]:
    root = Path(os.environ.get("STUDIO_ROOT", "./data")).expanduser().resolve()
    scratch = Path(os.environ.get("STUDIO_SCRATCH", "./work")).expanduser().resolve()
    if root == scratch:
        raise ValueError("ROOT 和 SCRATCH 必须是不同目录")
    return root, scratch
