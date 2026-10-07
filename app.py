import atexit
import copy
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
from pathlib import Path
from urllib.parse import urlparse
from typing import Literal

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "library"
WORK = ROOT / "work"
MODELS = ROOT / "models"
for directory in (DATA, WORK, MODELS):
    directory.mkdir(exist_ok=True)
os.environ["HF_HOME"] = str(MODELS / "huggingface")
os.environ["TORCH_HOME"] = str(MODELS / "torch")
os.environ["PYTORCH_ALLOC_CONF"] = "expandable_segments:True"

import httpx
import imageio_ffmpeg
import keyring
from music21 import stream
from task_control import Control, Cancelled, controls, context, checkpoint
from send2trash import send2trash
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from music import describe_score, edit_note, playback, read_score, recognize_chords, score_notes, transpose_score
from notation import export_views, prepare_piano_hands
from arrangement import availability as arrangement_availability, prepare_melody, STYLES

app = FastAPI(title="MusicScore", version="1.0.0")
pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
jobs = {}
edit_lock = threading.Lock()
child_guard = threading.Lock()
children = set()
CONFIG = ROOT / "settings.json"
CREDENTIAL_SERVICE = "ScoreDesk"  # Keep existing Windows credentials after the rename.


def config():
    default = {"musescore": "", "provider": "openai", "llm_url": "https://api.openai.com/v1",
               "llm_model": "", "remote_small": "", "remote_medium": "", "remote_large": "",
               "export_dir": str(ROOT / "exports")}
    if CONFIG.exists():
        default.update(json.loads(CONFIG.read_text(encoding="utf-8")))
    return default


def save_json(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def secret(name):
    return keyring.get_password(CREDENTIAL_SERVICE, name) or ""


def environment():
    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'
    token = secret("huggingface")
    if token:
        env["HF_TOKEN"] = token
    executable = config()["musescore"] or detect_musescore()
    if executable:
        env["MUSCRIPTOR_MUSESCORE"] = executable
    return env


@app.middleware("http")
async def local_only(request: Request, call_next):
    host = request.headers.get("host", "").split(":")[0]
    origin = request.headers.get("origin")
    if host not in ("127.0.0.1", "localhost", "testserver") or (origin and urlparse(origin).netloc != request.headers.get("host")):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Local access only"}, status_code=403)
    return await call_next(request)


def project(pid):
    if not re.fullmatch(r"[0-9a-f]{32}", pid):
        raise HTTPException(404, "Project not found")
    path = DATA / pid
    if not (path / "project.json").exists():
        raise HTTPException(404, "Project not found")
    return path


def metadata(path):
    return json.loads((path / "project.json").read_text(encoding="utf-8"))


def update(path, **values):
    data = metadata(path)
    data.update(values)
    save_json(path / "project.json", data)


def version_dir(path):
    data = metadata(path)
    return path / "versions" / data["version"]


def score_path(path):
    return version_dir(path) / "score.musicxml"


def run_process(command, log, timeout=7200):
    checkpoint()
    with log.open("a", encoding="utf-8") as handle:
        process = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT, env=environment(),
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        with child_guard:
            children.add(process)
        try:
            control = getattr(context, 'control', None)
            if control:
                with control.lock:
                    control.process = process
                    if control.cancelled:
                        control.action('cancel')
                    elif control.paused:
                        control.action('pause')
                elapsed = 0
                while process.poll() is None:
                    checkpoint()
                    start = time.monotonic()
                    try:
                        process.wait(timeout=.2)
                    except subprocess.TimeoutExpired:
                        pass
                    elapsed += time.monotonic() - start
                    if elapsed > timeout:
                        raise subprocess.TimeoutExpired(command, timeout)
                checkpoint()
                code = process.returncode
            else:
                code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise RuntimeError("Operation timed out")
        finally:
            if getattr(context, 'control', None):
                context.control.process = None
            with child_guard:
                children.discard(process)
        if code:
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
            errors = [line for line in lines if re.search(r"Error:|Exception:|timed out|out of memory", line, re.I)]
            tail = "\n".join(errors[-3:] or lines[-6:])[:1500]
            if re.search(r'CUDA.*out of memory|OutOfMemoryError', tail, re.I):
                tail = '显存不足，请关闭其他占用显卡的程序，或切换为 medium / small。\n' + tail
            raise RuntimeError(tail or f"Process failed ({code})")


def enqueue(kind, fn, *args, resource=None, model=None):
    jid = uuid.uuid4().hex
    controls[jid] = Control()
    jobs[jid] = {"id": jid, "kind": kind, "status": "queued", "message": "等待处理", "created": time.time(),
                 "model": model, "project": resource or (args[0] if args and isinstance(args[0], str) and re.fullmatch(r"[0-9a-f]{32}", args[0]) else None)}
    def execute():
        context.control = controls[jid]
        try:
            checkpoint()
            jobs[jid].update(status="running", message="正在处理", started=time.time())
            result = fn(jid, *args)
            checkpoint()
            jobs[jid].update(status="complete", message="完成", result=result)
        except Cancelled:
            jobs[jid].update(status="cancelled", message="已取消，原始文件和已生成成果保留")
            pid = jobs[jid].get('project')
            if pid and jobs[jid]['kind']=='separate' and jobs[jid]['status']=='running':
                log = DATA/pid/'separation.log'
                if log.exists() and log.stat().st_size<2000000:
                    text = log.read_text(encoding='utf-8',errors='replace')
                    if '开始分轨' in text:
                        jobs[jid]['message'] = '分轨处理中，完成后可逐轨试听'
                    percentages = re.findall(r'(\d{1,3})%\|',text)
                    if percentages:
                        jobs[jid]['progress'] = {'percent':min(100,int(percentages[-1]))}
                        jobs[jid]['detail'] = '当前步骤：'+('分轨推理' if '开始分轨' in text else '模型加载或下载')
            if pid:
                path = project(pid)
                update(path, status="ready" if metadata(path).get('version') else ("input_ready" if (path/'original.wav').exists() else "cancelled"), error="")
        except Exception as exc:
            message = str(exc)
            for name in ("huggingface", "llm-openai", "llm-deepseek", "llm-custom", "remote"):
                token = secret(name)
                if token:
                    message = message.replace(token, "[redacted]")
            jobs[jid].update(status="failed", message=message)
        finally:
            context.control = None
            controls.pop(jid, None)
    pool.submit(execute)
    return {"job": jid}


@app.post('/api/jobs/{jid}/{action}')
def control_job(jid: str, action: str):
    if action not in ('pause', 'resume', 'cancel'):
        raise HTTPException(400, '未知操作')
    job = jobs.get(jid)
    control = controls.get(jid)
    if not job or not control or job['status'] in ('complete', 'failed', 'cancelled'):
        raise HTTPException(409, '任务已结束')
    if job['status'] == 'cancelling':
        raise HTTPException(409, '任务正在取消')
    previous = job['status']
    control.action(action)
    job['status'] = 'cancelling' if action == 'cancel' else ('paused' if action == 'pause' else ('queued' if previous == 'paused' and not job.get('started') else 'running'))
    return {'ok': True}


def detect_musescore():
    existing = config()["musescore"]
    candidates = [Path(existing)] if existing else []
    for base in (ROOT / "tools", Path("C:/Program Files"), Path("C:/Program Files (x86)")):
        if base.exists():
            candidates.extend(base.glob("**/MuseScore4.exe"))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return ""


def controlled_musescore(binary, args):
    with tempfile.TemporaryDirectory(prefix='musicscore-export-') as temporary:
        log = Path(temporary) / 'output.log'
        run_process([binary, *args], log, 600)
        return subprocess.CompletedProcess(args, 0, log.read_text(encoding='utf-8', errors='replace'), '')


def engrave(path):
    from muscriptor.utils import sheets
    sheets.RUN_TIMEOUT_S = 600
    sheets._run = controlled_musescore
    binary = detect_musescore()
    if not binary:
        raise RuntimeError("MuseScore 未安装或未配置路径")
    log = path / "export.log"
    source = path / "score.musicxml"
    for extension in ("mscz", "pdf", "mid"):
        output = path / f"score.{extension}"
        run_process([binary, "-o", str(output), str(source)], log, 600)
        if not output.exists() or output.stat().st_size == 0:
            raise RuntimeError(f"MuseScore 未生成 {extension}")
    from muscriptor.utils.sheets import convert_to_tab_staves, fretted_parts, _write_part_pdfs
    native = path / "score.mscx"
    run_process([binary, "-o", str(native), str(source)], log, 180)
    if not native.exists():
        raise RuntimeError("MuseScore 未生成原生谱面")
    _write_part_pdfs(binary, native, path)
    from notation import tablature_parts, retain_tab_instruments
    tab_indices = tablature_parts(read_score(source),native)
    if tab_indices:
        tab = path / "tab.mscx"
        shutil.copy2(native, tab)
        retain_tab_instruments(tab,tab_indices)
        convert_to_tab_staves(tab)
        run_process([binary, "-o", str(path / "tab.pdf"), str(tab)], log, 180)
        run_process([binary, "-o", str(path / "tab.mscz"), str(tab)], log, 180)
        _write_part_pdfs(binary, tab, path, suffix="_tab", only=set(tab_indices))
    export_views(read_score(source), path, binary, run_process)


def make_revision(path, score, description):
    ident = "v-" + uuid.uuid4().hex[:12]
    dest = path / "versions" / ident
    dest.mkdir(parents=True)
    try:
        score.write("musicxml", fp=str(dest / "score.musicxml"))
        engrave(dest)
        save_json(dest / "revision.json", {"description": description, "created": time.time()})
        update(path, version=ident, status="ready", modified=time.time())
    except Exception:
        save_json(dest / "revision.json", {"description": description, "status": "failed"})
        raise
    return metadata(path)


def transcribe_job(jid, pid, mode, model, instruments, source=None):
    path = project(pid)
    try:
        update(path, status="running")
        jobs[jid]["message"] = "提取音频"
        audio = path / "audio.wav"
        run_process([imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-y", "-i", str(source or path / metadata(path)["input"]),
                     "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "24000", str(audio)], path / "process.log", 600)
        ident = "v-" + uuid.uuid4().hex[:12]
        dest = path / "versions" / ident
        dest.mkdir(parents=True)
        if mode == "local":
            jobs[jid]["message"] = f"本地 {model} 转录与制谱"
            command = [sys.executable, str(ROOT / "transcribe_worker.py"), "transcribe", str(audio), "--model", model,
                       "--device", "cuda", "--dtype", "float16", "--batch-size", "1", "--format", "sheets", "--output", str(dest)]
            if instruments:
                command += ["--instruments", ",".join(instruments)]
            try:
                run_process(command, path / "process.log")
            except RuntimeError as exc:
                source = dest / "score.musicxml"
                if not source.exists() or not len(read_score(source).recurse().notes):
                    raise RuntimeError("转录或制谱失败，未得到有效音符：" + str(exc)) from exc
                warning = "转录已保存，但部分乐谱导出失败：" + str(exc)
                save_json(dest / "revision.json", {"description": "原始转录（部分导出）", "created": time.time(), "warning": warning})
                update(path, version=ident, status="ready", modified=time.time(), error="", warning=warning)
                jobs[jid]["message"] = warning
                return {"project": pid, "warning": warning}
        else:
            jobs[jid]["message"] = f"远程 {model} 转录"
            url = config()["remote_" + model].rstrip("/")
            if not url:
                raise RuntimeError(f"请先设置远程 {model} MuScriptor 服务地址")
            headers = {"Authorization": "Bearer " + secret("remote")} if secret("remote") else {}
            fields = [("instruments", x) for x in instruments]
            with audio.open("rb") as handle, httpx.Client(timeout=7200) as client:
                response = client.post(url + "/transcribe/midi", files=[("file", ("audio.wav", handle, "audio/wav"))] +
                                       [(k, (None, v)) for k, v in fields], headers=headers)
                response.raise_for_status()
                if not response.content.startswith(b"MThd"):
                    raise RuntimeError("远程服务未返回有效 MIDI")
                midi = dest / "score.mid"
                midi.write_bytes(response.content)
            score = read_score(midi)
            score.write("musicxml", fp=str(dest / "score.musicxml"))
        if not (dest / "score.musicxml").exists():
            raise RuntimeError("未生成 MusicXML")
        jobs[jid]["message"] = "钢琴与吉他和弦分析"
        score = read_score(dest / "score.musicxml")
        checkpoint()
        if not len(score.recurse().notes):
            raise RuntimeError("没有识别到音符，请检查音频音量及所选乐器，或改用自动识别")
        count = recognize_chords(score)
        prepare_piano_hands(score)
        score.write("musicxml", fp=str(dest / "score.musicxml"))
        checkpoint()
        jobs[jid]['message'] = '导出总谱、分谱和派生谱式'
        warning = ""
        try:
            engrave(dest)
        except Cancelled:
            raise
        except Exception as exc:
            warning = "音符已保存，但部分乐谱导出失败：" + str(exc)[:1500]
        save_json(dest / "revision.json", {"description": "原始转录 + 自动和弦", "created": time.time(), "chords": count})
        update(path, version=ident, status="ready", modified=time.time(), chords=count, warning=warning, error="")
        return {"project": pid, "chords": count}
    except Exception as exc:
        update(path, status="failed", error=str(exc))
        raise


class Settings(BaseModel):
    musescore: str = ""
    export_dir: str = ""
    provider: Literal["openai", "deepseek", "custom"] = "openai"
    llm_url: str = "https://api.openai.com/v1"
    llm_model: str = ""
    remote_small: str = ""
    remote_medium: str = ""
    remote_large: str = ""
    hf_token: str = ""
    llm_key: str = ""
    remote_key: str = ""


def validate_url(value):
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(400, "请输入有效 HTTP/HTTPS 服务地址，不要在地址中放入密钥")
    if parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost"):
        raise HTTPException(400, "远程服务请使用 HTTPS")


@app.get("/api/settings")
def get_settings():
    value = config()
    value["musescore"] = detect_musescore()
    value["install_dir"] = str(ROOT)
    value["credentials"] = {n: bool(secret(n)) for n in ("huggingface", "remote")}
    value["credentials"]["llm"] = bool(secret("llm-" + value["provider"]))
    return value


@app.post("/api/settings")
def set_settings(value: Settings):
    data = value.model_dump()
    for name in ("llm_url", "remote_small", "remote_medium", "remote_large"):
        if data[name]:
            validate_url(data[name])
    if data["musescore"] and not Path(data["musescore"]).is_file():
        raise HTTPException(400, "MuseScore 可执行文件不存在")
    data["export_dir"] = str(validate_export_directory(data["export_dir"] or config()["export_dir"]))
    for field, name in (("hf_token", "huggingface"), ("llm_key", "llm-" + data["provider"]), ("remote_key", "remote")):
        token = data.pop(field)
        if token:
            keyring.set_password(CREDENTIAL_SERVICE, name, token)
    save_json(CONFIG, data)
    return {"ok": True}


def validate_export_directory(value):
    directory = Path(value).expanduser()
    if not directory.is_absolute():
        raise HTTPException(400, "乐谱导出位置必须是完整的文件夹路径")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=directory):
            pass
    except OSError as exc:
        raise HTTPException(400, "乐谱导出位置不可写，请选择其他文件夹") from exc
    return directory.resolve()


@app.get("/api/status")
def status():
    for jid, control in list(controls.items()):
        if jid in jobs:
            jobs[jid]['pause_pending'] = control.paused and not control.process and not control.waiting
            pid = jobs[jid].get('project')
            if pid and jobs[jid]['kind'] == 'transcribe':
                log = DATA / pid / 'process.log'
                if log.exists() and log.stat().st_size < 2000000:
                    text = log.read_text(encoding='utf-8', errors='replace')
                    total = re.search(r'audio: ([\d.]+)s.*?(\d+) chunk', text)
                    if total:
                        chunks = min(int(total[2]), len(re.findall(r'\[muscriptor\] mel-spec', text)))
                        jobs[jid]['detail'] = f'音频 {total[1]} 秒 · 已输入 {chunks}/{total[2]} 个片段'
    snapshots = MODELS / "huggingface" / "hub"
    cached = {}
    for size in ("small", "medium", "large"):
        cached[size] = any(p.stat().st_size > 100000000 for p in snapshots.glob(f"models--*--muscriptor-{size}/snapshots/*/model.safetensors"))
    downloads = {}
    for size in ("small", "medium", "large"):
        persisted = read_progress(WORK / f"model-{size}-download.json")
        latest = next((j for j in reversed(list(jobs.values())) if j["kind"] == "download" and j.get("model") == size), None)
        if latest:
            latest["progress"] = read_progress(WORK / f"download-{latest['id']}.json") or latest.get("progress", {})
            downloads[size] = {**latest, "progress": latest["progress"]}
        elif persisted:
            if persisted["status"] in ("queued", "running"):
                persisted = {**persisted, "status": "interrupted", "message": "上次下载已中断，可重新下载以继续缓存的传输。"}
            downloads[size] = persisted
    return {"musescore": bool(detect_musescore()), "models": cached, "downloads": downloads,
            "library": str(DATA), "jobs": list(jobs.values())[-12:],
            "active_jobs": sum(j["status"] in ("queued", "running", "paused", "cancelling") for j in jobs.values())}


@app.get("/api/client")
def client_identity():
    return {"name": "MusicScore", "pid": os.getpid(),
            "workspace": hashlib.sha256(str(ROOT).lower().encode()).hexdigest()[:20]}


@app.post("/api/models/{size}/download")
def download_model(size: str):
    if size not in ("small", "medium", "large"):
        raise HTTPException(400, "本地模型请选择 small、medium 或 large")
    existing = next((j for j in jobs.values() if j["kind"] == "download" and j.get("model") == size and j["status"] in ("queued", "running", "paused", "cancelling")), None)
    if existing:
        return {"job": existing["id"], "existing": True}
    def download(jid):
        jobs[jid]["message"] = f"下载官方 {size} 权重"
        log = WORK / f"download-{size}.log"
        progress = WORK / f"download-{jid}.json"
        persisted = WORK / f"model-{size}-download.json"
        save_json(persisted, {"model": size, "status": "running", "message": jobs[jid]["message"], "progress": {}})
        try:
            run_process([sys.executable, str(ROOT / "model_download.py"), size, str(progress)], log)
        except Exception:
            state = read_progress(progress)
            message = state.get("message") or "模型下载失败，请检查网络、Token 与模型访问权限。"
            save_json(persisted, {"model": size, "status": "failed", "message": message, "progress": state})
            raise RuntimeError(message) from None
        state = read_progress(progress)
        save_json(persisted, {"model": size, "status": "complete", "message": "下载完成", "progress": state})
        return {"model": size}
    return enqueue("download", download, model=size)


def read_progress(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@app.get("/api/instruments")
def instruments():
    from muscriptor.tokenizer.mt3 import MT3_FULL_PLUS_GROUP_NAMES
    return list(MT3_FULL_PLUS_GROUP_NAMES)


@app.get("/api/projects")
def projects():
    result = [metadata(p.parent) for p in DATA.glob("*/project.json")]
    for item in result:
        item["busy"] = item["status"] in ("queued", "running") or any(
            j.get("project") == item["id"] and j["status"] in ("queued", "running", "paused", "cancelling") for j in jobs.values())
    return sorted(result, key=lambda x: x["modified"], reverse=True)


@app.post("/api/transcribe")
async def upload(file: UploadFile = File(...), mode: str = Form("local"), model: str = Form("medium"), instruments: str = Form("")):
    if mode not in ("local", "remote") or model not in ("small", "medium", "large"):
        raise HTTPException(400, "模型选择无效")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aiff", ".mp4", ".mov", ".mkv", ".webm", ".avi", ".mid", ".midi", ".musicxml", ".xml", ".mscz"):
        raise HTTPException(400, "不支持的文件格式")
    pid = uuid.uuid4().hex
    path = DATA / pid
    path.mkdir()
    source = path / ("input" + suffix)
    total = 0
    try:
        with source.open("wb") as handle:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > 2 * 1024 ** 3:
                    raise HTTPException(413, "文件最大 2GB")
                handle.write(chunk)
        save_json(path / "project.json", {"id": pid, "name": Path(file.filename).stem, "input": source.name,
                  "version": "", "status": "queued", "model": model, "mode": mode, "modified": time.time()})
    except Exception:
        shutil.rmtree(path)
        raise
    if suffix in (".mid", ".midi", ".musicxml", ".xml", ".mscz"):
        def import_score(jid):
            try:
                update(path, status="running")
                if suffix == ".mscz":
                    converted = path / "import.musicxml"
                    binary = detect_musescore()
                    if not binary:
                        raise RuntimeError("需要 MuseScore 导入 MSCZ")
                    run_process([binary, "-o", str(converted), str(source)], path / "process.log", 180)
                    score = read_score(converted)
                else:
                    score = read_score(source)
                recognize_chords(score)
                prepare_piano_hands(score)
                make_revision(path, score, "导入乐谱")
                return {"project": pid}
            except Exception as exc:
                update(path, status="failed", error=str(exc))
                raise
        return {**enqueue("import", import_score, resource=pid), "project": pid}
    return {**enqueue("transcribe", transcribe_job, pid, mode, model, [x.strip() for x in instruments.split(",") if x.strip()]), "project": pid}


@app.get("/api/projects/{pid}")
def detail(pid: str):
    path = project(pid)
    data = metadata(path)
    if data["version"]:
        score = read_score(score_path(path))
        data.update(parts=describe_score(score), notes=score_notes(score), playback=playback(score),
                    files=[p.name for p in version_dir(path).iterdir() if p.suffix in (".pdf", ".mscz", ".musicxml", ".mid")],
                    revisions=[{**json.loads(p.read_text(encoding="utf-8")), "id": p.parent.name,
                                "midi_files": [f.name for f in p.parent.iterdir() if f.is_file() and f.suffix.lower() in ('.mid','.midi')]}
                               for p in (path / "versions").glob("*/revision.json")])
    return data


@app.get("/api/projects/{pid}/files/{filename}")
def get_file(pid: str, filename: str):
    return FileResponse(project_file(pid, filename))


class ArrangementOptions(BaseModel):
    part: int = Field(0,ge=0)
    style: Literal['pop_standard','pop_complex','dark','r&b'] = 'pop_standard'
    tonic: Literal['C','C#','Db','D','Eb','E','F','F#','Gb','G','Ab','A','Bb','B'] = 'C'
    mode: Literal['maj','min'] = 'maj'
    segmentation: str = Field('',max_length=256)
    texture: bool = False
    rhythm: int = Field(2,ge=0,le=4)
    voices: int = Field(2,ge=0,le=4)


@app.get('/api/arrangement/status')
def arrangement_status():
    return arrangement_availability()


def arrange_job(jid,pid,value,source_version):
    path = project(pid)
    with edit_lock:
        jobs[jid]['message']='准备旋律与乐句分段'
        source = read_score(path/'versions'/source_version/'score.musicxml')
        ident='v-'+uuid.uuid4().hex[:12]
        dest=path/'versions'/ident
        dest.mkdir(parents=True)
        try:
            info=prepare_melody(source,value.part,dest/'melody.mid',value.segmentation)
            spec={**value.model_dump(),**info,'melody':str(dest/'melody.mid'),'output':str(dest)}
            save_json(dest/'arrangement-input.json',spec)
            jobs[jid]['message']='AccoMontage2 和声编配 · '+STYLES[value.style]
            run_process([sys.executable,str(ROOT/'arrangement_worker.py'),str(dest/'arrangement-input.json')],dest/'arrangement.log')
            checkpoint()
            output=dest/('textured_chord_gen.mid' if value.texture else 'chord_gen.mid')
            if not output.is_file():
                raise RuntimeError('AccoMontage2 未生成编配 MIDI')
            arranged=read_score(output)
            # Keep the source melody exactly; append only generated accompaniment.
            result=stream.Score()
            result.append(copy.deepcopy(source.parts[value.part]))
            for start,_,mark in source.metronomeMarkBoundaries():
                result.insert(start,copy.deepcopy(mark))
            for accompaniment in list(arranged.parts)[1:]:
                result.append(accompaniment)
            if len(result.parts)<2:
                raise RuntimeError('未得到有效伴奏声部')
            recognize_chords(result)
            prepare_piano_hands(result)
            result.write('musicxml',fp=str(dest/'score.musicxml'))
            jobs[jid]['message']='导出编配乐谱'
            warning=''
            try:
                engrave(dest)
            except Cancelled:
                raise
            except Exception as exc:
                warning='编配已保存，部分谱式导出失败：'+str(exc)[:1200]
            description='和声编配 · '+STYLES[value.style]
            save_json(dest/'revision.json',{'description':description,'created':time.time(),'arrangement':spec,'source_version':source_version,'warning':warning})
            update(path,version=ident,status='ready',error='',warning=warning,modified=time.time())
            return {'project':pid,'version':ident,'warning':warning}
        except Exception:
            save_json(dest/'revision.json',{'description':'和声编配失败 · '+STYLES[value.style],'created':time.time(),'status':'failed'})
            raise


@app.post('/api/projects/{pid}/arrange')
def arrange(pid: str,value: ArrangementOptions):
    path=project(pid)
    data=metadata(path)
    if not data.get('version'):
        raise HTTPException(400,'请先生成或导入旋律乐谱')
    if any(j.get('project')==pid and j['status'] in ('queued','running','paused','cancelling') for j in jobs.values()):
        raise HTTPException(409,'该曲目仍有任务进行中')
    status=arrangement_availability()
    if not status['installed'] or (value.texture and not status['texture_ready']):
        raise HTTPException(400,'AccoMontage2 完整伴奏资源尚未就绪；可先选择和声编配')
    if value.part>=len(read_score(score_path(path)).parts):
        raise HTTPException(400,'旋律声部无效')
    return enqueue('arrange',arrange_job,pid,value,data['version'])


@app.delete('/api/projects/{pid}/versions/{revision}/midi')
def delete_revision_midi(pid: str, revision: str):
    path = project(pid)
    if not re.fullmatch(r'v-[0-9a-f]{12}',revision):
        raise HTTPException(400,'版本编号无效')
    if metadata(path).get('status') in ('queued','running') or any(j.get('project')==pid and j['status'] in ('queued','running','paused','cancelling') for j in jobs.values()):
        raise HTTPException(409,'任务尚未结束')
    folder = path/'versions'/revision
    if not folder.is_dir() or folder.is_symlink() or not folder.resolve().is_relative_to(path.resolve()):
        raise HTTPException(404,'历史版本不存在')
    files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in ('.mid','.midi')]
    if not files:
        raise HTTPException(404,'该版本没有 MIDI 文件')
    if any(f.is_symlink() or not f.resolve().is_relative_to(folder.resolve()) for f in files):
        raise HTTPException(400,'MIDI 路径无效')
    try:
        send2trash([str(f.resolve()) for f in files])
    except OSError as exc:
        raise HTTPException(500,'无法移入 Windows 回收站，未执行永久删除') from exc
    return {'ok':True,'deleted':[f.name for f in files]}


def project_file(pid, filename):
    if Path(filename).name != filename or Path(filename).suffix not in (".pdf", ".mscz", ".musicxml", ".mid"):
        raise HTTPException(400, "文件名无效")
    path = version_dir(project(pid)) / filename
    if not path.is_file():
        raise HTTPException(404, "文件不存在")
    return path


class ExportFile(BaseModel):
    filename: str = Field(..., min_length=1, max_length=200)


@app.post("/api/projects/{pid}/export")
def export_file(pid: str, value: ExportFile):
    source = project_file(pid, value.filename)
    data = metadata(project(pid))
    directory = validate_export_directory(config()["export_dir"])
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", data["name"]).strip(" .")[:60] or "MusicScore"
    destination = directory / (name + "-" + pid[:8]) / data["version"]
    destination.mkdir(parents=True, exist_ok=True)
    for index in range(1, 10000):
        target = destination / (source.name if index == 1 else f"{source.stem}_{index}{source.suffix}")
        try:
            output = target.open("xb")
        except FileExistsError:
            continue
        try:
            with output, source.open("rb") as handle:
                shutil.copyfileobj(handle, output)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return {"path": str(target), "directory": str(destination)}
    raise HTTPException(409, "该文件的导出副本过多，请更换导出目录")


class Change(BaseModel):
    semitones: int = Field(0, ge=-24, le=24)
    part: int | None = Field(None, ge=0)
    index: int = Field(0, ge=0)
    pitches: list[int] = []
    duration: float = Field(1, gt=0, le=32)
    version: str = ""


@app.post("/api/projects/{pid}/{operation}")
def modify(pid: str, operation: str, value: Change):
    if operation not in ("transpose", "note", "chords", "restore", "sync"):
        raise HTTPException(404, "Unknown operation")
    path = project(pid)
    if not metadata(path)["version"]:
        raise HTTPException(400, "尚未生成谱面")
    def change(jid):
        with edit_lock:
            if operation == "restore":
                if not re.fullmatch(r"v-[0-9a-f]{12}", value.version):
                    raise ValueError("版本无效")
                dest = path / "versions" / value.version
                if not (dest / "score.pdf").is_file() or not (dest / "score.musicxml").is_file():
                    raise ValueError("该版本未完成导出")
                update(path, version=value.version, modified=time.time())
                return {"project": pid}
            source = score_path(path)
            if operation == "sync":
                edited = version_dir(path) / "edited.mscz"
                if not edited.exists():
                    raise ValueError("先在 MuseScore 中保存编辑副本")
                source = WORK / (uuid.uuid4().hex + ".musicxml")
                run_process([detect_musescore(), "-o", str(source), str(edited)], path / "process.log", 180)
            score = read_score(source)
            if value.part is not None and value.part >= len(score.parts):
                raise ValueError("声部无效")
            if operation == "transpose":
                transpose_score(score, value.semitones, value.part)
            elif operation == "note":
                if value.part is None or not value.pitches or any(type(p) is not int or p < 0 or p > 127 for p in value.pitches):
                    raise ValueError("音高或声部无效")
                edit_note(score, value.part, value.index, value.pitches, value.duration)
                recognize_chords(score)
            elif operation == "chords":
                recognize_chords(score, value.part)
            make_revision(path, score, {"transpose": "移调", "note": "修改音符", "chords": "重新识别和弦", "sync": "同步 MuseScore 编辑"}[operation])
            return {"project": pid}
    return enqueue(operation, change, resource=pid)


@app.post("/api/musescore/{pid}")
def open_editor(pid: str, view: str = "score"):
    path = project(pid)
    if not metadata(path)["version"]:
        raise HTTPException(400, "尚未生成谱面")
    binary = detect_musescore()
    if not binary:
        raise HTTPException(400, "MuseScore 路径未配置")
    folder = version_dir(path)
    if view != "score":
        if not re.fullmatch(r"(?:guitar-\d+-combined|piano-staff|piano-numbered)", view):
            raise HTTPException(400, "谱式无效")
        display = folder / (view + ".mscz")
        if not display.is_file():
            raise HTTPException(404, "该谱式尚未生成")
        subprocess.Popen([binary, str(display)])
        return {"ok": True, "derived": True}
    edited = folder / "edited.mscz"
    if not edited.exists():
        shutil.copy2(folder / "score.mscz", edited)
    subprocess.Popen([binary, str(edited)])
    return {"ok": True}


@app.post("/api/assistant/{pid}")
def assistant(pid: str, prompt: str = Form(...)):
    path = project(pid)
    cfg = config()
    assistant_key = secret("llm-" + cfg["provider"])
    if not cfg["llm_model"] or not assistant_key:
        raise HTTPException(400, "请配置 API 模型 ID 和密钥")
    score = read_score(score_path(path))
    context = {"parts": describe_score(score), "notes": score_notes(score)[:1000]}
    try:
        with httpx.Client(timeout=120) as client:
            response = client.post(cfg["llm_url"].rstrip("/") + "/chat/completions",
                headers={"Authorization": "Bearer " + assistant_key},
                json={"model": cfg["llm_model"], "messages": [
                    {"role": "system", "content": "你是音乐编配助手。根据提供的音符回答中文建议，不声称听过原音频。只提供建议，不声称已经修改乐谱。音符列表最多覆盖1000个事件，请说明范围限制。"},
                    {"role": "user", "content": json.dumps(context, ensure_ascii=False) + "\n用户要求：" + prompt}]})
            response.raise_for_status()
            return {"answer": response.json()["choices"][0]["message"]["content"]}
    except Exception as exc:
        raise HTTPException(502, "AI 服务调用失败，请检查地址、模型 ID 和密钥") from exc


@app.delete("/api/projects/{pid}")
def archive(pid: str):
    path = project(pid)
    if metadata(path)["status"] in ("queued", "running") or any(j.get("project") == pid and j["status"] in ("queued", "running", "paused", "cancelling") for j in jobs.values()):
        raise HTTPException(409, "任务尚未结束")
    try:
        send2trash(str(path.resolve()))
    except OSError as exc:
        raise HTTPException(500, "无法移入 Windows 回收站，未执行永久删除，请检查磁盘和文件占用") from exc
    return {"ok": True}


MEDIA_SUFFIXES = {'.wav', '.mp3', '.flac', '.ogg', '.m4a', '.aiff', '.mp4', '.mov', '.mkv', '.webm', '.avi'}
STEM_NAMES = {'vocals':'人声', 'drums':'鼓组', 'bass':'贝斯', 'other':'其他乐器', 'guitar':'吉他', 'piano':'钢琴', 'instrumental':'伴奏'}


def ensure_idle(pid):
    if any(j.get('project') == pid and j['status'] in ('queued','running','paused','cancelling') for j in jobs.values()):
        raise HTTPException(409, '该曲子还有未结束的任务')


def media_source(pid, key):
    path = project(pid)
    data = metadata(path)
    allowed = {'original.wav'} | {t['file'] for t in data.get('tracks', [])}
    if key not in allowed:
        raise HTTPException(400, '音轨不存在')
    source = (path / key).resolve()
    if key == 'original.wav' and not source.exists() and (path/'audio.wav').is_file():
        source = (path/'audio.wav').resolve()
    if not source.is_relative_to(path.resolve()) or not source.is_file():
        raise HTTPException(404, '音轨文件尚未生成')
    return source


@app.post('/api/media')
async def import_media(file: UploadFile = File(...)):
    suffix = Path(file.filename or '').suffix.lower()
    if suffix not in MEDIA_SUFFIXES:
        raise HTTPException(400, '请选择音频或视频文件')
    pid = uuid.uuid4().hex
    path = DATA / pid
    path.mkdir()
    source = path / ('input' + suffix)
    try:
        total = 0
        with source.open('wb') as output:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > 2 * 1024**3:
                    raise HTTPException(413, '文件最大 2GB')
                output.write(chunk)
        save_json(path / 'project.json', {'id':pid,'name':Path(file.filename).stem,'input':source.name,
                  'version':'','status':'queued','model':'medium','mode':'local','modified':time.time(),'tracks':[]})
    except Exception:
        shutil.rmtree(path)
        raise
    def prepare(jid):
        jobs[jid]['message'] = '提取可试听音频'
        update(path, status='running')
        try:
            run_process([imageio_ffmpeg.get_ffmpeg_exe(),'-nostdin','-y','-i',str(source),'-map','0:a:0','-vn','-ac','2','-ar','44100',str(path/'original.wav')], path/'media.log',600)
            update(path, status='input_ready', error='')
            return {'project':pid}
        except Exception as exc:
            update(path, status='failed', error=str(exc))
            raise
    return {**enqueue('prepare',prepare,resource=pid),'project':pid}


class SeparationRequest(BaseModel):
    preset: Literal['six_stem','four_stem','vocals'] = 'six_stem'


@app.post('/api/separation/{pid}')
def separate_media(pid: str, value: SeparationRequest):
    ensure_idle(pid)
    source = media_source(pid, 'original.wav')
    path = project(pid)
    executable = ROOT / '.separator-venv' / 'Scripts' / 'python.exe'
    if not executable.exists():
        raise HTTPException(400, '分轨运行环境尚未安装')
    def separate(jid):
        previous = metadata(path)['status']
        update(path,status='running')
        output = path / 'stems' / uuid.uuid4().hex[:12]
        jobs[jid]['message'] = '分轨模型首次下载或加载，随后进行音源分离'
        try:
            run_process([str(executable),str(ROOT/'separation_worker.py'),str(source),str(output),str(MODELS/'separator'),value.preset], path/'separation.log',14400)
            checkpoint()
            files = json.loads((output/'tracks.json').read_text(encoding='utf-8'))
            tracks = [{'file':(output/name).relative_to(path).as_posix(),'label':STEM_NAMES.get(Path(name).stem,'分轨音频')} for name in files]
            update(path,tracks=tracks,status='ready' if metadata(path).get('version') else 'input_ready',error='',modified=time.time())
            return {'project':pid,'tracks':tracks}
        except Exception:
            update(path,status=previous)
            raise
    return enqueue('separate',separate,resource=pid)


class SourceTranscription(BaseModel):
    source: str = 'original.wav'
    mode: Literal['local','remote'] = 'local'
    model: Literal['small','medium','large'] = 'medium'
    instruments: list[str] = []


@app.post('/api/source-transcribe/{pid}')
def transcribe_source(pid: str, value: SourceTranscription):
    ensure_idle(pid)
    source = media_source(pid,value.source)
    update(project(pid),status='queued',mode=value.mode,model=value.model,transcription_source=value.source,error='')
    return {**enqueue('transcribe',transcribe_job,pid,value.mode,value.model,value.instruments,source),'project':pid}


@app.get('/api/media/{pid}/audio/{key:path}')
def serve_audio(pid: str, key: str):
    path = project(pid)
    if re.fullmatch(r'preview-v-[0-9a-f]{12}\.wav',key):
        source = path/key
        if not source.is_file():
            raise HTTPException(404,'试听尚未生成')
    else:
        source = media_source(pid,key)
    return FileResponse(source,media_type='audio/wav')


@app.post('/api/score-audio/{pid}')
def score_audio(pid: str):
    path = project(pid)
    data = metadata(path)
    if not data.get('version'):
        raise HTTPException(400,'尚未生成谱面')
    key = 'preview-' + data['version'] + '.wav'
    def render(jid):
        jobs[jid]['message'] = '生成乐谱合成试听'
        from audio_preview import render_preview
        render_preview(playback(read_score(score_path(path))),path/key,checkpoint)
        return {'audio':'/api/media/'+pid+'/audio/'+key,'name':data['name']+' · 乐谱合成试听'}
    return enqueue('preview',render,resource=pid)


@app.get("/")
def home():
    return FileResponse(ROOT / "static" / "index.html")


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


def shutdown():
    with child_guard:
        for process in children:
            if process.poll() is None:
                process.kill()
                process.wait()
atexit.register(shutdown)


if __name__ == "__main__":
    import uvicorn
    port = 8765
    while port < 8800:
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
                break
            except OSError:
                port += 1
    url = f"http://127.0.0.1:{port}"
    print(f"MusicScore: {url}", flush=True)
    if "--no-browser" not in sys.argv:
        threading.Timer(2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=port)
