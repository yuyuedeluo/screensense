"""最近幾秒的原畫質緩衝：放大看的時候，可以回到「那一刻」，而不是重拍現在。

另外開一條很省的擷取：每秒只拍 2 張原始解析度，由 ffmpeg 直接壓成 JPEG（C 寫的，很快），
程式只保留最近 N 秒。記憶體大約每張幾百 KB。
"""
from __future__ import annotations

import io
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np

from .capture import _ffmpeg

SOI, EOI = b"\xff\xd8", b"\xff\xd9"


def _args(source: str, fps: float, backend: str, quality: int) -> list[str]:
    out = ["-an", "-c:v", "mjpeg", "-q:v", str(quality), "-f", "image2pipe", "-"]
    if source == "desktop":
        if backend == "ddagrab":
            return ["-f", "lavfi", "-i", f"ddagrab=framerate={fps}", "-vf", "hwdownload,format=bgra,format=yuvj420p", *out]
        return ["-f", "gdigrab", "-framerate", str(fps), "-i", "desktop", "-vf", "format=yuvj420p", *out]
    return ["-re", "-i", source, "-vf", f"fps={fps},format=yuvj420p", *out]


class NativeBuffer:
    def __init__(self, source: str = "desktop", seconds: float = 10, fps: float = 2,
                 backend: str | None = None, quality: int = 4):
        self.source, self.seconds, self.fps, self.quality = source, seconds, fps, quality
        self.backend = backend or ("ddagrab" if sys.platform == "win32" else "gdigrab")
        self._frames: deque[tuple[float, bytes]] = deque()
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.error: str | None = None

    def start(self):
        if self.source != "desktop" and not Path(self.source).exists():
            self.error = f"找不到影片檔：{self.source}"
            return self
        if self.source == "desktop" and sys.platform != "win32":
            self.error = "原畫質緩衝只支援 Windows 桌面（或影片檔）"
            return self
        if self._thread is not None and self._thread.is_alive() and not self._stop.is_set():
            return self                 # 已經在跑
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="screensense-native", daemon=True)
        self._thread.start()
        return self

    def _run(self):
        backends = [self.backend] + (["gdigrab"] if self.backend == "ddagrab" else [])
        for be in backends:
            if self._stop.is_set():
                return
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            try:
                self._proc = subprocess.Popen(
                    [_ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin",
                     *_args(self.source, self.fps, be, self.quality)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
            except Exception as e:
                self.error = str(e)
                return
            got = self._read(self._proc)
            if got or self._stop.is_set():
                return
            try:
                self.error = self._proc.stderr.read().decode(errors="replace")[-300:] or f"{be} 拍不到畫面"
            except (OSError, ValueError):
                pass

    def _read(self, proc) -> bool:
        buf, got = b"", False
        while not self._stop.is_set():
            chunk = proc.stdout.read1(65536)   # 有多少讀多少，不要等滿 64 KB
            if not chunk:
                break
            buf += chunk
            while True:
                s = buf.find(SOI)
                e = buf.find(EOI, s + 2) if s >= 0 else -1
                if s < 0 or e < 0:
                    if s > 0:
                        buf = buf[s:]
                    break
                jpg, buf = buf[s:e + 2], buf[e + 2:]
                got = True
                now = time.time()
                with self._lock:
                    self._frames.append((now, jpg))
                    while self._frames and now - self._frames[0][0] > self.seconds:
                        self._frames.popleft()
        return got

    def stop(self):
        self._stop.set()
        p, self._proc = self._proc, None
        if p and p.poll() is None:
            p.kill()
        self.clear()

    def clear(self):
        with self._lock:
            self._frames.clear()

    def at(self, t: float, tolerance: float = 1.5) -> np.ndarray | None:
        """最接近時間 t 的那一張原畫質（RGB）；差太多就回傳 None。"""
        with self._lock:
            if not self._frames:
                return None
            ft, jpg = min(self._frames, key=lambda f: abs(f[0] - t))
        if abs(ft - t) > tolerance:
            return None
        from PIL import Image
        return np.asarray(Image.open(io.BytesIO(jpg)).convert("RGB"))

    def __len__(self):
        with self._lock:
            return len(self._frames)
