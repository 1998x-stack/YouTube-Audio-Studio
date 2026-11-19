# Repository Engineering Rules

- **Scope**: authorized YouTube media; do not bypass platform restrictions or download third-party protected content without permission.
- **Layering**: domain never imports yt-dlp, Gradio, OpenAI, FFmpeg or SQLite; application enforces scope and orchestration; adapters perform network/model I/O; infrastructure persists.
- **Backwards compatibility**: keep existing `studio.*` import paths and `studio_catalog.db` layout working while moving code in small steps.
- **Persistence**: per ROOT only one process writes SQLite. Every completed transcription chunk is backed up before marking its task complete. Never delete the old `db/catalog.db`.
- **Secrets**: API keys only from password fields or environment; never store them in logs, DB, metadata files, or manifest JSON.
- **Review**: every PR should contain a short migration plan, regression tests, test commands, and explicit limitations.
- **Tests**: run `python -m pytest -q` and `python scripts/check_notebook_sync.py` before a PR. Network access and real GPU model tests are separate, opt-in end-to-end tests.
- **Synchronization**: the Colab Notebook embeds source code; regenerate and verify it whenever tracked project files change.
