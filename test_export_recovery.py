import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import app


def test_error_is_not_hidden_by_buffered_diagnostics(tmp_path, monkeypatch):
    log = tmp_path / 'process.log'
    log.write_text('Error: MuseScore failed to generate PDFs\n  timed out after 600s\n' + 'diagnostic\n' * 30, encoding='utf-8')
    class Process:
        def wait(self, **kwargs):
            return 1
    monkeypatch.setattr(app.subprocess, 'Popen', lambda *a, **k: Process())
    with pytest.raises(RuntimeError, match='timed out after 600s'):
        app.run_process(['fake'], log)


def test_upstream_export_timeout_is_extended():
    source = (app.ROOT / 'transcribe_worker.py').read_text(encoding='utf-8')
    assert 'RUN_TIMEOUT_S = 600' in source


def test_partial_local_export_preserves_revision(tmp_path, monkeypatch):
    path = tmp_path / 'project'
    path.mkdir()
    updates = []
    monkeypatch.setattr(app, 'project', lambda pid: path)
    monkeypatch.setattr(app, 'metadata', lambda p: {'input': 'input.mp3'})
    monkeypatch.setattr(app, 'update', lambda p, **kw: updates.append(kw))
    monkeypatch.setattr(app, 'read_score', lambda p: SimpleNamespace(recurse=lambda: SimpleNamespace(notes=[1])))
    def process(command, log, timeout=7200):
        if 'transcribe' in command:
            dest = Path(command[command.index('--output') + 1])
            (dest / 'score.musicxml').write_text('mock score')
            raise RuntimeError('Error: export failed: timed out after 600s')
    monkeypatch.setattr(app, 'run_process', process)
    app.jobs['recovery-test'] = {}
    try:
        result = app.transcribe_job('recovery-test', 'fake', 'local', 'small', [])
        assert 'warning' in result
        assert updates[-1]['status'] == 'ready'
        assert updates[-1]['version'].startswith('v-')
        assert next((path / 'versions').glob('*/revision.json')).exists()
    finally:
        app.jobs.pop('recovery-test', None)
