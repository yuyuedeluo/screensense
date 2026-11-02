"""取得畫面：用 ffmpeg 開一條管線一直讀，讀不到時退回 mss 輪詢截圖。

來源（source）：
- "desktop"：整個螢幕。Windows 優先用 ddagrab（桌面複製 API，省 CPU，比較抓得到遊戲），
  不行再用 gdigrab；其他系統用 mss。
- 影片檔路徑：拿來測試，或陪你看本機影片。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import numpy as np


class CaptureError(RuntimeError):
    pass


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise CaptureError("找不到 ffmpeg。Windows 可以用 winget install Gyan.FFmpeg 安裝。")
    return exe


def _ffmpeg_args(source: str, fps: float, width: int, height: int,
                 backend: str, realtime: bool) -> list[str]:
    out = ["-an", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    scale = f"scale={width}:{height}:flags=area"
    if source == "desktop":
        if backend == "ddagrab":
            return ["-f", "lavfi", "-i", f"ddagrab=framerate={fps}",
                    "-vf", f"hwdownload,format=bgra,{scale},format=rgb24", *out]
        if backend == "gdigrab":
            return ["-f", "gdigrab", "-framerate", str(fps), "-i", "desktop", "-vf", scale, *out]
        raise CaptureError(f"不認得的擷取方式：{backend}")
    if not Path(source).exists():
        raise CaptureError(f"找不到影片檔：{source}")
    pre = ["-re"] if realtime else []
    return [*pre, "-i", source, "-vf", f"fps={fps},{scale}", *out]


class FFmpegSource:
    """在背景讀 ffmpeg 吐出來的原始畫面；frames() 一張一張給你（RGB numpy）。"""

    def __init__(self, source: str = "desktop", fps: float = 8, width: int = 640, height: int = 360,
                 backend: str | None = None, realtime: bool = True):
        self.source, self.fps, self.width, self.height = source, fps, width, height
        self.realtime = realtime
        if backend is None:
            backend = "ddagrab" if (source == "desktop" and sys.platform == "win32") else "file"
        self.backend = backend
        self._proc: subprocess.Popen | None = None
        self._closed = False

    def _start(self, backend: str):
        args = [_ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin",
                *_ffmpeg_args(self.source, self.fps, self.width, self.height, backend, self.realtime)]
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        self._proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      bufsize=self.width * self.height * 3 * 2, creationflags=flags)

    def frames(self) -> Iterator[tuple[np.ndarray, float]]:
        size = self.width * self.height * 3
        backends = [self.backend] + (["gdigrab"] if self.backend == "ddagrab" else [])
        for i, be in enumerate(backends):
            self._start(be)
            proc = self._proc            # stop() 可能從別的執行緒把 self._proc 清掉，這裡留一份
            got_any = False
            while True:
                buf = proc.stdout.read(size)
                if len(buf) < size:
                    break
                got_any = True
                yield np.frombuffer(buf, np.uint8).reshape(self.height, self.width, 3), time.time()
            try:
                err = proc.stderr.read().decode(errors="replace").strip()
            except (OSError, ValueError):
                err = ""
            self.close()
            if self._closed:
                return
            if got_any or i == len(backends) - 1:
                if not got_any and err:
                    raise CaptureError(f"ffmpeg 擷取失敗（{be}）：{err[-300:]}")
                return
            # ddagrab 開不起來（舊版 ffmpeg、遠端桌面…）就換 gdigrab 再試

    def close(self, final: bool = False):
        p, self._proc = self._proc, None
        if final:
            self._closed = True
        if p and p.poll() is None:
            p.kill()
            p.wait(timeout=5)


class MSSSource:
    """沒有 ffmpeg 或非 Windows 時的退路：用 mss 定時截整個主螢幕。"""

    def __init__(self, fps: float = 4, width: int = 640, height: int = 360, monitor: int = 1):
        self.fps, self.width, self.height, self.monitor = fps, width, height, monitor
        self._stop = threading.Event()

    def frames(self) -> Iterator[tuple[np.ndarray, float]]:
        try:
            import mss
            from PIL import Image
        except ImportError as e:
            raise CaptureError("要用 mss 截圖，先 pip install mss") from e
        with mss.mss() as sct:
            mon = sct.monitors[self.monitor]
            step = 1.0 / self.fps
            while not self._stop.is_set():
                t0 = time.time()
                shot = sct.grab(mon)
                img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
                img = img.resize((self.width, self.height), Image.BILINEAR)
                yield np.asarray(img), t0
                time.sleep(max(0.0, step - (time.time() - t0)))

    def close(self):
        self._stop.set()


def open_source(source: str = "desktop", fps: float = 8, width: int = 640, height: int = 360,
                backend: str | None = None, realtime: bool = True):
    """挑一個能用的來源。backend 可指定 ddagrab、gdigrab、mss；不指定就自動。"""
    if backend == "mss" or (source == "desktop" and sys.platform != "win32"):
        return MSSSource(fps, width, height)
    if shutil.which("ffmpeg") is None:
        if source == "desktop":
            return MSSSource(fps, width, height)
        raise CaptureError("讀影片檔需要 ffmpeg")
    return FFmpegSource(source, fps, width, height, backend, realtime)
