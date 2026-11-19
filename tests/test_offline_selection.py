"""Regression checks: offline playlist or unrelated channel must not leak audio."""
import json

import pytest

from studio.application.offline_selection import select_cached_videos
from studio.domain.links import parse_link
from studio.store import Store


ALPHA = "gFcjsbA_xqc"
BETA = "R1L79bh-3uw"


def test_offline_playlist_fails_closed(tmp_path):
    store = Store(tmp_path / "drive", tmp_path / "scratch")
    try:
        with pytest.raises(ValueError, match="播放列表成员"):
            select_cached_videos(store, parse_link("https://www.youtube.com/playlist?list=PLabcdefghijk123"), "全部")
    finally:
        store.close()


def test_offline_channel_matches_exact_handle_or_channel_id(tmp_path):
    store = Store(tmp_path / "drive", tmp_path / "scratch")
    try:
        examples = [
            (ALPHA, "@zhuweiyi", "UC-ALPHA1234", "20261117"),
            (BETA, "@someoneelse", "UC-BETA12345", "20261119"),
        ]
        for vid, handle, channel, published in examples:
            store.put_video(vid, metadata={
                "id": vid, "title": vid, "uploader_id": handle,
                "channel_id": channel, "upload_date": published,
            })
            media = store.root / "media" / f"{vid}.mp3"
            media.write_bytes(b"audio" * 250)
        assert select_cached_videos(store, parse_link("https://www.youtube.com/@zhuweiyi/videos"), "全部") == [ALPHA]
        assert select_cached_videos(store, parse_link("https://www.youtube.com/channel/UC-BETA12345"), "全部") == [BETA]
        assert select_cached_videos(store, parse_link("https://www.youtube.com/@unknown"), "全部") == []
        with pytest.raises(ValueError, match="无法离线核验"):
            select_cached_videos(store, parse_link("https://www.youtube.com/user/legacyname"), "全部")
    finally:
        store.close()


def test_domain_result_is_backwards_compatible():
    from studio.domain.models import VideoResult as Canonical
    from studio.engine import VideoResult as Legacy
    assert Canonical is Legacy


def test_colab_public_console_requires_login():
    # Static guard: publishing this console without auth exposes user-supplied API keys.
    from pathlib import Path
    import json
    notebook = json.loads((Path(__file__).resolve().parents[1] / "YouTube_Audio_Studio_Colab.ipynb").read_text("utf-8"))
    public_cell = "".join(notebook["cells"][-1]["source"])
    assert "share=True" in public_cell
    assert "auth=(AUTH_USER, AUTH_PASSWORD)" in public_cell
    assert "secrets.token_urlsafe(" in public_cell
