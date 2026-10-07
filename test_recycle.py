from fastapi.testclient import TestClient
import app


def test_delete_history_midi_keeps_score_and_version(monkeypatch,tmp_path):
    folder=tmp_path/'project'
    revision='v-123456abcdef'
    version=folder/'versions'/revision
    version.mkdir(parents=True)
    app.save_json(folder/'project.json',{'status':'ready'})
    (version/'score.mid').write_bytes(b'MThd')
    (version/'score.musicxml').write_text('score')
    monkeypatch.setattr(app,'project',lambda pid:folder)
    monkeypatch.setattr(app,'jobs',{})
    recycled=[]
    def recycle(paths):
        from pathlib import Path
        recycled.extend(paths)
        for path in paths:
            Path(path).unlink()
    monkeypatch.setattr(app,'send2trash',recycle)
    response=TestClient(app.app).delete('/api/projects/'+'c'*32+'/versions/'+revision+'/midi')
    assert response.status_code==200
    assert len(recycled)==1
    assert not (version/'score.mid').exists()
    assert (version/'score.musicxml').read_text()=='score'
    assert version.is_dir()


def test_delete_history_midi_recycle_failure_preserves_file(monkeypatch,tmp_path):
    version=tmp_path/'versions/v-123456abcdef'
    version.mkdir(parents=True)
    (version/'score.mid').write_bytes(b'MThd')
    app.save_json(tmp_path/'project.json',{'status':'ready'})
    monkeypatch.setattr(app,'project',lambda pid:tmp_path)
    monkeypatch.setattr(app,'jobs',{})
    def fail(paths):
        raise OSError('unavailable')
    monkeypatch.setattr(app,'send2trash',fail)
    client=TestClient(app.app)
    assert client.delete('/api/projects/'+'c'*32+'/versions/v-123456abcdef/midi').status_code==500
    assert (version/'score.mid').exists()
    assert client.delete('/api/projects/'+'c'*32+'/versions/invalid/midi').status_code==400


def test_recycle_failure_does_not_delete_files(monkeypatch, tmp_path):
    pid = 'c' * 32
    folder = tmp_path / pid
    folder.mkdir()
    app.save_json(folder / 'project.json', {'status': 'ready'})
    (folder / 'score.musicxml').write_text('original')
    monkeypatch.setattr(app, 'project', lambda value: folder)
    monkeypatch.setattr(app, 'jobs', {})
    def fail(path):
        raise OSError('recycle unavailable')
    monkeypatch.setattr(app, 'send2trash', fail)
    response = TestClient(app.app).delete('/api/projects/' + pid)
    assert response.status_code == 500
    assert (folder / 'score.musicxml').read_text() == 'original'
