"""MusicScore native Qt launcher; the local worker survives window closure."""
import ctypes
from ctypes import wintypes
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parent
WORK = ROOT / 'work'
WORK.mkdir(exist_ok=True)
TITLE = 'MusicScore - 我的曲谱'
WORKSPACE = hashlib.sha256(str(ROOT).lower().encode()).hexdigest()[:20]
kernel = ctypes.WinDLL('kernel32',use_last_error=True)
kernel.CreateMutexW.argtypes = [wintypes.LPVOID,wintypes.BOOL,wintypes.LPCWSTR]
kernel.CreateMutexW.restype = wintypes.HANDLE
kernel.CloseHandle.argtypes = [wintypes.HANDLE]
kernel.CloseHandle.restype = wintypes.BOOL


def acquire_instance():
    handle = kernel.CreateMutexW(None,False,'Local\\MusicScore-'+WORKSPACE)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error()==183:
        user = ctypes.WinDLL('user32',use_last_error=True)
        user.FindWindowW.argtypes = [wintypes.LPCWSTR,wintypes.LPCWSTR]
        user.FindWindowW.restype = wintypes.HWND
        user.ShowWindow.argtypes = [wintypes.HWND,ctypes.c_int]
        user.SetForegroundWindow.argtypes = [wintypes.HWND]
        hwnd = user.FindWindowW(None,TITLE)
        if hwnd:
            user.ShowWindow(hwnd,9)
            user.SetForegroundWindow(hwnd)
        kernel.CloseHandle(handle)
        return None
    return handle


def matches_backend(client,url):
    try:
        response = client.get(url+'/api/client')
        return response.is_success and response.json().get('workspace')==WORKSPACE
    except Exception:
        return False


def ensure_backend():
    import httpx
    with httpx.Client(timeout=.3,trust_env=False) as client:
        for port in range(8765,8800):
            url = f'http://127.0.0.1:{port}'
            if matches_backend(client,url):
                return url
    log = WORK/('client-server-'+uuid.uuid4().hex[:8]+'.log')
    with log.open('w',encoding='utf-8') as output:
        process = subprocess.Popen([str(ROOT/'.venv/Scripts/python.exe'),str(ROOT/'app.py'),'--no-browser'],
                    cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW)
    deadline = time.monotonic()+45
    with httpx.Client(timeout=.5,trust_env=False) as client:
        while time.monotonic()<deadline:
            match = re.search(r'MusicScore: (http://127\.0\.0\.1:\d+)',log.read_text(encoding='utf-8',errors='replace'))
            if match and matches_backend(client,match[1]):
                return match[1]
            if process.poll() is not None:
                raise RuntimeError('本地服务启动失败，请查看 '+str(log))
            time.sleep(.2)
    raise RuntimeError('本地服务未就绪，请查看 '+str(log))


def main():
    mutex = acquire_instance()
    if mutex is None:
        return
    try:
        shell = ctypes.WinDLL('shell32',use_last_error=True)
        shell.SetCurrentProcessExplicitAppUserModelID.argtypes = [wintypes.LPCWSTR]
        shell.SetCurrentProcessExplicitAppUserModelID('MusicScore.Personal.'+WORKSPACE)
        from qt_client import launch
        launch(ensure_backend(),self_test='--self-test' in sys.argv)
    finally:
        kernel.CloseHandle(mutex)


if __name__=='__main__':
    with (WORK/'desktop.log').open('a',encoding='utf-8',buffering=1) as log:
        import faulthandler
        faulthandler.enable(file=log,all_threads=True)
        sys.stdout = sys.stderr = log
        try:
            main()
        except Exception:
            import traceback
            traceback.print_exc()
            if '--self-test' not in sys.argv:
                ctypes.windll.user32.MessageBoxW(None,'MusicScore 启动失败，请查看应用目录 work/desktop.log。','MusicScore',0x10)
            sys.exit(1)
