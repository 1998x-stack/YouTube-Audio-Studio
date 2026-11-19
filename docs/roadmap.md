# 代码分类与渐进式重构路线图

## 基线（Phase 0）

本 PR 将此前生成的可运行项目完整移入 GitHub；主程序保持原有 `studio.*` 模块，避免首个提交同时重写全部依赖。后续遵循每阶段独立 PR、回归测试与可回滚的原则。

## Category 规划

| Category | 当前源文件 | 目标包 | 边界 |
|---|---|---|---|
| Domain | config.py / links.py | studio/domain | 数据契约、YouTube URL、状态机；无外部 API |
| Application | engine.py | studio/application | 流水线、并发、重试、恢复；依赖 ports |
| Adapters / Source | youtube.py | studio/adapters/youtube | yt-dlp 与 FFmpeg |
| Adapters / ASR | asr.py | studio/adapters/asr | local Whisper / OpenAI-compatible ASR |
| Adapters / LLM | articles.py | studio/adapters/llm | 文章生成、Prompt、模型版本 |
| Infrastructure | store.py / utils.py | studio/infrastructure | SQLite、Drive 快照、文件哈希、原子发布 |
| Interfaces | ui.py / cli.py | studio/interfaces | Gradio / CLI，不包含业务逻辑 |
| Operations | preflight.py / Dockerfile | deploy/ | GPU/FFmpeg/Deno 检查与部署 |
| QA | tests/ / .github/workflows | tests/ | mock / integration / smoke / CI |

### P0：保底可用性

- [x] 导入完整功能基线与 Colab Notebook
- [x] GitHub Actions pytest、ruff 基础验证
- [ ] 在 Colab GPU 实测 yt-dlp + PyAV + faster-whisper
- [ ] 数据库存储版本和旧数据迁移验收
- [ ] 损坏音频 / 失败任务 / 重试过程详尽日志
- [ ] 同一 ROOT 单写者防护与告警

### P1：分层架构

- [ ] 提取 domain models、状态机和 ports
- [ ] 引入 repository/download/ASR/LLM 接口，逐个替换硬耦合
- [ ] 针对单视频、频道、播放列表的 contract tests
- [ ] 并发上限、速率限制、取消任务与部分失败恢复
- [ ] 统一可观测性：run_id、video_id、stage、duration、error_type

### P2：内容质量

- [ ] 中文字幕 fallback / Whisper 判定与重转写
- [ ] LLM 多阶段 Prompt：分段、合并、核验、引用时间戳
- [ ] 文章格式模板及版本化，增量重生成
- [ ] FTS5 全文搜索、系列分类与专题管理

### P3：生产化

- [ ] Gradio 安全性：默认本地绑定，公网需鉴权
- [ ] PostgreSQL + 队列支持多实例并发
- [ ] 对象存储、API 费用预算与配额控制
- [ ] Colab / Docker / Linux 手册与端到端验收报告

## 验收约束

任何阶段不得破坏已有 `studio_catalog.db`、ROOT 目录布局、`yt-dlp` 缓存、CLI 与 Notebook。先完成迁移适配与测试，再移动文件。只允许一个进程写同一 ROOT。
