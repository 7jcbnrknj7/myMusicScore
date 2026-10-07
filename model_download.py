"""Official model downloads with byte-level progress for the local client."""
import argparse
from collections import deque
import json
from pathlib import Path
import sys
import threading
import time

FILES = ("config.json", "model.safetensors")


class Progress:
    def __init__(self, path, model):
        self.path = Path(path)
        self.model = model
        self.sizes = {}
        self.done = 0
        self.current = 0
        self.filename = ""
        self.samples = deque()
        self.lock = threading.RLock()
        self.phase = "获取模型文件信息"
        self.status = "running"
        self.last_write = 0
        self.write(force=True)

    def start_file(self, filename):
        with self.lock:
            self.filename = filename
            self.current = 0
            self.samples.clear()
            self.phase = "下载 " + filename
            self.write(force=True)

    def update(self, amount, total=None):
        with self.lock:
            if total is not None and total > 0:
                self.sizes[self.filename] = int(total)
            size = self.sizes.get(self.filename)
            self.current = max(0, min(int(amount), size)) if size is not None else max(0, int(amount))
            now = time.monotonic()
            self.samples.append((now, self.current))
            while len(self.samples) > 2 and now - self.samples[0][0] > 5:
                self.samples.popleft()
            self.write()

    def complete_file(self, path):
        with self.lock:
            actual = Path(path).stat().st_size
            expected = self.sizes.get(self.filename)
            if expected is not None and actual != expected:
                raise RuntimeError("模型文件大小不匹配，请重试下载")
            self.sizes[self.filename] = actual
            self.done += actual
            self.current = 0
            self.samples.clear()
            self.phase = "已保存 " + self.filename
            self.write(force=True)

    def write(self, force=False, message=""):
        now = time.monotonic()
        if not force and now - self.last_write < .2:
            return
        self.last_write = now
        total = sum(self.sizes.values()) if all(self.sizes.get(f, 0) > 0 for f in FILES) else None
        downloaded = self.done + self.current
        rate = None
        if len(self.samples) > 1 and self.status == "running":
            delta = self.samples[-1][0] - self.samples[0][0]
            if delta >= .2:
                rate = max(0, (self.samples[-1][1] - self.samples[0][1]) / delta)
        percent = min(99.9, downloaded / total * 100) if total else None
        if self.status == "complete":
            percent = 100
        value = {"model": self.model, "status": self.status, "phase": self.phase, "filename": self.filename,
                 "downloaded_bytes": downloaded, "total_bytes": total, "percent": percent,
                 "bytes_per_second": rate, "eta_seconds": (max(0, total - downloaded) / rate) if total and rate else None,
                 "updated": time.time(), "message": message}
        temporary = self.path.with_suffix(".tmp")
        try:
            temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            for attempt in range(5):
                try:
                    temporary.replace(self.path)
                    break
                except PermissionError:
                    if attempt == 4:
                        return
                    time.sleep(.01)
        except OSError:
            # A brief file-sharing conflict must not abort a multi-GB transfer.
            pass


def failure_message(exc):
    from huggingface_hub.errors import GatedRepoError, HfHubHTTPError
    if isinstance(exc, GatedRepoError):
        return "Hugging Face 拒绝模型访问：请确认账号已接受模型许可，且已保存该账号有下载权限的 Token（401/403）。"
    if isinstance(exc, HfHubHTTPError) and exc.response is not None and exc.response.status_code in (401, 403):
        return "Hugging Face 身份验证失败：请检查 Token 是否有效及模型下载权限（401/403）。"
    if isinstance(exc, OSError):
        return "模型下载失败：请检查网络连接、磁盘剩余空间与模型目录的写入权限。"
    return "模型下载失败，请检查网络和访问权限后重试。错误类型：" + type(exc).__name__


def download(model, progress_path):
    from huggingface_hub import HfApi, hf_hub_download
    from huggingface_hub.utils import tqdm
    tracker = Progress(progress_path, model)
    repo = "MuScriptor/muscriptor-" + model
    try:
        info = HfApi().model_info(repo, files_metadata=True)
        available = {f.rfilename: f.size for f in info.siblings}
        if any(f not in available for f in FILES):
            raise RuntimeError("官方仓库缺少模型文件")
        tracker.sizes = {f: available[f] for f in FILES if available[f] is not None}
        tracker.write(force=True)

        class ClientProgress(tqdm):
            def __init__(self, *args, **kwargs):
                kwargs["disable"] = True
                super().__init__(*args, **kwargs)
                tracker.update(self.n, self.total)

            def update(self, n=1):
                self.n += n or 0
                tracker.update(self.n, self.total)

        for filename in FILES:
            tracker.start_file(filename)
            path = hf_hub_download(repo, filename, revision=info.sha, tqdm_class=ClientProgress)
            tracker.complete_file(path)
        tracker.status = "complete"
        tracker.phase = "下载完成"
        tracker.write(force=True)
        return 0
    except Exception as exc:
        message = failure_message(exc)
        tracker.status = "failed"
        tracker.phase = "下载失败"
        tracker.write(force=True, message=message)
        print(message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("model", choices=("small", "medium", "large"))
    parser.add_argument("progress")
    args = parser.parse_args()
    sys.exit(download(args.model, args.progress))
