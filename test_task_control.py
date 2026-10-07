import subprocess
import sys
import threading
import time

import psutil
import pytest
from fastapi.testclient import TestClient

import app
from task_control import Control, Cancelled, controls, context


def test_real_process_pause_resume_cancel(tmp_path):
    control = Control()
    errors = []
    def worker():
        context.control = control
        try:
            app.run_process([sys.executable, '-c', 'import time; time.sleep(30)'], tmp_path / 'process.log')
        except Cancelled:
            errors.append('cancelled')
        finally:
            context.control = None
    thread = threading.Thread(target=worker)
    thread.start()
    deadline = time.monotonic() + 5
    while control.process is None and time.monotonic() < deadline:
        time.sleep(.02)
    assert control.process is not None
    process = psutil.Process(control.process.pid)
    control.action('pause')
    try:
        deadline = time.monotonic() + 2
        while process.status() != psutil.STATUS_STOPPED and time.monotonic() < deadline:
            time.sleep(.05)
        assert process.status() == psutil.STATUS_STOPPED
        control.action('resume')
    finally:
        control.action('cancel')
    thread.join(5)
    assert not thread.is_alive()
    assert errors == ['cancelled']


def test_task_routes_and_busy_state(monkeypatch):
    control = Control()
    monkeypatch.setattr(app, 'jobs', {'test': {'id': 'test', 'kind': 'transcribe', 'status': 'running', 'started': time.time()}})
    controls['test'] = control
    client = TestClient(app.app)
    try:
        assert client.post('/api/jobs/test/pause').status_code == 200
        assert app.jobs['test']['status'] == 'paused'
        assert client.get('/api/status').json()['active_jobs'] == 1
        assert client.post('/api/jobs/test/resume').status_code == 200
        assert app.jobs['test']['status'] == 'running'
        assert client.post('/api/jobs/test/cancel').status_code == 200
        assert control.cancelled
        assert client.post('/api/jobs/test/resume').status_code == 409
        assert client.post('/api/jobs/missing/pause').status_code == 409
    finally:
        controls.pop('test', None)
