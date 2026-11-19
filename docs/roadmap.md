
## Phase 1 implementation checkpoint

- Domain URL parser moved to `studio/domain/links.py`; legacy `studio.links` stays import-compatible.
- Domain result model moved to `studio/domain/models.py`; `studio.engine.VideoResult` remains an alias.
- Offline cached media scope restricted in `studio/application/offline_selection.py`: no playlist/mixed-channel cross-contamination.
- Added regression tests and Notebook-source synchronization check.
