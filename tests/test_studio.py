import json
import shutil
import threading
import time
import wave
from pathlib import Path

import pytest

from studio.articles import make_prompt, split_text
from studio.asr import Whisper, transcribe
from studio.config import RunOptions
from studio.engine import Engine, VideoResult
from studio.links import parse_link
from studio.store import Store
from studio.youtube import ensure_audio

VID = "gFcjsbA_xqc"
VID2 = "R1L79bh-3uw"


def make_audio(path: Path, seconds: int = 5):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Valid WAV bytes in a file with .mp3 extension; FFmpeg detects input by header.
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        f.writeframes(b"\x00\x00" * 16000 * seconds)


def test_parse_links():
    assert parse_link(f"https://youtu.be/{VID}?si=random").video_id == VID
    assert parse_link(f"https://www.youtube.com/watch?v={VID}&list=stuff").kind == "video"
    assert parse_link("https://www.youtube.com/@zhuweiyi/videos?view=0&sort=dd&shelf_id=3").url == "https://www.youtube.com/@zhuweiyi/videos"
    assert parse_link("https://www.youtube.com/@zhuweiyi").kind == "channel"
    assert parse_link("https://www.youtube.com/playlist?list=PLabcdefghijklmn").kind == "playlist"
    assert parse_link(f"https://www.youtube.com/shorts/{VID}").kind == "video"
    with pytest.raises(ValueError):
        parse_link("https://youtube.com.attacker.example/watch?v=" + VID)
    with pytest.raises(ValueError):
        parse_link("file:///etc/passwd")
    with pytest.raises(ValueError):
        parse_link("https://www.youtube.com/unknown")


def test_keys_hidden_and_prompt_preserves_json():
    opts = RunOptions(url="https://youtu.be/" + VID, whisper_key="private-whisper", llm_key="secret-llm")
    assert "private-whisper" not in repr(opts)
    assert "secret-llm" not in repr(opts)
    prompt = make_prompt('{"custom":true}\n{transcript}\n{title}', {"title": "题目"}, VID, "正文")
    assert '{"custom":true}' in prompt and "正文" in prompt and "题目" in prompt
    assert split_text("a"*10000, max_length=1000) == ["a"*1000]*10


def test_old_catalog_untouched_and_recovery(tmp_path):
    root = tmp_path / "drive"; scratch = tmp_path / "vm1"
    (root / "db").mkdir(parents=True)
    (root / "db/catalog.db").write_bytes(b"USER_LEGACY_CATALOG_DO_NOT_CHANGE")
    media = root / "media" / f"{VID}.mp3"
    make_audio(media)
    (root / "metadata").mkdir()
    (root / "metadata" / f"{VID}.json").write_text(json.dumps({"id": VID, "title": "你好"}), encoding="utf-8")
    store = Store(root, scratch)
    assert store.video(VID)["title"] == "你好"
    assert store.get_audio(VID)["byte_size"] > 1024
    assert store.remote.name == "studio_catalog.db"
    store.close()
    assert (root / "db/catalog.db").read_bytes() == b"USER_LEGACY_CATALOG_DO_NOT_CHANGE"
    shutil.rmtree(scratch)
    store2 = Store(root, tmp_path / "vm2")
    assert store2.video(VID)["title"] == "你好"
    store2.close()


def test_existing_audio_never_fetches_youtube(tmp_path):
    root = tmp_path / "drive"
    make_audio(root / "media" / f"{VID}.mp3")
    store = Store(root, tmp_path / "work")
    path, info, reused = ensure_audio(store, VID)
    assert reused is True and info["id"] == VID and path.exists()
    assert (root / "metadata" / f"{VID}.json").exists()
    store.close()


def test_whisper_chunk_resume_across_new_scratch(tmp_path, monkeypatch):
    root = tmp_path / "drive"; source = root / "media" / f"{VID}.mp3"
    make_audio(source, 5)
    first = Store(root, tmp_path / "vm1")
    calls = []
    class FakeWhisper:
        device = "mock"
        def init_local(self, name): return "small"
        def decode(self, clip, opts):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("SIMULATED VM SHUTDOWN")
            return [{"start_ms": 0, "end_ms": 500, "text": "转写内容"}]
    cfg = RunOptions(url="https://youtu.be/" + VID, chunk_seconds=2)
    with pytest.raises(RuntimeError, match="SIMULATED"):
        transcribe(first, VID, source, cfg, FakeWhisper())
    with first.lock:
        assert first.conn.execute("SELECT count(*) FROM chunks").fetchone()[0] == 1
    first.close()
    shutil.rmtree(tmp_path / "vm1")
    second = Store(root, tmp_path / "vm2")
    next_calls = []
    class GoodWhisper(FakeWhisper):
        def decode(self, clip, opts):
            next_calls.append(1)
            return [{"start_ms": 0, "end_ms": 500, "text": "续传成功"}]
    key, text, path = transcribe(second, VID, source, cfg, GoodWhisper())
    assert len(next_calls) == 2  # 3 total chunks, first one restored
    assert "转写内容" in text and text.count("续传成功") == 2
    assert path.exists() and path.with_suffix(".json").exists()
    # Missing exports should be rebuilt using saved segment chunks.
    path.unlink()
    key2, text2, path2 = transcribe(second, VID, source, cfg, GoodWhisper())
    assert key == key2 and path2.exists() and len(next_calls) == 2
    second.close()


def test_articles_reused_and_regenerated(tmp_path):
    from studio.articles import create_article
    root = tmp_path / "drive"
    make_audio(root / "media" / f"{VID}.mp3")
    store = Store(root, tmp_path / "vm")
    key = "transcript-test"
    store.start_transcript(VID, key, "mock", "small", "sha", {})
    path = create_article(store, VID, key, "[00:00] 字幕", {"title":"测试"}, RunOptions(url="https://youtu.be/" + VID))
    assert path.exists()
    path.unlink()
    result = create_article(store, VID, key, "different", {"title":"测试"}, RunOptions(url="https://youtu.be/" + VID))
    assert result.exists() and "字幕" in result.read_text()
    store.close()


def test_export_zip_contains_text_and_metadata_not_audio_by_default(tmp_path):
    root = tmp_path / "drive"; scratch = tmp_path / "vm"
    make_audio(root / "media" / f"{VID}.mp3")
    engine = Engine(root, scratch)
    txt = root / "transcripts" / f"{VID}.txt"; txt.write_text("text")
    article = root / "articles" / f"{VID}.md"; article.write_text("article")
    item = VideoResult(VID, "Title", "complete", str(root/"media"/f"{VID}.mp3"), str(txt), str(article))
    out = engine.make_export([item], False)
    import zipfile
    with zipfile.ZipFile(out) as z:
        assert "transcripts/"+VID+".txt" in z.namelist()
        assert "media/"+VID+".mp3" not in z.namelist()
        assert "manifest.json" in z.namelist()
    engine.close()


def test_concurrency_is_limited_to_three(tmp_path, monkeypatch):
    from studio import engine as engine_module
    obj = Engine(tmp_path/"drive", tmp_path/"vm")
    ids = [f"ABCDEFGHI{i:02d}" for i in range(9)]
    ids = [v[:11] for v in ids]
    for v in ids: obj.store.put_video(v)
    monkeypatch.setattr(engine_module, "discover", lambda *args, **kwargs: ids)
    lock = threading.Lock()
    count = [0, 0]
    def fake_one(vid, opts, notify):
        with lock:
            count[0] += 1
            count[1] = max(count[1], count[0])
        time.sleep(0.03)
        with lock: count[0] -= 1
        return VideoResult(vid, status="complete")
    monkeypatch.setattr(obj, "one", fake_one)
    seen = []
    result = obj.run(RunOptions(url="https://www.youtube.com/@zhuweiyi", concurrency=3), on_result=seen.append)
    assert len(result) == len(ids) and len(seen) == len(ids)
    assert count[1] == 3
    obj.close()


def test_complete_offline_pipeline_and_second_run_zero_new_asr(tmp_path, monkeypatch):
    root = tmp_path/"drive"
    make_audio(root/"media"/f"{VID}.mp3", 3)
    calls = []
    def fake_init(self, name):
        self.selected_model = "small"; self.device = "cpu"; return "small"
    def fake_decode(self, file, opts):
        calls.append(1)
        return [{"start_ms": 0, "end_ms": 500, "text": "这一句话将被保存"}]
    monkeypatch.setattr(Whisper, "init_local", fake_init)
    monkeypatch.setattr(Whisper, "decode", fake_decode)
    engine = Engine(root, tmp_path/"vm")
    opts = RunOptions(url=f"https://youtu.be/{VID}", only_existing=True)
    one = engine.one(VID, opts, lambda message: None)
    assert one.status == "complete" and all(Path(p).exists() for p in [one.audio, one.transcript, one.article])
    assert Path(one.article).read_text().find("这一句话将被保存") >= 0
    two = engine.one(VID, opts, lambda message: None)
    assert two.status == "complete" and len(calls) == 1
    engine.close()
    shutil.rmtree(tmp_path / "vm")
    new_engine = Engine(root, tmp_path / "vm2")
    three = new_engine.one(VID, opts, lambda message: None)
    assert three.status == "complete" and len(calls) == 1
    new_engine.close()


def test_llm_partial_draft_resume(tmp_path, monkeypatch):
    from studio.articles import create_article
    from studio.utils import short_hash
    from types import SimpleNamespace, ModuleType
    import sys
    calls = []
    fail = {"enabled": True}

    def create_response(**kwargs):
        calls.append(1)
        if fail["enabled"] and len(calls) == 2:
            raise RuntimeError("SIMULATED LLM OUTAGE")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="整理稿"))])

    class FakeOpenAI:
        def __init__(self, *args, **kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create_response))

    fake_module = ModuleType("openai")
    fake_module.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_module)
    root = tmp_path / "drive"
    store = Store(root, tmp_path / "vm")
    store.put_video(VID)
    store.start_transcript(VID, "r1", "mock", "small", "sha", {})
    opts = RunOptions(url=f"https://youtu.be/{VID}", llm_enabled=True,
                      llm_base_url="http://localhost:11434/v1")
    long_text = ("[00:01] 这是一个很长的转录文本。\n" * 1000)
    with pytest.raises(RuntimeError, match="SIMULATED LLM"):
        create_article(store, VID, "r1", long_text, {"title": "标题"}, opts)
    assert len(list((root / "articles" / "drafts").glob("*.md"))) == 1
    fail["enabled"] = False
    result = create_article(store, VID, "r1", long_text, {"title": "标题"}, opts)
    assert result.exists() and "整理稿" in result.read_text()
    assert store.article(VID, "r1", short_hash(opts.prompt + "|" + opts.llm_base_url), opts.llm_model)
    # First draft was reused; only missing LLM parts issued requests.
    assert len(calls) > 2
    store.close()
