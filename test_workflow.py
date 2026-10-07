import json
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app
from audio_preview import render_preview

client = TestClient(app.app)


def draft(monkeypatch, tmp_path):
    pid = 'd'*32
    folder = tmp_path/pid
    folder.mkdir()
    app.save_json(folder/'project.json',{'id':pid,'name':'test','input':'input.wav','version':'','status':'input_ready','tracks':[]})
    render_preview([{'seconds':0,'length':.1,'pitches':[60]}],folder/'original.wav')
    monkeypatch.setattr(app,'DATA',tmp_path)
    monkeypatch.setattr(app,'jobs',{})
    return pid,folder


def test_audio_whitelist_and_original(monkeypatch,tmp_path):
    pid,folder = draft(monkeypatch,tmp_path)
    assert client.get(f'/api/media/{pid}/audio/original.wav').status_code==200
    assert client.get(f'/api/media/{pid}/audio/project.json').status_code==400
    with pytest.raises(app.HTTPException):
        app.media_source(pid,'../outside.wav')


def test_source_selection_preserves_original_and_tracks(monkeypatch,tmp_path):
    pid,folder = draft(monkeypatch,tmp_path)
    tracks = folder/'stems'/'test'
    tracks.mkdir(parents=True)
    render_preview([{'seconds':0,'length':.1,'pitches':[64]}],tracks/'guitar.wav')
    app.update(folder,tracks=[{'file':'stems/test/guitar.wav','label':'吉他'}])
    calls=[]
    def enqueue(kind,fn,*args,**kwargs):
        calls.append(args)
        return {'job':'mock'}
    monkeypatch.setattr(app,'enqueue',enqueue)
    response=client.post(f'/api/source-transcribe/{pid}',json={'source':'stems/test/guitar.wav','model':'large'})
    assert response.status_code==200
    assert calls[0][-1]==(tracks/'guitar.wav').resolve()
    assert app.metadata(folder)['input']=='input.wav'
    assert app.metadata(folder)['tracks'][0]['label']=='吉他'
    assert client.post(f'/api/source-transcribe/{pid}',json={'source':'missing.wav'}).status_code==400


def test_busy_separation_is_rejected(monkeypatch,tmp_path):
    pid,folder=draft(monkeypatch,tmp_path)
    app.jobs['busy']={'project':pid,'status':'paused'}
    assert client.post(f'/api/separation/{pid}',json={'preset':'six_stem'}).status_code==409


def test_import_media_prepares_stereo_audio(monkeypatch,tmp_path):
    monkeypatch.setattr(app,'DATA',tmp_path)
    calls=[]
    def enqueue(kind,fn,*args,**kwargs):
        calls.append((kind,fn,kwargs['resource']))
        return {'job':'mock'}
    monkeypatch.setattr(app,'enqueue',enqueue)
    source=tmp_path/'test.wav'
    render_preview([{'seconds':0,'length':.1,'pitches':[60]}],source)
    response=client.post('/api/media',files={'file':('test.wav',source.read_bytes(),'audio/wav')})
    assert response.status_code==200
    app.jobs['mock']={}
    try:
        calls[0][1]('mock')
        output=tmp_path/response.json()['project']/'original.wav'
        with wave.open(str(output)) as handle:
            assert handle.getnchannels()==2
            assert handle.getframerate()==44100
    finally:
        app.jobs.pop('mock',None)


def test_preview_is_valid_pcm(tmp_path):
    output=tmp_path/'preview.wav'
    render_preview([{'seconds':0,'length':.2,'pitches':[60,64]}],output)
    with wave.open(str(output)) as handle:
        assert handle.getnframes()>4000
        assert handle.getsampwidth()==2


def test_separation_publishes_only_finished_tracks(monkeypatch,tmp_path):
    pid,folder=draft(monkeypatch,tmp_path)
    callbacks=[]
    monkeypatch.setattr(app,'enqueue',lambda kind,fn,**kwargs:callbacks.append(fn) or {'job':'mock'})
    def process(command,log,timeout=7200):
        output=Path(command[3])
        output.mkdir(parents=True)
        render_preview([{'seconds':0,'length':.1,'pitches':[60]}],output/'guitar.wav')
        (output/'tracks.json').write_text(json.dumps(['guitar.wav']))
    monkeypatch.setattr(app,'run_process',process)
    app.jobs['mock']={}
    try:
        assert client.post(f'/api/separation/{pid}',json={'preset':'six_stem'}).status_code==200
        assert app.metadata(folder)['tracks']==[]
        result=callbacks[0]('mock')
        assert result['tracks'][0]['label']=='吉他'
        assert app.metadata(folder)['status']=='input_ready'
    finally:
        app.jobs.pop('mock',None)
