import json
from types import SimpleNamespace

from model_download import Progress, download


def test_unknown_total_is_not_a_fake_percentage(tmp_path):
    path = tmp_path / "progress.json"
    Progress(path, "medium")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["total_bytes"] is None
    assert data["percent"] is None
    assert data["phase"] == "获取模型文件信息"


def test_progress_includes_cached_and_resumed_bytes(tmp_path):
    path = tmp_path / "progress.json"
    tracker = Progress(path, "small")
    tracker.sizes = {"config.json": 10, "model.safetensors": 100}
    config = tmp_path / "config.json"
    config.write_bytes(b"0" * 10)
    tracker.start_file("config.json")
    tracker.complete_file(config)
    tracker.start_file("model.safetensors")
    tracker.update(40, 100)
    tracker.write(force=True)
    state = json.loads(path.read_text(encoding="utf-8"))
    assert state["downloaded_bytes"] == 50
    assert state["total_bytes"] == 110
    assert 45 < state["percent"] < 46
    model = tmp_path / "model.safetensors"
    model.write_bytes(b"0" * 100)
    tracker.complete_file(model)
    assert json.loads(path.read_text(encoding="utf-8"))["percent"] < 100
    tracker.status = "complete"
    tracker.write(force=True)
    assert json.loads(path.read_text(encoding="utf-8"))["percent"] == 100


def test_official_downloader_reports_bytes_and_completion(monkeypatch, tmp_path):
    import huggingface_hub as hub
    info = SimpleNamespace(sha="test-sha", siblings=[SimpleNamespace(rfilename=f, size=n) for f, n in
                                                    (("config.json", 10), ("model.safetensors", 100))])
    monkeypatch.setattr(hub.HfApi, "model_info", lambda *args, **kwargs: info)
    def fetch(repo, filename, revision, tqdm_class):
        assert repo == "MuScriptor/muscriptor-medium"
        assert revision == "test-sha"
        size = 10 if filename == "config.json" else 100
        with tqdm_class(total=size, initial=0) as bar:
            bar.update(size // 2)
            bar.update(size - size // 2)
        path = tmp_path / filename
        path.write_bytes(b"0" * size)
        return str(path)
    monkeypatch.setattr(hub, "hf_hub_download", fetch)
    progress = tmp_path / "download.json"
    assert download("medium", progress) == 0
    state = json.loads(progress.read_text(encoding="utf-8"))
    assert state["status"] == "complete"
    assert state["downloaded_bytes"] == state["total_bytes"] == 110
    assert state["percent"] == 100


def test_gated_repo_error_is_actionable_and_not_reported_as_download(monkeypatch, tmp_path):
    import huggingface_hub as hub
    import httpx2
    from huggingface_hub.errors import GatedRepoError
    def fail(*args, **kwargs):
        response = httpx2.Response(401, request=httpx2.Request("GET", "https://huggingface.co/test"))
        raise GatedRepoError("private request details", response=response)
    monkeypatch.setattr(hub.HfApi, "model_info", fail)
    progress = tmp_path / "failed.json"
    assert download("small", progress) == 1
    state = json.loads(progress.read_text(encoding="utf-8"))
    assert state["status"] == "failed"
    assert state["percent"] is None
    assert "401/403" in state["message"]
    assert "Token" in state["message"]
    assert "private request" not in state["message"]
