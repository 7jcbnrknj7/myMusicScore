from fastapi.testclient import TestClient
from app import app

client = TestClient(app)


def test_project_with_unpitched_percussion_opens(monkeypatch,tmp_path):
    import app as module
    from music21 import stream,note,instrument
    pid='f'*32
    data=tmp_path/'library'
    folder=data/pid/'versions/v-123456abcdef'
    folder.mkdir(parents=True)
    score=stream.Score()
    drums=stream.Part()
    drums.insert(0,instrument.Percussion())
    drums.insert(0,note.Unpitched())
    score.append(drums)
    score.write('musicxml',fp=str(folder/'score.musicxml'))
    module.save_json(folder.parent.parent/'project.json',{'id':pid,'name':'Percussion','version':folder.name,'status':'ready'})
    monkeypatch.setattr(module,'DATA',data)
    response=client.get('/api/projects/'+pid)
    assert response.status_code==200
    assert response.json()['notes']==[]
    assert response.json()['playback']==[]
    assert 'score.musicxml' in response.json()['files']


def test_cross_origin_requests_are_rejected():
    response = client.post("/api/settings", json={}, headers={"Origin": "https://example.com"})
    assert response.status_code == 403


def test_model_and_path_validation():
    assert client.post("/api/models/invalid/download").status_code == 400
    assert client.get("/api/projects/invalid").status_code == 404
    assert client.post("/api/transcribe", files={"file": ("bad.exe", b"bad")}).status_code == 400


def test_local_diagnostics_do_not_include_secrets():
    response = client.get("/api/status")
    assert response.status_code == 200
    assert set(response.json()["models"]) == {"small", "medium", "large"}
    assert "hf_token" not in response.text


def test_invalid_remote_url_does_not_get_saved():
    response = client.post("/api/settings", json={"remote_large": "http://remote.example.com"})
    assert response.status_code == 400


def test_personal_client_name_and_identity():
    response = client.get("/api/client")
    assert response.status_code == 200
    assert response.json()["name"] == "MusicScore"
    assert response.json()["pid"] > 0
    assert len(response.json()["workspace"]) == 20
    assert client.get("/openapi.json").json()["info"]["title"] == "MusicScore"
    assert "MusicScore 我的曲谱" in client.get("/").text


def test_settings_show_install_and_export_directories():
    from app import ROOT
    response = client.get("/api/settings")
    assert response.json()["install_dir"] == str(ROOT)
    assert response.json()["export_dir"]
    assert "可执行文件路径" not in client.get("/").text
    assert "乐谱导出位置" in client.get("/").text


def test_export_directory_validation(tmp_path):
    from app import validate_export_directory
    import pytest
    from fastapi import HTTPException
    assert validate_export_directory(str(tmp_path / "exports")) == tmp_path / "exports"
    with pytest.raises(HTTPException):
        validate_export_directory("relative-folder")
    file = tmp_path / "file"
    file.write_bytes(b"test")
    with pytest.raises(HTTPException):
        validate_export_directory(str(file))


def test_export_directory_is_saved_but_install_location_cannot_be_changed(monkeypatch, tmp_path):
    import app as module
    monkeypatch.setattr(module, "CONFIG", tmp_path / "settings.json")
    export_dir = str(tmp_path / "chosen-exports")
    response = client.post("/api/settings", json={"export_dir": export_dir, "install_dir": "C:\\Windows"})
    assert response.status_code == 200
    assert client.get("/api/settings").json()["export_dir"] == export_dir
    assert client.get("/api/settings").json()["install_dir"] == str(module.ROOT)


def test_exports_use_configured_path_without_overwriting(monkeypatch, tmp_path):
    import app as module
    pid = "a" * 32
    data = tmp_path / "library"
    folder = data / pid / "versions" / "v-123456789abc"
    folder.mkdir(parents=True)
    module.save_json(data / pid / "project.json", {"name": "曲谱:test", "version": "v-123456789abc"})
    (folder / "score.pdf").write_bytes(b"%PDF-test")
    monkeypatch.setattr(module, "DATA", data)
    monkeypatch.setattr(module, "config", lambda: {"export_dir": str(tmp_path / "output")})
    first = client.post(f"/api/projects/{pid}/export", json={"filename": "score.pdf"})
    second = client.post(f"/api/projects/{pid}/export", json={"filename": "score.pdf"})
    assert first.status_code == second.status_code == 200
    from pathlib import Path
    assert Path(first.json()["path"]).read_bytes() == b"%PDF-test"
    assert first.json()["path"] != second.json()["path"]
    assert client.post(f"/api/projects/{pid}/export", json={"filename": "../score.pdf"}).status_code == 400


def test_library_delete_keeps_a_recoverable_copy_and_rejects_busy_projects(monkeypatch, tmp_path):
    import app as module
    pid = "b" * 32
    data = tmp_path / "library"
    folder = data / pid
    folder.mkdir(parents=True)
    module.save_json(folder / "project.json", {"id": pid, "status": "failed", "modified": 0, "version": ""})
    (folder / "input.wav").write_bytes(b"original")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "DATA", data)
    monkeypatch.setattr(module, "jobs", {"busy": {"project": pid, "status": "running"}})
    assert client.get("/api/projects").json()[0]["busy"] is True
    assert client.delete(f"/api/projects/{pid}").status_code == 409
    assert folder.is_dir()
    module.jobs.clear()
    recycled = []
    def recycle(target):
        import shutil
        recycled.append(target)
        shutil.move(target, str(tmp_path / "mock-windows-recycle-bin"))
    monkeypatch.setattr(module, "send2trash", recycle)
    assert client.delete(f"/api/projects/{pid}").status_code == 200
    assert not folder.exists()
    assert recycled == [str(folder.resolve())]
    assert (tmp_path / "mock-windows-recycle-bin" / "input.wav").read_bytes() == b"original"
    assert not (tmp_path / "trash").exists()


def test_duplicate_model_download_returns_existing_job(monkeypatch):
    import app as module
    monkeypatch.setattr(module, "jobs", {"test": {"id": "test", "kind": "download", "model": "medium", "status": "running"}})
    assert client.post("/api/models/medium/download").json() == {"job": "test", "existing": True}


def test_large_download_is_supported_without_starting_network_transfer(monkeypatch):
    import app as module
    monkeypatch.setattr(module, "jobs", {})
    calls = []
    def enqueue(kind, fn, *args, **kwargs):
        calls.append((kind, kwargs))
        return {"job": "mock-large-download"}
    monkeypatch.setattr(module, "enqueue", enqueue)
    response = client.post("/api/models/large/download")
    assert response.status_code == 200
    assert calls == [("download", {"model": "large"})]


def test_local_large_upload_is_supported(monkeypatch, tmp_path):
    import app as module
    monkeypatch.setattr(module, "DATA", tmp_path)
    calls = []
    def enqueue(kind, fn, *args, **kwargs):
        calls.append(args)
        return {"job": "mock-large-transcription"}
    monkeypatch.setattr(module, "enqueue", enqueue)
    response = client.post('/api/transcribe', data={'mode':'local','model':'large'}, files={'file':('test.wav',b'RIFF-test','audio/wav')})
    assert response.status_code == 200
    assert calls[0][1:3] == ('local', 'large')


def test_download_progress_survives_reopening_and_reports_interruption(monkeypatch, tmp_path):
    import app as module
    monkeypatch.setattr(module, "WORK", tmp_path)
    monkeypatch.setattr(module, "jobs", {})
    state = {"status": "running", "message": "download", "progress": {"downloaded_bytes": 100, "total_bytes": 200, "percent": 50}}
    module.save_json(tmp_path / "model-small-download.json", state)
    result = client.get("/api/status").json()["downloads"]["small"]
    assert result["status"] == "interrupted"
    assert result["progress"]["percent"] == 50
