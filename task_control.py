import threading
import time

import psutil


class Cancelled(Exception):
    pass


class Control:
    def __init__(self):
        self.lock = threading.RLock()
        self.paused = False
        self.cancelled = False
        self.process = None
        self.waiting = False

    def tree(self):
        if not self.process:
            return []
        try:
            parent = psutil.Process(self.process.pid)
            return parent.children(recursive=True) + [parent]
        except psutil.NoSuchProcess:
            return []

    def action(self, action):
        with self.lock:
            if action == 'cancel':
                self.cancelled = True
                for process in self.tree():
                    try:
                        process.kill()
                    except psutil.NoSuchProcess:
                        pass
            else:
                self.paused = action == 'pause'
                for process in self.tree():
                    try:
                        process.suspend() if self.paused else process.resume()
                    except psutil.NoSuchProcess:
                        pass

    def checkpoint(self):
        self.waiting = self.paused
        while self.paused and not self.cancelled:
            time.sleep(.1)
        self.waiting = False
        if self.cancelled:
            raise Cancelled('任务已取消')


context = threading.local()
controls = {}


def checkpoint():
    control = getattr(context, 'control', None)
    if control:
        control.checkpoint()
