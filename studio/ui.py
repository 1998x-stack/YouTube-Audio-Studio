from __future__ import annotations
import os
import shutil
from pathlib import Path

from .config import DEFAULT_PROMPT, RunOptions, resolve_paths
from .engine import stream_run


def build_app():
    import gradio as gr
    root, scratch = resolve_paths()
    gr.set_static_paths(paths=[])  # do not publish user archives or model caches as static assets
    with gr.Blocks(title="YouTube Audio Studio") as app:
        gr.Markdown("# YouTube Audio Studio\n视频或频道 → MP3 → Whisper → 文本 → 可选 LLM 文章\n\n"
                    "**仅处理你有权下载、转写与使用的内容。** 单个 ROOT 仅允许一个应用进程写入。")
        with gr.Row():
            url = gr.Textbox(label="YouTube 视频 / 频道 / 播放列表链接", lines=2,
                             placeholder="https://www.youtube.com/@zhuweiyi/videos")
        with gr.Row():
            limit = gr.Radio(["5", "10", "全部"], value="5", label="频道/列表处理数量（单视频自动忽略）")
            concurrency = gr.Slider(minimum=1, maximum=8, step=1, value=3,
                                    label="同时处理的视频数（默认 3）")
        with gr.Row():
            mode = gr.Radio(choices=[("本地 faster-whisper（GPU 优先）", "local"),
                                     ("Whisper OpenAI 兼容 API", "api")], value="local", label="转写方式")
            language = gr.Dropdown([("自动检测", "auto"), ("中文", "zh"), ("English", "en")],
                                   value="auto", label="语言")
            local_model = gr.Textbox(value="large-v3-turbo", label="本地 Whisper 模型")
        with gr.Accordion("Whisper API 配置（本地模式可不填）", open=False):
            whisper_base = gr.Textbox(label="Whisper API Base URL", value="http://localhost:8000/v1")
            whisper_model = gr.Textbox(label="Whisper API 模型名", value="whisper-1")
            whisper_key = gr.Textbox(label="Whisper API Key", type="password", value="")
        with gr.Accordion("LLM 内容整理（可选）", open=False):
            enabled = gr.Checkbox(label="启用 LLM 生成文章", value=False)
            with gr.Row():
                llm_base = gr.Textbox(label="LLM OpenAI 兼容 Base URL", value="http://localhost:11434/v1")
                llm_model = gr.Textbox(label="模型名", value="qwen3:8b")
                llm_key = gr.Textbox(label="LLM API Key（localhost 可不填）", type="password")
            prompt = gr.Textbox(label="Prompt 模板（可以粘贴替换）", value=DEFAULT_PROMPT, lines=12)
            gr.Markdown("可用占位符：`{title}`、`{url}`、`{description}`、`{transcript}`。")
        with gr.Accordion("恢复与导出", open=False):
            offline = gr.Checkbox(label="仅处理 ROOT 已有的 MP3，不访问 YouTube", value=False)
            include_extra = gr.Checkbox(label="频道扫描时额外包含 Shorts 与直播回放（自动去重）", value=False)
            with_audio = gr.Checkbox(label="ZIP 额外包含 MP3（批量时文件可能很大）", value=False)
            chunk = gr.Slider(120, 1800, value=600, step=60, label="Whisper 分块长度（秒）")
            gr.Markdown(f"**ROOT:** `{root}`  \n**SCRATCH:** `{scratch}`  \n"
                        "Colab 重新启动时使用相同 ROOT，将自动恢复 `studio_catalog.db` 和已经完成的音频块。")
        start = gr.Button("开始下载 / 转写 / 生成文章", variant="primary")
        status = gr.Markdown("准备就绪。")
        logs = gr.Textbox(label="执行日志", lines=13, interactive=False)
        table = gr.Dataframe(headers=["video_id", "标题", "状态", "MP3", "TXT", "文章", "失败原因"],
                             datatype=["str"]*7, label="逐条处理结果", interactive=False, wrap=True)
        export = gr.File(label="下载本次结果 ZIP（默认文本 + 元数据）")

        def run(url, limit, concurrency, mode, language, local_model, whisper_base, whisper_model,
                whisper_key, enabled, llm_base, llm_model, llm_key, prompt, offline, with_audio, chunk, include_extra):
            opts = RunOptions(url=url, limit=limit, concurrency=int(concurrency), asr_mode=mode,
                              language=language, whisper_model=local_model,
                              whisper_base_url=whisper_base, whisper_api_model=whisper_model,
                              whisper_key=whisper_key, llm_enabled=enabled,
                              llm_base_url=llm_base, llm_model=llm_model,
                              llm_key=llm_key, prompt=prompt,
                              only_existing=offline, export_audio=with_audio, chunk_seconds=int(chunk),
                              include_shorts_streams=include_extra)
            log_lines, rows = [], []
            yield "正在处理（请保持页面打开）…", "", rows, None
            for kind, data in stream_run(root, scratch, opts):
                if kind == "log":
                    log_lines.append(data)
                    log_lines = log_lines[-250:]
                    yield "正在处理…", "\n".join(log_lines), rows, None
                elif kind == "result":
                    rows.append(data.table_row())
                    yield f"正在处理… 已完成 {len(rows)} 条", "\n".join(log_lines), rows, None
                else:
                    if "error" in data:
                        yield "**运行失败：** " + data["error"], "\n".join(log_lines), rows, None
                    else:
                        rows = [r.table_row() for r in data["results"]]
                        success = sum(r.status == "complete" for r in data["results"])
                        yield f"**完成：** {success}/{len(rows)} 条；失败项下次可重试", "\n".join(log_lines), rows, str(data["export"])

        inputs = [url, limit, concurrency, mode, language, local_model, whisper_base, whisper_model,
                  whisper_key, enabled, llm_base, llm_model, llm_key, prompt, offline, with_audio, chunk, include_extra]
        start.click(run, inputs=inputs, outputs=[status, logs, table, export],
                    concurrency_limit=1, show_progress="full")
    return app


def main():
    app = build_app()
    app.queue(max_size=10).launch(server_name=os.environ.get("STUDIO_HOST", "127.0.0.1"),
                                  server_port=int(os.environ.get("STUDIO_PORT", "7860")),
                                  share=os.environ.get("STUDIO_SHARE", "false").lower() == "true")


if __name__ == "__main__":
    main()
